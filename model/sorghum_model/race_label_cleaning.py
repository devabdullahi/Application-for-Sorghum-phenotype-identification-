"""Which basic-race training labels are confirmed, which are excluded, and why (T32, #62).

basic-race-v1 trained on every accession GRIN names as one basic race. Most of those labels
rest on one GRIN observation, and the crosswalk (T24, `race_crosswalk.py`) found that a second
source agrees with such a label only about four times in five. The confirmed-label rule
(ADR-0013, `docs/architecture/type-evaluation-protocol.md` 5.2) is applied here to the
training and validation accessions of `accession_split`:

- **Confirmed** (`core_shortlist.LabelTier`): the Frontiers 2023 panel names the same basic race
  (`corroborated`), or two or more GRIN plantings recorded the same race (`repeated`).
- **Excluded**, with one reason per accession (`TrainingLabelExclusion`): the label is
  contradicted by a second source, rests on a single GRIN observation, conflicts between GRIN
  plantings, names an intermediate race, or there is no scored race at all.

**Fallback.** A race whose confirmed training accessions fall below
`RaceLabelCleaningSettings.min_confirmed_train_accessions_per_race` cannot be trained on
confirmed labels alone. It is never silently refilled. Instead, when any race is short, the
whole manifest switches to the documented weighting fallback: confirmed labels weigh 1,
single-observation labels weigh `single_observation_weight`, and contradicted, conflicting and
intermediate labels weigh 0. Every race is weighted the same way, so the class balance the
model sees does not depend on how often each race happened to be confirmed. The rejected
alternative (keep single-observation labels only for the short races) would, on the GRIN data
of 2026-10-30, train Caudatum and Durra on their 21 and 27 confirmed accessions next to 395
single-observation photos of Bicolor, Guinea and Kafir, and so teach the model that the two
commonest races are the rarest.

Test accessions are never read into the manifest: the GRIN test split was scored once for
basic-race-v1 and is now seen, and nothing here may select on it. Pure Python; no TensorFlow.
"""

import csv
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path

from sorghum_model.core_shortlist import LabelTier, frontiers_by_accession
from sorghum_model.cultivar_races import RaceExclusion
from sorghum_model.grin_descriptors import RACE, DescriptorObservation
from sorghum_model.race_crosswalk import BASIC_RACES, CrosswalkRow, RaceComparison, wilson_interval
from sorghum_model.settings import RaceLabelCleaningSettings
from sorghum_model.splits import Split

# Splits the manifest covers. Test is left out on purpose (module docstring).
CLEANED_SPLITS: tuple[Split, ...] = (Split.TRAIN, Split.VALIDATION)

# Frontiers comparisons that leave a GRIN label standing (protocol 5.2: no other source may name
# a different race or an intermediate of it).
_SECOND_SOURCE_ALLOWS = frozenset({RaceComparison.SAME.value, RaceComparison.NOT_COMPARED.value})

# Crosswalk agreement where both sources name a basic race (T24): quoted in the summary because
# it is where `single_observation_weight` comes from.
_CROSSWALK_BASIC_AGREEMENT = (23, 29)


class TrainingLabelExclusion(Enum):
    """Why an accession's label is not a confirmed basic-race training label."""

    NO_SCORED_RACE = "no-scored-race"  # GRIN has no usable race (`grin_race_exclusion` says which)
    CONFLICTING_OBSERVATIONS = "conflicting-observations"  # GRIN plantings disagree
    INTERMEDIATE_RACE = "intermediate-race"  # one of the ten intermediates, not a basic race
    SECOND_SOURCE_DISAGREES = "second-source-disagrees"  # Frontiers names another race or an intermediate
    SINGLE_OBSERVATION = "single-observation"  # one GRIN observation, no second source


