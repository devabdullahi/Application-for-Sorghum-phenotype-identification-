"""Polite HTTP for the photo-source modules: pacing, JSON requests and resumable downloads.

Every source (iNaturalist, GBIF, Wikimedia Commons, Mendeley Data, Figshare, Flickr) goes
through here, so they all send the same User-Agent, wait between requests and never leave a
truncated file that a later run would mistake for a finished one. This is a developer tool
that runs on a workstation; nothing here ships in the app, and the app never uses the network.

Run one process per source and per host. The pacer below is per process, so two processes
talking to the same API (say two `inat-download` runs) together send twice the polite rate;
the manifest lock (`manifest.manifest_lock`) refuses a second process on the same source.
"""

import email.utils
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from sorghum_model.manifest import ImageRecord, process_is_running, sha256_of_file

# Wikimedia's User-Agent policy asks for a way to contact the operator; the repository URL
# is that contact. The other APIs only ask that the client names itself.
USER_AGENT = (
    "sorghum-model-training/0.1 "
    "(https://github.com/devabdullahi/Application-for-Sorghum-phenotype-identification-; "
    "offline sorghum identification research)"
)

# iNaturalist, GBIF and Wikimedia all ask scripted clients to stay at or below about one
# request per second. We use it for every source, including file downloads.
SECONDS_BETWEEN_REQUESTS = 1.0

REQUEST_TIMEOUT_SECONDS = 60

# Waits before retrying an API request that failed with a network error, a 5xx or a 429.
# Downloads run unattended for hours, and one transient error must not end the whole run;
# a fourth failure is real and is raised.
RETRY_WAITS_SECONDS: tuple[float, ...] = (10.0, 30.0, 90.0)

# Longest Retry-After we honour. A server asking for more is effectively down; the request
# fails and the photo is counted as a failed download instead of stalling the run for hours.
MAX_RETRY_AFTER_SECONDS = 15 * 60.0

# Archives are read and written in 1 MiB chunks so a multi-gigabyte zip never sits in memory.
DOWNLOAD_CHUNK_BYTES = 1 << 20


