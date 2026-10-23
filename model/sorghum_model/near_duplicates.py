"""Finds near-duplicate photos across sources with a difference hash (dHash) at split time.

The same photo often reaches us twice: resized by GBIF's image cache and by iNaturalist, or
re-uploaded to Commons. Exact duplicates are caught by sha256 (`merge_manifests`), but a
resized or recompressed copy has a different checksum. If its two copies land in train and
test, the test numbers are inflated, so near-duplicates are found here and handled before
groups are assigned to splits:

- copies with the same class: their groups are merged into one, so every photo of both
  photographers (or plants) stays in one split;
- copies with different classes: both are dropped, as `merge_manifests` does for exact
  duplicates, since one of the labels is wrong.

dHash: shrink to 9x8 grey pixels and record, per row, whether each pixel is brighter than its
right neighbour. 64 bits survive resizing and JPEG recompression; a small Hamming distance
means the same picture. Hashes are cached by sha256, so a re-split reads only new photos.
"""

import csv
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from sorghum_model.manifest import ImageRecord

HASH_BITS = 64
_HASH_WIDTH_PX = 9  # 9 columns give 8 left-right comparisons per row
_HASH_HEIGHT_PX = 8

# Below the data root, so the cache travels with the photos and never enters git.
HASH_CACHE_FILE = Path(".cache") / "dhash.csv"


def difference_hash(image_path: Path) -> int:
    """The 64-bit dHash of an image file."""
    with Image.open(image_path) as image:
        grey = image.convert("L").resize(
            (_HASH_WIDTH_PX, _HASH_HEIGHT_PX), Image.Resampling.BILINEAR
        )
        pixels = grey.tobytes()
    bits = 0
    for row in range(_HASH_HEIGHT_PX):
        for column in range(_HASH_WIDTH_PX - 1):
            left = pixels[row * _HASH_WIDTH_PX + column]
            right = pixels[row * _HASH_WIDTH_PX + column + 1]
            bits = (bits << 1) | int(left > right)
    return bits


@dataclass(frozen=True)
class NearDuplicateResult:
    """Records ready to split, and what the near-duplicate pass changed.

    Attributes:
        records: kept records; a merged group's records all carry its new group id.
        dropped: near-duplicates whose copies disagree on the class, plus unreadable images.
        merged_groups: how many groups were folded into another group.
    """

    records: list[ImageRecord]
    dropped: list[ImageRecord]
    merged_groups: int


def resolve_near_duplicates(
    records: list[ImageRecord],
    hashes: dict[str, int | None],
    max_distance: int,
) -> NearDuplicateResult:
    """Merges the groups of same-class near-duplicates and drops conflicting ones.

    `hashes` maps sha256 to dHash; None means the image could not be read, and such a record
    is dropped (training would fail on it anyway). Two photos are near-duplicates when their
    hashes differ in at most `max_distance` bits.
    """
    readable = [r for r in records if hashes.get(r.sha256) is not None]
    dropped = [r for r in records if hashes.get(r.sha256) is None]

    conflicting: set[int] = set()
    group_parent: dict[str, str] = {r.group_id: r.group_id for r in readable}
    for first, second in _near_pairs([hashes[r.sha256] for r in readable], max_distance):
        a, b = readable[first], readable[second]
        if a.class_name != b.class_name:
            conflicting.update((first, second))
        else:
            _union(group_parent, a.group_id, b.group_id)

    kept = []
    for index, record in enumerate(readable):
        if index in conflicting:
            dropped.append(record)
            continue
        group = _find(group_parent, record.group_id)
        kept.append(record if group == record.group_id else replace(record, group_id=group))
    merged_groups = sum(1 for group in group_parent if _find(group_parent, group) != group)
    return NearDuplicateResult(kept, dropped, merged_groups)


def load_hashes(
    records: list[ImageRecord],
    data_root: Path,
    hash_file: Callable[[Path], int] = difference_hash,
) -> dict[str, int | None]:
    """dHash of every record's image, keyed by sha256, reading only photos not in the cache."""
    cache_path = data_root / HASH_CACHE_FILE
    cache = _read_cache(cache_path)
    added = False
    for record in records:
        if record.sha256 in cache:
            continue
        try:
            cache[record.sha256] = hash_file(data_root / record.image_path)
        except (OSError, UnidentifiedImageError, ValueError):
            # Missing or corrupt file; not cached, so a re-downloaded copy is hashed later.
            continue
        added = True
    if added:
        _write_cache(cache, cache_path)
    return {record.sha256: cache.get(record.sha256) for record in records}


def _near_pairs(hashes: list[int], max_distance: int) -> set[tuple[int, int]]:
    """Index pairs whose hashes differ in at most `max_distance` bits.

    Comparing every pair is quadratic (10^10 comparisons for 100,000 photos). Instead the 64
    bits are cut into max_distance + 1 bands: two hashes within the distance can differ in at
    most max_distance bands, so they agree exactly on at least one band (pigeonhole). Only
    hashes sharing a band value are compared.
    """
    if not 0 <= max_distance < HASH_BITS:
        raise ValueError(f"max_distance must be in [0, {HASH_BITS})")
    band_count = max_distance + 1
    band_edges = [round(i * HASH_BITS / band_count) for i in range(band_count + 1)]
    pairs: set[tuple[int, int]] = set()
    for band in range(band_count):
        low, high = band_edges[band], band_edges[band + 1]
        mask = (1 << (high - low)) - 1
        buckets: dict[int, list[int]] = {}
        for index, value in enumerate(hashes):
            buckets.setdefault((value >> low) & mask, []).append(index)
        for members in buckets.values():
            for position, first in enumerate(members):
                for second in members[position + 1 :]:
                    if (hashes[first] ^ hashes[second]).bit_count() <= max_distance:
                        pairs.add((first, second))
    return pairs


def _find(parent: dict[str, str], group: str) -> str:
    while parent[group] != group:
        parent[group] = parent[parent[group]]  # path halving keeps chains short
        group = parent[group]
    return group


def _union(parent: dict[str, str], a: str, b: str) -> None:
    root_a, root_b = _find(parent, a), _find(parent, b)
    if root_a != root_b:
        # The smaller id wins, so the merged group's name does not depend on input order.
        parent[max(root_a, root_b)] = min(root_a, root_b)


def _read_cache(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as file:
        return {row["sha256"]: int(row["dhash"], 16) for row in csv.DictReader(file)}


def _write_cache(cache: dict[str, int], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["sha256", "dhash"])
        for sha256, value in sorted(cache.items()):
            writer.writerow([sha256, f"{value:016x}"])
    os.replace(temporary, path)