@dataclass(frozen=True)
class TrainingLabelRow:
    """One accession of `manifests/basic-race-training-labels.csv`.

    Attributes:
        accession: GRIN accession ("PI 452506").
        accession_split: "train" or "validation".
        photos: how many of its photos are in the split manifest.
        grin_race: its scored GRIN race, or "" when it has none.
        grin_race_exclusion: `cultivar_races.RaceExclusion` value when it has none.
        grin_race_values: every GRIN race value recorded for it, "; "-joined.
        grin_race_studies: how many GRIN plantings recorded its race.
        frontiers_race: the Frontiers 2023 race, or "".
        frontiers_comparison: `race_crosswalk.RaceComparison` value, or "" with no Frontiers row.
        label_tier: "corroborated", "repeated" or "single" for a basic-race label, else "".
        exclusion: `TrainingLabelExclusion` value, or "" for a confirmed label.
        training_weight: the loss weight of each of its photos; 0 means not trained on. Always
            0 for validation, which is scored (all labels, and confirmed labels apart), not trained.
        kept_by_fallback: "yes" for a train accession the strict rule excludes but the fallback keeps.
    """

    accession: str
    accession_split: str
    photos: int
    grin_race: str
    grin_race_exclusion: str
    grin_race_values: str
    grin_race_studies: int
    frontiers_race: str
    frontiers_comparison: str
    label_tier: str
    exclusion: str
    training_weight: float
    kept_by_fallback: str

    @property
    def is_confirmed(self) -> bool:
        return not self.exclusion


TRAINING_LABEL_COLUMNS = [field.name for field in fields(TrainingLabelRow)]


@dataclass(frozen=True)
class CleanedLabels:
    """The cleaned manifest and the decision behind its weights.

    Attributes:
        rows: one per train or validation accession, sorted by split then accession.
        short_races: basic races with fewer confirmed training accessions than the minimum,
            alphabetical. Empty means training uses confirmed labels only.
        test_accessions_skipped: test accessions present in the split but not read.
    """

    rows: tuple[TrainingLabelRow, ...]
    short_races: tuple[str, ...]
    test_accessions_skipped: int

    @property
    def uses_fallback(self) -> bool:
        return bool(self.short_races)


def race_study_counts(observations: Iterable[DescriptorObservation]) -> dict[str, int]:
    """Accession -> how many GRIN plantings (studies) recorded its race."""
    studies: dict[str, set[str]] = defaultdict(set)
    for observation in observations:
        if observation.descriptor == RACE.code:
            studies[observation.accession].add(observation.study)
    return {accession: len(names) for accession, names in studies.items()}


def race_values(observations: Iterable[DescriptorObservation]) -> dict[str, tuple[str, ...]]:
    """Accession -> every distinct GRIN race value recorded for it, sorted."""
    values: dict[str, set[str]] = defaultdict(set)
    for observation in observations:
        if observation.descriptor == RACE.code:
            values[observation.accession].add(" ".join(observation.grin_value.split()))
    return {accession: tuple(sorted(found)) for accession, found in values.items()}


def strict_label(
    grin_race: str, grin_race_exclusion: str, race_studies: int, frontiers: CrosswalkRow | None
) -> tuple[LabelTier | None, TrainingLabelExclusion | None]:
    """(tier, exclusion) of one accession under the confirmed-label rule (module docstring).

    The tier is set for every basic-race label, so a reader can see how strong an excluded
    label was. The exclusion is None only for a confirmed basic-race label.
    """
    if not grin_race:
        if grin_race_exclusion == RaceExclusion.CONFLICTING_OBSERVATIONS.value:
            return None, TrainingLabelExclusion.CONFLICTING_OBSERVATIONS
        return None, TrainingLabelExclusion.NO_SCORED_RACE
    if grin_race not in BASIC_RACES:
        return None, TrainingLabelExclusion.INTERMEDIATE_RACE

    if frontiers is not None and frontiers.race_comparison == RaceComparison.SAME.value:
        tier = LabelTier.CORROBORATED
    elif race_studies >= 2:
        tier = LabelTier.REPEATED
    else:
        tier = LabelTier.SINGLE

    if frontiers is not None and frontiers.race_comparison not in _SECOND_SOURCE_ALLOWS:
        return tier, TrainingLabelExclusion.SECOND_SOURCE_DISAGREES
    if tier is LabelTier.SINGLE:
        return tier, TrainingLabelExclusion.SINGLE_OBSERVATION
    return tier, None


def short_races(
    confirmed_train_accessions: Mapping[str, int], settings: RaceLabelCleaningSettings
) -> tuple[str, ...]:
    """Basic races with fewer confirmed training accessions than the minimum, alphabetical."""
    minimum = settings.min_confirmed_train_accessions_per_race
    return tuple(sorted(race for race in BASIC_RACES if confirmed_train_accessions.get(race, 0) < minimum))


