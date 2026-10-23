"""Adds a folder of already-downloaded or team photos to the manifest.

Used for public datasets once `mendeley.py` or `figshare.py` has downloaded and laid them out
(SorghumWeedDataset, Sorghum Disease Image Dataset, GrainSet), for datasets without an API
(UQ panicle crops) and for our own photos (millets, no-plant board shots). Every import must
name its annotator and date, because unverified labels are excluded from training.
"""

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from sorghum_model.manifest import ImageRecord, LabelStatus, sha256_of_file

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
        # Hidden files and folders are never photos. On exFAT drives macOS writes a
        # "._<name>" metadata file next to every file, with the same image suffix.
        if any(part.startswith(".") for part in relative_to_folder.parts):
            continue
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
                label_status=LabelStatus.VERIFIED,
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


def import_class_folders(
    images_root: Path, data_root: Path, source: FolderSource
) -> list[ImageRecord]:
    """Imports every `<class>/<group>/<file>` below `images_root`, one class folder at a time.

    Used for public datasets laid out by `dataset_layout`; `source.class_name` is replaced by
    each folder's name, which must be a species class.
    """
    records = []
    for class_folder in sorted(images_root.iterdir()):
        if not class_folder.is_dir() or class_folder.name.startswith("."):
            continue
        records.extend(
            import_folder(class_folder, data_root, replace(source, class_name=class_folder.name))
        )
    return records
