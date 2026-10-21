"""Image manifest: one row per training photo, with its label provenance and licence.

The manifest is committed; the images are not. Every row carries enough to re-download or
re-locate the photo, check it has not changed (sha256), credit its author, and trace who
labelled it.
"""

import csv
import hashlib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from sorghum_model.species_classes import SPECIES_CLASS_NAMES

# Licences allowed in training. CC BY-NC and unlicensed photos are excluded so the model can
# ship in a commercial app (decision 2026-10-21). CC BY and CC BY-SA require attribution,
# which each row keeps. Codes follow iNaturalist's `license_code`; local datasets use the same
# codes and put the licence version in the attribution.
COMMERCIAL_LICENSES: frozenset[str] = frozenset({"cc0", "cc-by", "cc-by-sa"})


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
        license: licence code, one of COMMERCIAL_LICENSES.
        attribution: credit line required by the licence.
        label_source: who or what verified the label.
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
    labelled_on: str
    sha256: str

    def __post_init__(self) -> None:
        if self.class_name not in SPECIES_CLASS_NAMES:
            raise ValueError(f"{self.source}/{self.source_id}: unknown class {self.class_name!r}")
        if self.license not in COMMERCIAL_LICENSES:
            raise ValueError(
                f"{self.source}/{self.source_id}: licence {self.license!r} is not allowed; "
                f"expected one of {sorted(COMMERCIAL_LICENSES)}"
            )
        for required in ("image_path", "source", "source_id", "group_id", "label_source", "sha256"):
            if not getattr(self, required):
                raise ValueError(f"{self.source}/{self.source_id}: {required} is empty")


MANIFEST_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(ImageRecord))


def write_manifest(records: list[ImageRecord], path: Path) -> None:
    """Writes records sorted by source and id, so re-running a download gives a stable diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda r: (r.source, r.source_id))
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for record in ordered:
            writer.writerow(asdict(record))


def read_manifest(path: Path) -> list[ImageRecord]:
    """Reads and validates a manifest written by write_manifest."""
    with path.open(newline="", encoding="utf-8") as file:
        return [ImageRecord(**row) for row in csv.DictReader(file)]


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


def sha256_of_file(path: Path) -> str:
    """Returns the hex sha256 of a file, read in chunks so large images do not load at once."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