def training_weight(exclusion: TrainingLabelExclusion | None, uses_fallback: bool, settings: RaceLabelCleaningSettings) -> float:
    """Loss weight of one accession's photos: 1 confirmed, the fallback weight for a single
    observation when the fallback is on, 0 otherwise."""
    if exclusion is None:
        return 1.0
    if exclusion is TrainingLabelExclusion.SINGLE_OBSERVATION and uses_fallback:
        return settings.single_observation_weight
    return 0.0


def clean_basic_race_labels(
    split_rows: Sequence[Mapping[str, str]],
    observations: Sequence[DescriptorObservation],
    crosswalk: Iterable[CrosswalkRow],
    settings: RaceLabelCleaningSettings,
) -> CleanedLabels:
    """The cleaned training-label manifest of every train and validation accession.

    `split_rows` are `cultivar_manifest.read_cultivar_split` rows (one per photo). Refuses an
    accession in two splits, because its photos could then train and score at once.
    """
    split_of: dict[str, str] = {}
    first_row: dict[str, Mapping[str, str]] = {}
    photos: Counter[str] = Counter()
    for row in split_rows:
        accession = row["cultivar_label"]
        if split_of.setdefault(accession, row["accession_split"]) != row["accession_split"]:
            raise ValueError(f"{accession} is in two accession splits")
        first_row.setdefault(accession, row)
        photos[accession] += 1

    cleaned_split_names = {split.value for split in CLEANED_SPLITS}
    accessions = sorted(a for a, split in split_of.items() if split in cleaned_split_names)
    test_skipped = sum(1 for split in split_of.values() if split == Split.TEST.value)
    studies = race_study_counts(observations)
    values = race_values(observations)
    frontiers = frontiers_by_accession(crosswalk)

    labels = {}
    for accession in accessions:
        row = first_row[accession]
        labels[accession] = strict_label(row["race"], row["race_exclusion"], studies.get(accession, 0), frontiers.get(accession))

    confirmed_train = Counter(
        first_row[a]["race"] for a, (_, exclusion) in labels.items() if exclusion is None and split_of[a] == Split.TRAIN.value
    )
    short = short_races(confirmed_train, settings)

    rows = []
    for accession in accessions:
        row = first_row[accession]
        tier, exclusion = labels[accession]
        # Validation photos are scored, never trained on, so only train rows carry a weight.
        is_train = split_of[accession] == Split.TRAIN.value
        weight = training_weight(exclusion, bool(short), settings) if is_train else 0.0
        crosswalk_row = frontiers.get(accession)
        rows.append(
            TrainingLabelRow(
                accession=accession,
                accession_split=split_of[accession],
                photos=photos[accession],
                grin_race=row["race"],
                grin_race_exclusion=row["race_exclusion"],
                grin_race_values="; ".join(values.get(accession, ())),
                grin_race_studies=studies.get(accession, 0),
                frontiers_race=crosswalk_row.frontiers_race if crosswalk_row else "",
                frontiers_comparison=crosswalk_row.race_comparison if crosswalk_row else "",
                label_tier=tier.value if tier else "",
                exclusion=exclusion.value if exclusion else "",
                training_weight=weight,
                kept_by_fallback="yes" if is_train and exclusion is not None and weight > 0 else "no",
            )
        )
    rows.sort(key=lambda r: (CLEANED_SPLITS.index(Split(r.accession_split)), r.accession))
    return CleanedLabels(tuple(rows), short, test_skipped)


