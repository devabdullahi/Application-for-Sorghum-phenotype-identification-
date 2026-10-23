"""Lays out downloaded public datasets as `<class>/<group>/<file>` for `import_folder`.

The public datasets (Mendeley Data, Figshare) ship in their authors' layouts, with class
names of their own and no plant or plot ids. Each `*_path` function here maps one file of a
dataset to the path it gets below the dataset's images folder; `import_class_folders` then
imports each class folder with the existing folder importer, so label provenance, hidden-file
skipping and checksums work exactly as for our own photos.

Paths are rebuilt from the file name alone, never copied from the archive, so a crafted
archive entry ("../../x") cannot write outside the images folder.
"""

import hashlib
import os
import re
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from sorghum_model.local_import import IMAGE_SUFFIXES

# SorghumWeedDataset_Classification class folders (Mendeley 4gkcyxjyss). Its weed grasses are
# field grasses next to young sorghum: hard negatives like `other_grass`. Broadleaf weeds are
# dicots, i.e. `other_plant`.
SORGHUM_WEED_CLASSES: dict[str, str] = {
    "Class0_Sorghum": "sorghum_bicolor",
    "Class1_Grass": "other_grass",
    "Class2_BroadLeafWeed": "other_plant",
}

# GrainSet names each kernel "Grainset_<crop>_<capture time>_<kernel>_p600s.png". Kernels
# with the same capture time were imaged in one session from one sample, so they form a group.
# Checked on the real v2 archives on 2026-10-23: sorghum.zip has 102,750 kernel images (plus
# as many masks under "sorg/mask/", skipped) in 3,316 capture sessions of 12-55 kernels;
# maize.zip has 19,000 kernels in 3,324 sessions of 1-15. Every name carries a capture time,
# so grouping is per session, never per kernel.
GRAINSET_CAPTURE_TIME = re.compile(r"_(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})_")


def sequence_block(stem: str, images_per_group: int) -> str:
    """Groups a running-numbered file name ("Rust123", "SorghumTrain (12)") into a block.

    Files 1..N share block 0000, N+1..2N block 0001, and so on, each within its own name
    prefix. Names without a number are their own group.
    """
    match = re.search(r"(\d+)\D*$", stem)
    if match is None:
        return _slug(stem)
    prefix = stem[: match.start()]
    block = (int(match.group(1)) - 1) // images_per_group
    return f"{_slug(prefix) or 'file'}-{max(block, 0):04d}"


def sorghum_weed_path(entry_name: str, images_per_group: int) -> str | None:
    """Maps "SorghumWeedDataset_Classification/Train/Class0_Sorghum/SorghumTrain (12).jpeg".

    The authors' Train/Validate/Test split is kept in the group name only for traceability;
    our own grouped split decides where each group goes.
    """
    path = PurePosixPath(entry_name)
    if not _is_photo(path) or len(path.parts) < 3:
        return None
    author_split, class_folder = path.parts[-3], path.parts[-2]
    class_name = SORGHUM_WEED_CLASSES.get(class_folder)
    if class_name is None:
        return None
    group = f"{_slug(author_split)}-{_slug(class_folder)}-{sequence_block(path.stem, images_per_group)}"
    return f"{class_name}/{group}/{path.name}"


def sorghum_disease_path(file_name: str, images_per_group: int) -> str | None:
    """Maps a Sorghum Disease Image Dataset file ("Rust123.jpg"); every photo is sorghum.

    The disease name is the file name prefix, so blocks never mix diseases.
    """
    path = PurePosixPath(file_name)
    if not _is_photo(path):
        return None
    return f"sorghum_bicolor/{sequence_block(path.stem, images_per_group)}/{path.name}"


def grainset_path(entry_name: str, class_name: str) -> str | None:
    """Maps a GrainSet kernel image; segmentation masks are skipped."""
    path = PurePosixPath(entry_name)
    if not _is_photo(path) or "mask" in (part.lower() for part in path.parts[:-1]):
        return None
    match = GRAINSET_CAPTURE_TIME.search(path.name)
    group = f"capture-{match.group(1)}" if match else _slug(path.stem)
    return f"{class_name}/{group}/{path.name}"


def extract_zip(
    zip_path: Path,
    images_root: Path,
    path_for_entry: Callable[[str], str | None],
    max_images: int | None = None,
) -> int:
    """Extracts the photos `path_for_entry` maps, and returns how many are in place.

    With `max_images`, a fixed pseudo-random sample is kept: entries are ordered by the hash
    of their name, so re-running picks the same files and a larger cap only adds files.
    Files already extracted are skipped, so an interrupted run resumes.
    """
    with zipfile.ZipFile(zip_path) as archive:
        mapped = []
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            relative = path_for_entry(entry.filename)
            if relative is not None:
                mapped.append((entry, relative))
        if max_images is not None:
            mapped.sort(key=lambda pair: hashlib.sha256(pair[0].filename.encode()).hexdigest())
            mapped = mapped[:max_images]
        for entry, relative in mapped:
            destination = images_root / relative
            if destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(f"{destination.name}.{os.getpid()}.part")
            with archive.open(entry) as source, partial.open("wb") as target:
                shutil.copyfileobj(source, target)
            partial.rename(destination)
    return len(mapped)


def safe_file_name(name: str) -> str:
    """The last component of a file name a remote API gave us, refusing one that is unsafe.

    Used where the name becomes a local path (Mendeley archive names), so "../x" or "/etc/x"
    can never write outside the target folder.
    """
    base = PurePosixPath(name.replace("\\", "/")).name
    if base in ("", ".", "..") or base.startswith("."):
        raise ValueError(f"unsafe file name from the dataset API: {name!r}")
    return base


def _is_photo(path: PurePosixPath) -> bool:
    # Hidden entries ("__MACOSX/._x.jpg", ".DS_Store") are metadata, not photos.
    if any(part.startswith((".", "__MACOSX")) for part in path.parts):
        return False
    return path.suffix.lower() in IMAGE_SUFFIXES


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
