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

from sorghum_model.settings import RaceEvaluationSettings, RaceGateSettings, RaceRuleSearchSettings

UNRECOGNIZED = "unrecognized"

# The coverage the race gate is judged at (`RaceGateSettings.min_coverage`, #32); answer rules
# are chosen on validation for it.
GATE_COVERAGE = 0.80

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


@dataclass(frozen=True)
class ChosenRule:
    """An answer rule picked on validation, with the validation numbers that picked it."""

    settings: RaceEvaluationSettings
    validation: RaceEvaluation


def choose_answer_rule(
    true_races: Sequence[str],
    accessions: Sequence[str],
    probabilities: np.ndarray,
    races: Sequence[str],
    target_coverage: float,
    search: RaceRuleSearchSettings,
) -> ChosenRule:
    """The rule with the best validation selective accuracy whose validation coverage reaches
    `target_coverage + search.coverage_margin`. Ties go to the smaller mean group, then the
    lower mass. Call it with validation data only; test is scored once, with the result.

    Raises ValueError when no rule in the search grid reaches the coverage.
    """
    required_coverage = target_coverage + search.coverage_margin
    best: ChosenRule | None = None
    for max_group_size in search.max_group_sizes:
        for mass in search.group_masses():
            settings = RaceEvaluationSettings(group_probability_mass=mass, max_group_size=max_group_size)
            evaluation = evaluate_races(true_races, accessions, probabilities, races, settings)
            if evaluation.coverage < required_coverage:
                continue
            if best is None or _is_better(evaluation, best.validation):
                best = ChosenRule(settings, evaluation)
    if best is None:
        raise ValueError(f"no answer rule reaches validation coverage {required_coverage:.3f}")
    return best


def _is_better(candidate: RaceEvaluation, incumbent: RaceEvaluation) -> bool:
    if candidate.selective_accuracy != incumbent.selective_accuracy:
        return candidate.selective_accuracy > incumbent.selective_accuracy
    return candidate.mean_group_size < incumbent.mean_group_size


def top1_accuracy(true_races: Sequence[str], probabilities: np.ndarray, races: Sequence[str]) -> float:
    """Share of photos whose most probable race is the true race (no groups, no abstention)."""
    predicted = [races[index] for index in probabilities.argmax(axis=1)]
    return float(np.mean([p == t for p, t in zip(predicted, true_races, strict=True)]))


def majority_race_probabilities(train_races: Sequence[str], races: Sequence[str], photo_count: int) -> np.ndarray:
    """The majority baseline: every photo gets the most common training race with certainty.

    Scored with `evaluate_races`, it answers every photo with a group of one.
    """
    return _one_hot([Counter(train_races).most_common(1)[0][0]] * photo_count, races)


def planting_race_probabilities(
    train_races: Sequence[str],
    train_plantings: Sequence[str],
    plantings: Sequence[str],
    races: Sequence[str],
) -> np.ndarray:
    """The planting baseline: each photo gets the most common training race of its planting.

    Plantings differ in board, light and year, and their race mixes differ, so a model can
    score well by recognising the planting alone; it must beat this clearly. A planting with
    no training photos gets the overall majority race.
    """
    overall = Counter(train_races).most_common(1)[0][0]
    by_planting: dict[str, Counter[str]] = {}
    for race, planting in zip(train_races, train_plantings, strict=True):
        by_planting.setdefault(planting, Counter())[race] += 1
    predicted = [
        by_planting[planting].most_common(1)[0][0] if planting in by_planting else overall for planting in plantings
    ]
    return _one_hot(predicted, races)


def _one_hot(predicted: Sequence[str], races: Sequence[str]) -> np.ndarray:
    probabilities = np.zeros((len(predicted), len(races)))
    for row, race in enumerate(predicted):
        probabilities[row, list(races).index(race)] = 1.0
    return probabilities