def write_training_labels(rows: Iterable[TrainingLabelRow], path: Path) -> None:
    """Writes the manifest via a temporary file and a rename, so a crash leaves the old one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=TRAINING_LABEL_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: getattr(row, name) for name in TRAINING_LABEL_COLUMNS})
    temporary.replace(path)


def read_training_labels(path: Path) -> list[TrainingLabelRow]:
    """Reads a file written by `write_training_labels`."""
    with path.open(newline="", encoding="utf-8") as file:
        return [
            TrainingLabelRow(
                **{
                    **row,
                    "photos": int(row["photos"]),
                    "grin_race_studies": int(row["grin_race_studies"]),
                    "training_weight": float(row["training_weight"]),
                }
            )
            for row in csv.DictReader(file)
        ]


def cleaning_report(cleaned: CleanedLabels, settings: RaceLabelCleaningSettings) -> list[str]:
    """Counts by basic race and exclusion reason, per split, and the fallback decision."""
    rows = cleaned.rows
    lines = [
        "Basic-race training labels (T32, #62): confirmed-label rule of ADR-0013 / type-eval-v1 5.2",
        f"  splits read: {', '.join(s.value for s in CLEANED_SPLITS)}; "
        f"test accessions not read: {cleaned.test_accessions_skipped}",
        f"  minimum confirmed training accessions per race: {settings.min_confirmed_train_accessions_per_race}",
        "",
    ]
    reasons = [TrainingLabelExclusion.SECOND_SOURCE_DISAGREES, TrainingLabelExclusion.SINGLE_OBSERVATION]
    for split in CLEANED_SPLITS:
        in_split = [r for r in rows if r.accession_split == split.value]
        lines.append(f"{split.value}: accessions (photos) per GRIN basic race")
        header = (
            f"  {'race':<10}{'labelled':>14}{'corroborated':>15}{'repeated':>12}{'confirmed':>14}"
            + "".join(f"{reason.value:>26}" for reason in reasons)
            + f"{'conflicting, names it':>24}"
        )
        lines.append(header)
        for race in [*sorted(BASIC_RACES), "all"]:
            races = set(BASIC_RACES) if race == "all" else {race}
            of_race = [r for r in in_split if r.grin_race in races]
            conflicting = [
                r for r in in_split
                if r.exclusion == TrainingLabelExclusion.CONFLICTING_OBSERVATIONS.value
                and races & set(r.grin_race_values.split("; "))
            ]
            cells = [
                _count(of_race),
                _count([r for r in of_race if r.label_tier == LabelTier.CORROBORATED.value and r.is_confirmed]),
                _count([r for r in of_race if r.label_tier == LabelTier.REPEATED.value and r.is_confirmed]),
                _count([r for r in of_race if r.is_confirmed]),
            ]
            cells += [_count([r for r in of_race if r.exclusion == reason.value]) for reason in reasons]
            lines.append(
                f"  {race:<10}{cells[0]:>14}{cells[1]:>15}{cells[2]:>12}{cells[3]:>14}"
                + "".join(f"{cell:>26}" for cell in cells[4:])
                + f"{_count(conflicting):>24}"
            )
        lines.append("  not a basic-race label, accessions (photos):")
        for reason in (
            TrainingLabelExclusion.INTERMEDIATE_RACE,
            TrainingLabelExclusion.CONFLICTING_OBSERVATIONS,
            TrainingLabelExclusion.NO_SCORED_RACE,
        ):
            lines.append(f"    {reason.value:<26}{_count([r for r in in_split if r.exclusion == reason.value]):>14}")
        lines.append("")

    agreed, compared = _CROSSWALK_BASIC_AGREEMENT
    low, high = wilson_interval(agreed, compared)
    if cleaned.uses_fallback:
        lines += [
            f"Fallback ON: too few confirmed training accessions for {', '.join(cleaned.short_races)}.",
            "  Strict confirmed-only training would drop these races, so they are not refilled; instead",
            "  every race is weighted the same way: confirmed 1.0, single-observation "
            f"{settings.single_observation_weight:.2f}, contradicted / conflicting / intermediate 0.",
            f"  The single-observation weight is the crosswalk's basic-race agreement, {agreed}/{compared} = "
            f"{agreed / compared:.2f} [{low:.2f}, {high:.2f}] (T24): the share of one-curator labels a second source confirms.",
        ]
    else:
        lines.append("Fallback OFF: every race has enough confirmed training accessions; training uses confirmed labels only.")
    trained = [r for r in rows if r.training_weight > 0]
    weighted = sum(r.training_weight * r.photos for r in trained)
    lines.append(
        f"  train: {_count(trained)} accessions (photos) with weight > 0, "
        f"{_count([r for r in trained if r.kept_by_fallback == 'yes'])} of them kept by the fallback; "
        f"weighted photos {weighted:.1f}"
    )
    confirmed_validation = [r for r in rows if r.accession_split == Split.VALIDATION.value and r.is_confirmed]
    by_race = Counter(r.grin_race for r in confirmed_validation)
    lines.append(
        f"  validation (scored, not trained): {_count(confirmed_validation)} confirmed accessions (photos): "
        + ", ".join(f"{race} {by_race[race]}" for race in sorted(BASIC_RACES))
    )
    return lines


def _count(rows: Sequence[TrainingLabelRow]) -> str:
    return f"{len(rows)} ({sum(r.photos for r in rows)})"
