"""Image manifest: one row per training photo, with its label provenance and licence.

The manifest is committed; the images are not. Every row carries enough to re-download or
re-locate the photo, check it has not changed (sha256), credit its author, and trace who
labelled it.
"""

import contextlib
import csv
import hashlib
import os
import re
import time
import urllib.parse
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from pathlib import Path

from sorghum_model.species_classes import SPECIES_CLASS_NAMES

# Licences allowed in training. The app is a non-commercial research tool (ARCHITECTURE.md
# section 2), so CC BY-NC and CC BY-NC-SA photos are allowed (decision 2026-10-23,
# ASSUMPTION - confirm before any commercial release: the model would then have to be
# retrained without NC photos). No-derivatives (ND) licences stay excluded, because training
# and resizing make a derivative; unlicensed and all-rights-reserved photos stay excluded.
# Every CC licence requires attribution, which each row keeps. Codes follow iNaturalist's
# `license_code`; other sources are mapped with `normalize_license_code`, and the licence
# version goes in the attribution.
ALLOWED_LICENSES: frozenset[str] = frozenset({"cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa"})

# Licences that forbid commercial use. Training data under any of these makes the model
# non-commercial, which the exported metadata states (`trainingData.nonCommercial`).
NON_COMMERCIAL_LICENSES: frozenset[str] = frozenset({"cc-by-nc", "cc-by-nc-sa"})

# Every Creative Commons code `normalize_license_code` can return, allowed or not.
KNOWN_LICENSE_CODES: frozenset[str] = ALLOWED_LICENSES | {"cc-by-nd", "cc-by-nc-nd"}


class LabelStatus(StrEnum):
    """Whether a photo's label may be trained on (CLAUDE.md: unverified labels are excluded)."""

    VERIFIED = "verified"
    """Checked by people (iNaturalist research grade, GBIF identifiers, dataset annotators,
    our team) or confirmed by the BioCLIP 2 review (`label_review.py`)."""

    UNREVIEWED = "unreviewed"
    """Assigned by a category or a text search only (Wikimedia Commons, Flickr). Excluded
    from split, train and export until `sorghum-model review-labels` verifies it."""


# MIGRATION (drop once every committed manifest has a `label_status` column): manifests
# written before the column existed are read with this rule. Only Commons and Flickr labels
# come from a category or a text search; every other source's labels were checked by people.
LEGACY_UNREVIEWED_SOURCES: frozenset[str] = frozenset({"commons", "flickr"})


@dataclass(frozen=True)
class ImageRecord:
    """One labelled training photo.

    Attributes:
        image_path: path relative to the data root, using "/" separators.
        class_name: species class from `species_classes.SPECIES_CLASSES`.
        source: dataset the photo came from, e.g. "inaturalist" or "team-photos".
        source_id: id of the photo inside its source.
        group_id: photos sharing a group always land in the same split. For iNaturalist this
            is the observer, so one person's field (same plants, light and phone) cannot leak
            between train and test.
        license: licence code, one of ALLOWED_LICENSES.
        attribution: credit line required by the licence.
        label_source: who or what verified the label.
        label_status: whether training may use the label (see LabelStatus).
        labelled_on: ISO date the label refers to (observation or annotation date).
        sha256: checksum of the image file.
    """

    image_path: str
    class_name: str
    source: str
    source_id: str
    group_id: str
    license: str
    attribution: str
    label_source: str
    label_status: LabelStatus
    labelled_on: str
    sha256: str

    def __post_init__(self) -> None:
        try:
            # Frozen dataclass: the CSV gives a string, which is stored as the enum.
            object.__setattr__(self, "label_status", LabelStatus(self.label_status))
        except ValueError:
            raise ValueError(
                f"{self.source}/{self.source_id}: label_status {self.label_status!r} must be "
                f"one of {[status.value for status in LabelStatus]}"
            ) from None
        if self.class_name not in SPECIES_CLASS_NAMES:
            raise ValueError(f"{self.source}/{self.source_id}: unknown class {self.class_name!r}")
        if self.license not in ALLOWED_LICENSES:
            raise ValueError(
                f"{self.source}/{self.source_id}: licence {self.license!r} is not allowed; "
                f"expected one of {sorted(ALLOWED_LICENSES)}"
            )
        for required in ("image_path", "source", "source_id", "group_id", "label_source", "sha256"):
            if not getattr(self, required):
                raise ValueError(f"{self.source}/{self.source_id}: {required} is empty")


MANIFEST_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(ImageRecord))


