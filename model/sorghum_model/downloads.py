"""Polite HTTP for the photo-source modules: pacing, JSON requests and resumable downloads.

Every source (iNaturalist, GBIF, Wikimedia Commons, Mendeley Data, Figshare, Flickr) goes
through here, so they all send the same User-Agent, wait between requests and never leave a
truncated file that a later run would mistake for a finished one. This is a developer tool
that runs on a workstation; nothing here ships in the app, and the app never uses the network.
"""

import hashlib
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from sorghum_model.manifest import ImageRecord, sha256_of_file

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


def download_file(
    url: str,
    destination: Path,
    expected_md5: str | None = None,
    expected_sha256: str | None = None,
) -> None:
    """Downloads `url` to `destination`, resuming an interrupted download.

    Bytes go to `<destination>.part` first, and the file is renamed only once complete (and,
    when a published checksum is given, verified), so a crash never leaves a truncated file
    behind. A retry, or a later run, continues the `.part` file with an HTTP Range request.
    An existing `destination` is trusted and not downloaded again.
    """
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
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
        with partial.open(mode) as file:
            while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                file.write(chunk)


def _with_retries(attempt: Callable[[], T]) -> T:
    """Runs `attempt` after the shared pacer, retrying network errors, 5xx and 429.

    Other 4xx errors mean the request itself is wrong (a dead link, a bad parameter), so they
    are raised at once.
    """
    for wait_seconds in (*RETRY_WAITS_SECONDS, None):
        PACER.wait()
        try:
            return attempt()
        except urllib.error.HTTPError as error:
            if wait_seconds is None or not (error.code == 429 or error.code >= 500):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            if wait_seconds is None:
                raise
        time.sleep(wait_seconds)
    raise AssertionError("unreachable: the last attempt returns or raises")


def _digest_of_file(path: Path, algorithm: str) -> str:
    # Figshare publishes md5 and Mendeley sha256 checksums; files are verified against whichever
    # the source publishes.
    digest = hashlib.new(algorithm, usedforsecurity=False)
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()
