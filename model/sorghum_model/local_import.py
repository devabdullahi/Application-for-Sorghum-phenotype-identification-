"""Adds a folder of already-downloaded or team photos to the manifest.

Used for the datasets the research notes list that cannot be fetched through an API
(SorghumWeedDataset, Sorghum Disease Image Dataset, GrainSet, UQ panicle crops) and for our
own photos (millets, no-plant board shots). Every import must name its annotator and date,
because unverified labels are excluded from training.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sorghum_model.manifest import ImageRecord, sha256_of_file

IMAGE_SUFFIXES: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})


class GroupBy(Enum):
    """How photos of one folder are grouped for splitting."""

    SUBFOLDER = "subfolder"
    """The first subfolder below the import folder names a plant, plot or accession."""

    FILE = "file"
    """Every photo is its own group. Only for sources with one photo per plant, since
    photos of the same plant would otherwise leak across splits."""


@dataclass(frozen=True)
class FolderSource:
    """What every photo in an imported folder has in common."""

    class_name: str
    source: str
    license: str
    attribution: str
    annotator: str
    labelled_on: str
    group_by: GroupBy


def import_folder(folder: Path, data_root: Path, source: FolderSource) -> list[ImageRecord]:
    """Returns one record per image below `folder`, which must be inside `data_root`."""
    folder = folder.resolve()
    data_root = data_root.resolve()
    if not folder.is_relative_to(data_root):
        raise ValueError(f"{folder} must be inside the data root {data_root}")
    if not source.annotator:
        raise ValueError("annotator is required: unverified labels are excluded from training")

    records = []
    for image in sorted(folder.rglob("*")):
        if image.suffix.lower() not in IMAGE_SUFFIXES or not image.is_file():
            continue
        relative_to_folder = image.relative_to(folder)
        records.append(
            ImageRecord(
                image_path=image.relative_to(data_root).as_posix(),
                class_name=source.class_name,
                source=source.source,
                source_id=relative_to_folder.as_posix(),
                group_id=f"{source.source}-{_group_name(relative_to_folder, source.group_by)}",
                license=source.license,
                attribution=source.attribution,
                label_source=f"{source.source}; annotator {source.annotator}",
                labelled_on=source.labelled_on,
                sha256=sha256_of_file(image),
            )
        )
    return records


def _group_name(relative_path: Path, group_by: GroupBy) -> str:
    if group_by is GroupBy.FILE:
        return relative_path.as_posix()
    if len(relative_path.parts) < 2:
        raise ValueError(
            f"{relative_path} is not inside a subfolder; group-by subfolder needs "
            "one subfolder per plant, plot or accession"
        )
    return relative_path.parts[0]