def race_gate_problems(
    int8_test: RaceEvaluation,
    float_test: RaceEvaluation,
    best_baseline_accuracy: float,
    gate: RaceGateSettings,
) -> list[str]:
    """Every way the INT8 model's test result misses the T9 gate; empty when it passes.

    `float_test` is the float model scored with the same rule; `best_baseline_accuracy` the
    better of the majority and planting baselines (they answer every photo, so their
    selective accuracy is their accuracy).
    """
    problems = []
    if int8_test.selective_accuracy < gate.min_selective_accuracy:
        problems.append(
            f"selective accuracy {int8_test.selective_accuracy:.3f} < {gate.min_selective_accuracy:.2f}"
        )
    if int8_test.coverage < gate.min_coverage:
        problems.append(f"coverage {int8_test.coverage:.3f} < {gate.min_coverage:.2f}")
    margin = int8_test.selective_accuracy - best_baseline_accuracy
    # Differences of float ratios fall short of exact values (0.9 - 0.8 < 0.1).
    if margin < gate.min_points_over_baseline - _PROBABILITY_SUM_TOLERANCE:
        problems.append(f"only {margin:.3f} above the best baseline ({best_baseline_accuracy:.3f})")
    delta = abs(float_test.selective_accuracy - int8_test.selective_accuracy)
    if delta > gate.max_int8_accuracy_delta + _PROBABILITY_SUM_TOLERANCE:
        problems.append(f"float/INT8 selective accuracy delta {delta:.3f} > {gate.max_int8_accuracy_delta:.2f}")
    return problems


# Harlan & de Wet's five basic races. Every intermediate is named "<basic>-<basic>"
# (GRIN: "Durra-bicolor"), so its two parents can be read from its name.
BASIC_RACES: tuple[str, ...] = ("Bicolor", "Caudatum", "Durra", "Guinea", "Kafir")


def parent_basic_races(race: str) -> frozenset[str]:
    """The basic races a race is made of: itself for a basic race, both parents for an
    intermediate ("Durra-bicolor" -> {Durra, Bicolor})."""
    parents = frozenset(part.capitalize() for part in race.split("-"))
    if not parents <= set(BASIC_RACES):
        raise ValueError(f"{race!r} is not a basic race or an intermediate of two")
    return parents


@dataclass(frozen=True)
class BasicRaceEvaluation:
    """SECONDARY metric, never the gate: the 15-race answer read at the level of the five
    basic races.

    The returned group (same rule as the gate) is mapped to the basic races of its members;
    a photo is a hit when one of its true race's parents is among them. Lenient by design:
    a Durra-bicolor photo answered "Durra" is a hit. Abstentions stay abstentions.
    """

    photo_count: int
    answered_count: int
    hit_count: int

    @property
    def coverage(self) -> float:
        return self.answered_count / self.photo_count if self.photo_count else 0.0

    @property
    def selective_accuracy(self) -> float:
        return self.hit_count / self.answered_count if self.answered_count else 0.0


def evaluate_basic_races(
    true_races: Sequence[str], probabilities: np.ndarray, races: Sequence[str], settings: RaceEvaluationSettings
) -> BasicRaceEvaluation:
    answered = hits = 0
    for true_race, row in zip(true_races, probabilities, strict=True):
        group = returned_group(row, races, settings)
        if group is None:
            continue
        answered += 1
        group_parents = frozenset().union(*(parent_basic_races(race) for race in group))
        if parent_basic_races(true_race) & group_parents:
            hits += 1
    return BasicRaceEvaluation(len(true_races), answered, hits)


@dataclass(frozen=True)
class PlantingCheck:
    """The model against the planting baseline inside one planting.

    Within a planting the board, light and season are shared, so the planting baseline
    there is simply that planting's commonest training race; whatever the model gains over
    it inside the planting cannot come from recognising the planting.
    """

    planting_id: str
    photo_count: int
    coverage: float
    selective_accuracy: float
    planting_baseline_accuracy: float

    @property
    def gain_over_baseline(self) -> float:
        return self.selective_accuracy - self.planting_baseline_accuracy


def planting_shortcut_check(
    true_races: Sequence[str],
    accessions: Sequence[str],
    plantings: Sequence[str],
    probabilities: np.ndarray,
    races: Sequence[str],
    settings: RaceEvaluationSettings,
    train_races: Sequence[str],
    train_plantings: Sequence[str],
) -> list[PlantingCheck]:
    """One `PlantingCheck` per planting of the scored photos, by planting id."""
    baseline = planting_race_probabilities(train_races, train_plantings, plantings, races)
    checks = []
    for planting in sorted(set(plantings)):
        rows = [index for index, value in enumerate(plantings) if value == planting]
        subset_truth = [true_races[index] for index in rows]
        subset_accessions = [accessions[index] for index in rows]
        model = evaluate_races(subset_truth, subset_accessions, probabilities[rows], races, settings)
        planting_only = evaluate_races(subset_truth, subset_accessions, baseline[rows], races, settings)
        checks.append(
            PlantingCheck(planting, len(rows), model.coverage, model.selective_accuracy, planting_only.accuracy)
        )
    return checks