def write_manifest(records: list[ImageRecord], path: Path) -> None:
    """Writes records sorted by source and id, so re-running a download gives a stable diff.

    The rows go to a temporary file that then replaces the manifest in one step, so a crash
    or a full disk mid-write never leaves a truncated manifest behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda r: (r.source, r.source_id))
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=MANIFEST_COLUMNS)
            writer.writeheader()
            for record in ordered:
                writer.writerow(asdict(record))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_manifest(path: Path) -> list[ImageRecord]:
    """Reads and validates a manifest written by write_manifest.

    Rows without `label_status` (manifests from before the column) get it from
    LEGACY_UNREVIEWED_SOURCES.
    """
    with path.open(newline="", encoding="utf-8") as file:
        records = []
        for row in csv.DictReader(file):
            if not row.get("label_status"):
                row["label_status"] = (
                    LabelStatus.UNREVIEWED
                    if row.get("source") in LEGACY_UNREVIEWED_SOURCES
                    else LabelStatus.VERIFIED
                )
            records.append(ImageRecord(**row))
        return records


def verified_records(records: Iterable[ImageRecord]) -> list[ImageRecord]:
    """The records whose labels training may use; split, train and export see only these."""
    return [record for record in records if record.label_status is LabelStatus.VERIFIED]


# An empty lock file younger than this is treated as held (its owner is still writing its
# pid); an older one is a leftover.
FRESH_LOCK_SECONDS = 10.0


class ManifestLockedError(ValueError):
    """Another live process is writing the same manifest."""


@contextlib.contextmanager
def manifest_lock(manifest: Path) -> Iterator[None]:
    """Holds `<manifest>.lock` while one process writes the manifest.

    Two processes on one source would each replace the other's rows and race on the same
    photo files, so a second one is refused. The lock file holds the owner's pid; a lock left
    by a process that no longer runs (killed, crashed) is taken over. Only one machine writes
    the data drive, so a pid check is enough.
    """
    lock = manifest.with_name(manifest.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            owner = _lock_owner(lock)
            # An empty lock may be one another process created a moment ago and has not
            # written its pid to yet.
            is_being_created = owner is None and _age_seconds(lock) < FRESH_LOCK_SECONDS
            if is_being_created or (owner is not None and process_is_running(owner)):
                raise ManifestLockedError(
                    f"{manifest} is being written by process {owner or '(starting up)'}. "
                    f"Run one process per source; if that process is gone, delete {lock}."
                ) from None
            # Stale: the owner died without cleaning up.
            lock.unlink(missing_ok=True)
    with os.fdopen(descriptor, "w") as file:
        file.write(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _age_seconds(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _lock_owner(lock: Path) -> int | None:
    try:
        return int(lock.read_text().strip())
    except (OSError, ValueError):
        return None


def process_is_running(pid: int) -> bool:
    """Whether a process with this pid exists (signal 0 checks without signalling)."""
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    return True


def merge_manifests(record_lists: list[list[ImageRecord]]) -> list[ImageRecord]:
    """Combines manifests and removes duplicate photos.

    The same file (same sha256) can appear in two sources. With the same label one copy is
    kept; with different labels the photo is ambiguous and both copies are dropped, because
    keeping either would train on a label someone disagrees with.
    """
    by_checksum: dict[str, list[ImageRecord]] = {}
    for records in record_lists:
        for record in records:
            by_checksum.setdefault(record.sha256, []).append(record)

    merged = []
    for copies in by_checksum.values():
        if len({copy.class_name for copy in copies}) == 1:
            merged.append(copies[0])
    return merged


def normalize_license_code(text: str) -> str | None:
    """Maps a licence as a source writes it to our code (e.g. "cc-by-sa"), or None if unknown.

    Sources spell licences differently: GBIF uses enums ("CC_BY_NC_4_0") and URLs
    ("http://creativecommons.org/licenses/by-nc-nd/4.0/"), Wikimedia Commons uses
    "cc-by-sa-3.0-de", Mendeley and Figshare use "CC BY 4.0". The version and jurisdiction port
    are dropped, since they do not change what training may do. None means "not a Creative
    Commons licence we recognise" (public domain marks, GFDL, all rights reserved), and the
    caller skips the photo. A returned code may still be disallowed (ND); check it against
    ALLOWED_LICENSES.
    """
    value = text.strip().lower()
    if "creativecommons.org" in value:
        url = value if "://" in value else f"https://{value}"
        path = [part for part in urllib.parse.urlparse(url).path.split("/") if part]
        if path[:2] == ["publicdomain", "zero"]:
            return "cc0"
        if len(path) < 2 or path[0] != "licenses":
            return None
        value = f"cc-{path[1]}"
    value = re.sub(r"[\s_]+", "-", value)
    # Drop "-4.0", "-1-0" (from GBIF's "CC0_1_0"), "-3.0-de" and similar version and port
    # suffixes.
    value = re.sub(r"-\d+([.-]\d+)*(-[a-z]{2,})?$", "", value)
    return value if value in KNOWN_LICENSE_CODES else None


def license_summary(records: Iterable[ImageRecord]) -> dict:
    """Describes the licences of a training set, for `trainingData` in traits-vN.json.

    Returns the sorted licence codes used and whether any of them is non-commercial, so a
    reader of the model file can tell whether the model may be used commercially.
    """
    codes = sorted({record.license for record in records})
    return {
        "licenses": codes,
        "nonCommercial": any(code in NON_COMMERCIAL_LICENSES for code in codes),
    }


def sha256_of_file(path: Path) -> str:
    """Returns the hex sha256 of a file, read in chunks so large images do not load at once."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
