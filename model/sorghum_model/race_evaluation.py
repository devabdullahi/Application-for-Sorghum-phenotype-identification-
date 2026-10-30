"""Group-aware race accuracy, coverage, per-race support and the confusion matrix (ADR-0011).

The race model (T4) gives calibrated probabilities over the scored races for each test
photo. `returned_group` turns them into the app's kind of answer: a group of races, or
"unrecognized". `evaluate_races` scores those answers:

- a photo is a **hit** when its true race is in the returned group;
- "unrecognized" is an **abstention**: never a hit, and it lowers coverage;
- **accuracy** is hits over all photos, so abstaining cannot raise it; **selective accuracy**
  is hits over answered photos. Both are reported with coverage, because 89% selective
  accuracy at 30% coverage is not 89%.

The confusion matrix counts (true race, top-1 race) for answered photos and
(true race, "unrecognized") for abstentions. Pure numpy; no TensorFlow.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from sorghum_model.settings import RaceEvaluationSettings

UNRECOGNIZED = "unrecognized"

# Float sums of probabilities fall short of exact values (0.3 + 0.3 + 0.3 < 0.9), which would
# grow a group by a race it does not need.
_PROBABILITY_SUM_TOLERANCE = 1e-9


def returned_group(
    probabilities: np.ndarray, races: Sequence[str], settings: RaceEvaluationSettings
) -> tuple[str, ...] | None:
    """The fewest most-likely races whose probability reaches the group mass, most likely first.

    Returns None ("unrecognized") when that group has more than `max_group_size` races.
    Ties are broken by race order, so the result is deterministic.
    """
    if len(probabilities) != len(races):
        raise ValueError(f"{len(probabilities)} probabilities for {len(races)} races")
    order = sorted(range(len(races)), key=lambda index: (-probabilities[index], index))
    group: list[str] = []
    mass = 0.0
    for index in order:
        group.append(races[index])
        mass += float(probabilities[index])
        if mass >= settings.group_probability_mass - _PROBABILITY_SUM_TOLERANCE:
            break
    if len(group) > settings.max_group_size:
        return None
    return tuple(group)


@dataclass(frozen=True)
class RaceEvaluation:
    """Scores of one split. Counts are photos; `support` also gives accessions per race.

    Attributes:
        photo_count: photos scored (only photos with a scored race; see `cultivar_races`).
        answered_count: photos given a group rather than "unrecognized".
        hit_count: answered photos whose true race is in the group.
        group_size_total: sum of returned group sizes, for the mean group size.
        support: race -> (photos, accessions) in this split.
        hits_by_race: race -> hits.
        confusion: (true race, top-1 race or UNRECOGNIZED) -> photos.
    """

    photo_count: int
    answered_count: int
    hit_count: int
    group_size_total: int
    support: dict[str, tuple[int, int]]
    hits_by_race: dict[str, int]
    confusion: dict[tuple[str, str], int]

    @property
    def coverage(self) -> float:
        return self.answered_count / self.photo_count if self.photo_count else 0.0

    @property
    def accuracy(self) -> float:
        """Hits over all photos: the headline group-aware race accuracy."""
        return self.hit_count / self.photo_count if self.photo_count else 0.0

    @property
    def selective_accuracy(self) -> float:
        """Hits over answered photos."""
        return self.hit_count / self.answered_count if self.answered_count else 0.0

    @property
    def mean_group_size(self) -> float:
        return self.group_size_total / self.answered_count if self.answered_count else 0.0


def evaluate_races(
    true_races: Sequence[str],
    accessions: Sequence[str],
    probabilities: np.ndarray,
    races: Sequence[str],
    settings: RaceEvaluationSettings,
) -> RaceEvaluation:
    """Scores one split; row i of `probabilities` belongs to photo i of `true_races` and `accessions`."""
    if not len(true_races) == len(accessions) == len(probabilities):
        raise ValueError("true_races, accessions and probabilities must have one entry per photo")
    unknown = sorted(set(true_races) - set(races))
    if unknown:
        raise ValueError(f"true races {unknown} are not model classes; excluded labels must not be scored")

    answered = hits = group_size_total = 0
    hits_by_race: Counter[str] = Counter()
    confusion: Counter[tuple[str, str]] = Counter()
    for true_race, row in zip(true_races, probabilities, strict=True):
        group = returned_group(row, races, settings)
        if group is None:
            confusion[(true_race, UNRECOGNIZED)] += 1
            continue
        answered += 1
        group_size_total += len(group)
        confusion[(true_race, group[0])] += 1
        if true_race in group:
            hits += 1
            hits_by_race[true_race] += 1

    photos_by_race = Counter(true_races)
    accessions_by_race = {race: len({a for a, r in zip(accessions, true_races) if r == race}) for race in photos_by_race}
    return RaceEvaluation(
        photo_count=len(true_races),
        answered_count=answered,
        hit_count=hits,
        group_size_total=group_size_total,
        support={race: (photos_by_race[race], accessions_by_race[race]) for race in photos_by_race},
        hits_by_race=dict(hits_by_race),
        confusion=dict(confusion),
    )


def race_evaluation_report(evaluation: RaceEvaluation, races: Sequence[str]) -> list[str]:
    """Human-readable lines: headline numbers, per-race support and recall, confusion matrix."""
    lines = [
        f"photos {evaluation.photo_count}, coverage {evaluation.coverage:.3f}, "
        f"group-aware accuracy {evaluation.accuracy:.3f}, selective accuracy {evaluation.selective_accuracy:.3f}, "
        f"mean group size {evaluation.mean_group_size:.2f}",
        f"{'race':18} {'photos':>7} {'accessions':>10} {'in-group recall':>16}",
    ]
    for race in races:
        photos, accession_count = evaluation.support.get(race, (0, 0))
        recall = evaluation.hits_by_race.get(race, 0) / photos if photos else 0.0
        lines.append(f"{race:18} {photos:>7} {accession_count:>10} {recall:>16.3f}")

    columns = [*races, UNRECOGNIZED]
    lines.append("confusion (rows: true race; columns: top-1 race, then unrecognized)")
    lines.append(f"{'':18} " + " ".join(f"{index:>4}" for index in range(len(columns))))
    for race in races:
        counts = " ".join(f"{evaluation.confusion.get((race, column), 0):>4}" for column in columns)
        lines.append(f"{race:18} {counts}")
    lines.append("columns: " + ", ".join(f"{index} {column}" for index, column in enumerate(columns)))
    return lines
