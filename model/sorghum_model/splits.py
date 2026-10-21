"""Assigns photos to train / validation / test by group, never by image.

A group is a plant, plot, accession or iNaturalist observer (see ImageRecord.group_id). The
split of a group is derived from a hash of its id, so adding new photos never moves an
existing group to another split, and the committed split manifest stays valid.
"""

import csv
import hashlib
from collections import Counter
from enum import Enum
from pathlib import Path

from sorghum_model.manifest import ImageRecord


class Split(Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


SPLIT_COLUMNS: tuple[str, ...] = ("sha256", "source", "source_id", "group_id", "split")


def assign_split(group_id: str, validation_fraction: float, test_fraction: float, salt: str) -> Split:
    """Maps a group id to a split, deterministically.

    `salt` names the split scheme (e.g. "species-v1"); changing it reshuffles every group,
    which is only correct together with a new model version.
    """
    if not 0 < validation_fraction < 1 or not 0 < test_fraction < 1:
        raise ValueError("validation and test fractions must be between 0 and 1")
    if validation_fraction + test_fraction >= 1:
        raise ValueError("validation and test fractions must leave room for training data")

    digest = hashlib.sha256(f"{salt}:{group_id}".encode()).digest()
    # First 8 bytes as a uniform number in [0, 1).
    position = int.from_bytes(digest[:8], "big") / 2**64
    if position < test_fraction:
        return Split.TEST
    if position < test_fraction + validation_fraction:
        return Split.VALIDATION
    return Split.TRAIN


def split_records(
    records: list[ImageRecord], validation_fraction: float, test_fraction: float, salt: str
) -> dict[str, Split]:
    """Returns the split of every record, keyed by sha256."""
    return {
        record.sha256: assign_split(record.group_id, validation_fraction, test_fraction, salt)
        for record in records
    }


def count_per_class_and_split(
    records: list[ImageRecord], splits: dict[str, Split]
) -> Counter[tuple[str, Split]]:
    """Counts photos per (class, split), for the minimum-size check and the training report."""
    return Counter((record.class_name, splits[record.sha256]) for record in records)


def find_undersized_classes(
    counts: Counter[tuple[str, Split]],
    class_names: tuple[str, ...],
    min_train: int,
    min_evaluation: int,
) -> list[str]:
    """Describes every class and split below its minimum size; empty when training can start."""
    problems = []
    for class_name in class_names:
        for split in Split:
            minimum = min_train if split is Split.TRAIN else min_evaluation
            found = counts[(class_name, split)]
            if found < minimum:
                problems.append(f"{class_name}: {found} {split.value} photos, need {minimum}")
    return problems


def write_split_manifest(records: list[ImageRecord], splits: dict[str, Split], path: Path) -> None:
    """Writes the committed split manifest, sorted for stable diffs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SPLIT_COLUMNS)
        writer.writeheader()
        for record in sorted(records, key=lambda r: (r.source, r.source_id)):
            writer.writerow(
                {
                    "sha256": record.sha256,
                    "source": record.source,
                    "source_id": record.source_id,
                    "group_id": record.group_id,
                    "split": splits[record.sha256].value,
                }
            )


def read_split_manifest(path: Path) -> dict[str, Split]:
    """Reads a split manifest written by write_split_manifest, keyed by sha256."""
    with path.open(newline="", encoding="utf-8") as file:
        return {row["sha256"]: Split(row["split"]) for row in csv.DictReader(file)}