class RequestPacer:
    """Keeps at least `seconds_between_requests` between consecutive requests.

    One pacer is shared by everything in a process, so a download loop and its API paging
    together stay under the limit. Not thread-safe: the downloaders are single-threaded.
    """

    def __init__(
        self,
        seconds_between_requests: float = SECONDS_BETWEEN_REQUESTS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if seconds_between_requests < 0:
            raise ValueError("seconds_between_requests must not be negative")
        self._interval = seconds_between_requests
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None

    def wait(self) -> None:
        """Sleeps until the next request is allowed, then records it as sent."""
        if self._last_request is not None:
            remaining = self._interval - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()


PACER = RequestPacer()

T = TypeVar("T")


def get_json(url: str, params: dict | None = None) -> dict:
    """GETs a JSON document, waiting for the shared pacer first and retrying transient errors.

    List values in `params` become repeated query parameters (GBIF's `license=A&license=B`).
    """
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    def fetch() -> dict:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.load(response)

    return _with_retries(fetch)


def get_text(url: str) -> str:
    """GETs a text page (HTML), waiting for the shared pacer first and retrying transient errors.

    For sources with no JSON API (GRIN-Global's study pages). Decoded as UTF-8; undecodable
    bytes are replaced, because only the markup around the labels is parsed.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    def fetch() -> str:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="replace")

    return _with_retries(fetch)


def download_file(
    url: str,
    destination: Path,
    expected_md5: str | None = None,
    expected_sha256: str | None = None,
) -> None:
    """Downloads `url` to `destination`, resuming an interrupted download.

    Bytes go to `<destination>.<pid>.part` first, and the file is renamed only once complete
    (and, when a published checksum is given, verified), so a crash never leaves a truncated
    file behind. The pid keeps two processes from appending to one file. A retry, or a later
    run, continues the bytes with an HTTP Range request: a later run first adopts the `.part`
    of a process that is no longer running. An existing `destination` is trusted and not
    downloaded again.
    """
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = partial_path(destination)
    _adopt_abandoned_part(destination, partial)
    _with_retries(lambda: _append_remaining_bytes(url, partial))

    for algorithm, expected in (("md5", expected_md5), ("sha256", expected_sha256)):
        if expected is None:
            continue
        actual = _digest_of_file(partial, algorithm)
        if actual != expected.lower():
            # A corrupt .part would make every resume fail the same way, so start over.
            partial.unlink()
            raise ValueError(f"{url}: {algorithm} {actual} does not match the published {expected}")
    partial.rename(destination)


@dataclass(frozen=True)
class PhotoToDownload:
    """A photo selected from a source's API response, before its file exists locally.

    `record_without_file` holds every ImageRecord field except sha256, which needs the file.
    """

    url: str
    record_without_file: dict[str, str]


def download_photo(photo: PhotoToDownload, data_root: Path) -> ImageRecord:
    """Downloads a photo unless it is already on disk, and returns its manifest row."""
    destination = data_root / photo.record_without_file["image_path"]
    download_file(photo.url, destination)
    return ImageRecord(**photo.record_without_file, sha256=sha256_of_file(destination))


def partial_path(destination: Path) -> Path:
    """Where this process writes `destination` until it is complete."""
    return destination.with_name(f"{destination.name}.{os.getpid()}.part")


def _adopt_abandoned_part(destination: Path, partial: Path) -> None:
    """Takes over the largest `.part` of `destination` left by a process that has ended.

    Covers `<name>.<pid>.part` from earlier runs and the plain `<name>.part` that versions
    before the pid suffix wrote, so restarting a multi-gigabyte download resumes it. A part
    whose process still runs is left alone.
    """
    if partial.exists():
        return
    pattern = re.compile(re.escape(destination.name) + r"(?:\.(\d+))?\.part")
    abandoned = []
    for candidate in destination.parent.iterdir():
        match = pattern.fullmatch(candidate.name)
        if match is None or candidate == partial:
            continue
        owner = match.group(1)
        if owner is not None and process_is_running(int(owner)):
            continue
        abandoned.append(candidate)
    if not abandoned:
        return
    largest = max(abandoned, key=lambda path: path.stat().st_size)
    try:
        largest.rename(partial)
    except FileNotFoundError:
        pass  # another process adopted it first; start a fresh part



def _append_remaining_bytes(url: str, partial: Path) -> None:
    """Fetches the bytes `partial` does not have yet; one attempt, no retry."""
    already_have = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if already_have:
        headers["Range"] = f"bytes={already_have}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as error:
        # 416: the .part file already holds every byte; only the rename is missing.
        if error.code == 416 and already_have:
            return
        raise
    with response:
        # A server that ignores Range answers 200 with the whole file: start over.
        mode = "ab" if response.status == 206 else "wb"
        expected = response.headers.get("Content-Length") if response.headers else None
        received = 0
        with partial.open(mode) as file:
            while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                file.write(chunk)
                received += len(chunk)
    # urllib returns a short body without an error when the connection drops mid-file. The
    # bytes stay in the .part, and raising a connection error makes the retry resume them.
    if expected is not None and expected.isdigit() and received < int(expected):
        raise ConnectionError(f"{url}: connection closed after {received} of {expected} bytes")


def _with_retries(attempt: Callable[[], T]) -> T:
    """Runs `attempt` after the shared pacer, retrying network errors, 5xx and 429.

    Other 4xx errors mean the request itself is wrong (a dead link, a bad parameter), so they
    are raised at once. A 429 or 503 with Retry-After waits at least as long as the server
    asks (up to MAX_RETRY_AFTER_SECONDS).
    """
    for wait_seconds in (*RETRY_WAITS_SECONDS, None):
        PACER.wait()
        try:
            return attempt()
        except urllib.error.HTTPError as error:
            if wait_seconds is None or not (error.code == 429 or error.code >= 500):
                raise
            retry_after = retry_after_seconds(error.headers.get("Retry-After") if error.headers else None)
            if retry_after is not None:
                if retry_after > MAX_RETRY_AFTER_SECONDS:
                    raise
                wait_seconds = max(wait_seconds, retry_after)
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            if wait_seconds is None:
                raise
        time.sleep(wait_seconds)
    raise AssertionError("unreachable: the last attempt returns or raises")


def retry_after_seconds(value: str | None, now: float | None = None) -> float | None:
    """Parses a Retry-After header: delay seconds or an HTTP date. None when absent or invalid."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        moment = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    current = time.time() if now is None else now
    return max(moment.timestamp() - current, 0.0)


def _digest_of_file(path: Path, algorithm: str) -> str:
    # Figshare publishes md5 and Mendeley sha256 checksums; files are verified against whichever
    # the source publishes.
    digest = hashlib.new(algorithm, usedforsecurity=False)
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()
