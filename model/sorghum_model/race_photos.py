"""The photos the race model trains and is scored on, joined from the cultivar manifest and split.

Only photos with a scored race (`cultivar_races`) are kept, and each takes its
`accession_split`, so no accession is in more than one of train, validation and test
(ADR-0011). Pure Python; no TensorFlow.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sorghum_model.cultivar_manifest import find_accession_split_leaks, read_cultivar_manifest, read_cultivar_split
from sorghum_model.race_evaluation import BASIC_RACES
from sorghum_model.splits import Split


@dataclass(frozen=True)
class RacePhoto:
    """One photo with its race label.

    Attributes:
        image_path: path relative to the cultivar data root, "/" separators.
        sha256: checksum of the image file; names the input cache.
        accession: genebank accession ("PI 452506"); every photo of it is in one split.
        planting_id: the planting (study, year, site) the photo was taken in.
        split: the photo's accession split.
        race: one of the fifteen scored GRIN race names.
    """

    image_path: str
    sha256: str
    accession: str
    planting_id: str
    split: Split
    race: str


def read_race_photos(manifest_path: Path, split_path: Path) -> list[RacePhoto]:
    """Returns every photo with a scored race, in split-manifest order.

    Refuses a split whose accessions or files cross splits, and split rows missing from the
    manifest, because either would put test photos into training.
    """
    split_rows = read_cultivar_split(split_path)
    leaks = find_accession_split_leaks(split_rows)
    if leaks:
        raise ValueError(f"{split_path} leaks across accession splits: {leaks[:5]}")
    image_paths = {
        (record.source, record.source_id): record.image_path for record in read_cultivar_manifest(manifest_path)
    }
    photos = []
    for row in split_rows:
        if not row["race"]:
            continue
        key = (row["source"], row["source_id"])
        if key not in image_paths:
            raise ValueError(f"{key} is in {split_path} but not in {manifest_path}")
        photos.append(
            RacePhoto(
                image_path=image_paths[key],
                sha256=row["sha256"],
                accession=row["cultivar_label"],
                planting_id=row["planting_id"],
                split=Split(row["accession_split"]),
                race=row["race"],
            )
        )
    return photos


def race_class_names(photos: Sequence[RacePhoto]) -> tuple[str, ...]:
    """The race head's output order: every race with a training photo, alphabetical.

    Alphabetical so the order does not depend on the photos' order. A race without training
    photos gets no output, and `race_evaluation.evaluate_races` refuses to score it.
    """
    return tuple(sorted({photo.race for photo in photos if photo.split is Split.TRAIN}))


def photos_in(photos: Sequence[RacePhoto], split: Split) -> list[RacePhoto]:
    return [photo for photo in photos if photo.split is split]


def balanced_race_weights(train_photos: Sequence[RacePhoto], races: Sequence[str]) -> dict[int, float]:
    """Keras class weights n / (races * count), so a race with 30 photos is not ignored next to
    Caudatum's 1,600."""
    counts = Counter(photo.race for photo in train_photos)
    missing = [race for race in races if not counts[race]]
    if missing:
        raise ValueError(f"races without training photos: {missing}")
    total = sum(counts[race] for race in races)
    return {index: total / (len(races) * counts[race]) for index, race in enumerate(races)}


def undersized_races(
    photos: Sequence[RacePhoto], races: Sequence[str], min_train_photos: int, min_evaluation_photos: int
) -> list[str]:
    """Describes every race with fewer photos than the minimum in a split; empty when all pass."""
    counts = Counter((photo.race, photo.split) for photo in photos)
    problems = []
    for race in races:
        for split in Split:
            minimum = min_train_photos if split is Split.TRAIN else min_evaluation_photos
            if counts[(race, split)] < minimum:
                problems.append(f"{race}: {counts[(race, split)]} {split.value} photos (minimum {minimum})")
    return problems


def split_basic_and_intermediate(photos: Sequence[RacePhoto]) -> tuple[list[RacePhoto], list[RacePhoto]]:
    """(photos of the five basic races, photos of the ten intermediates), for the basic-race
    output (T14, #37).

    Label rule: the basic-race output is trained and scored only on accessions GRIN names as
    one of the five basic races. Intermediates are excluded from its training and its headline
    score rather than given a split target (half one parent, half the other): an intermediate
    is not "both parents at once", and a soft target would teach the head that two basic races
    look alike. How the output answers intermediate photos is reported separately (a hit when
    a parent is in the returned group), never folded into the headline.
    """
    basic = [photo for photo in photos if photo.race in BASIC_RACES]
    intermediate = [photo for photo in photos if photo.race not in BASIC_RACES]
    return basic, intermediate
