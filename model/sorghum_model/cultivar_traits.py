"""Per-accession trait labels for the learned trait heads (T12, #35), and why some have none.

GRIN records descriptors per accession and planting ("study"); `grin_descriptors` maps each
value to an IBPGR state code. A photo is labelled with its accession's state, so the label
must hold for the accession as a whole. An accession gets a state for a trait only when every
GRIN observation of that trait maps to the same IBPGR state. Otherwise it has no label for
that trait (its photos still serve the other traits) and records why:

- `no-observation`: GRIN has no value for the trait.
- `unmapped-value`: a value missing from the descriptor's GRIN code table (GRIN added a
  value). Kept apart so a new value is seen and mapped, not silently dropped.
- `no-single-state`: every value is a known GRIN value without one IBPGR equivalent: Tan
  glumes, Mixed or Segregating lots, and loose or semi-loose panicles whose IBPGR state also
  needs the branch habit GRIN does not record (`grin_descriptors.combined_panicle_state`).
- `conflicting-observations`: plantings disagree: two different states, or a state in one
  planting and a value without a state in another (e.g. Purple and Tan glumes). Choosing one
  would be a guess (CLAUDE.md: never guess a label).

Panicle compactness and shape is one IBPGR trait read from two GRIN descriptors. Per study the
combined compactness + shape row is used; a study with only one of them contributes that row,
which maps to a state only for Lax and Broomcorn shapes.

Grain lustre has no GRIN descriptor, and midrib colour and plant pigmentation are leaf traits
the GRIN panicle-and-grain photos do not show, so none of them is a candidate here.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sorghum_model.cultivar_manifest import find_accession_split_leaks, read_cultivar_manifest, read_cultivar_split
from sorghum_model.grin_descriptors import (
    COMBINED_PANICLE_DESCRIPTOR,
    GLUME_COLOUR,
    GRAIN_COLOUR,
    PANICLE_COMPACTNESS,
    PANICLE_SHAPE,
    SEED_WEIGHT,
    DescriptorObservation,
    read_observations,
)
from sorghum_model.splits import Split


@dataclass(frozen=True)
class CandidateTrait:
    """A catalogue trait that GRIN's photos show and GRIN's descriptors label.

    Attributes:
        trait_id: the catalogue id (`TraitCatalogue.kt`).
        descriptors: the GRIN descriptor codes whose observations label it.
        catalogue_states: the catalogue's state codes, in catalogue order. Copied from
            `TraitCatalogue.kt` (Python cannot read the Kotlin file); a change there is copied here.
    """

    trait_id: str
    descriptors: tuple[str, ...]
    catalogue_states: tuple[str, ...]


GLUME_COLOUR_TRAIT = CandidateTrait("glumeColour", (GLUME_COLOUR.code,), ("1", "2", "3", "4", "5", "6", "7", "8"))
GRAIN_COLOUR_TRAIT = CandidateTrait("grainColour", (GRAIN_COLOUR.code,), ("1", "2", "3", "4", "5", "6"))
PANICLE_TRAIT = CandidateTrait(
    "panicleCompactnessAndShape",
    (COMBINED_PANICLE_DESCRIPTOR, PANICLE_COMPACTNESS.code, PANICLE_SHAPE.code),
    tuple(str(code) for code in range(1, 14)),
)
# A measured trait in the catalogue (read from seed size on a calibrated grain photo); it is
# labelled here so the frozen-feature probe can say how much of it the GRIN photos show.
HUNDRED_SEED_WEIGHT_TRAIT = CandidateTrait("hundredSeedWeight", (SEED_WEIGHT.code,), ("3", "5", "7"))

CANDIDATE_TRAITS: tuple[CandidateTrait, ...] = (
    GLUME_COLOUR_TRAIT, GRAIN_COLOUR_TRAIT, PANICLE_TRAIT, HUNDRED_SEED_WEIGHT_TRAIT,
)


class TraitExclusion(Enum):
    """Why an accession has no state for a trait. The value is written to reports."""

    NO_OBSERVATION = "no-observation"
    UNMAPPED_VALUE = "unmapped-value"
    NO_SINGLE_STATE = "no-single-state"
    CONFLICTING_OBSERVATIONS = "conflicting-observations"


@dataclass(frozen=True)
class AccessionTrait:
    """One accession's label for one trait: exactly one of `state` and `exclusion` is set.

    Attributes:
        state: the IBPGR state code, or "" when excluded.
        exclusion: why there is no state, or None when `state` is set.
        observed_values: every distinct GRIN value used, sorted, so an exclusion can be
            checked without opening the descriptor manifest.
    """

    state: str
    exclusion: TraitExclusion | None
    observed_values: tuple[str, ...]

    def __post_init__(self) -> None:
        if bool(self.state) == (self.exclusion is not None):
            raise ValueError("an accession has either a state or an exclusion, not both or neither")


def trait_labels(
    trait: CandidateTrait, accessions: Iterable[str], observations: Iterable[DescriptorObservation]
) -> dict[str, AccessionTrait]:
    """Returns `trait`'s label for every accession in `accessions` (see the module docstring)."""
    by_accession_and_study: dict[str, dict[str, list[DescriptorObservation]]] = defaultdict(lambda: defaultdict(list))
    for observation in observations:
        if observation.descriptor in trait.descriptors:
            by_accession_and_study[observation.accession][observation.study].append(observation)

    labels = {}
    for accession in accessions:
        used = [
            observation
            for study_rows in by_accession_and_study.get(accession, {}).values()
            for observation in _observations_used(trait, study_rows)
        ]
        labels[accession] = _accession_label(used)
    return labels


def _observations_used(trait: CandidateTrait, study_rows: list[DescriptorObservation]) -> list[DescriptorObservation]:
    """The rows of one study that label the trait. For the panicle: the combined row when the
    study has one, because the separate compactness and shape rows carry no state alone."""
    if trait is not PANICLE_TRAIT:
        return study_rows
    combined = [row for row in study_rows if row.descriptor == COMBINED_PANICLE_DESCRIPTOR]
    return combined or study_rows


def _accession_label(observations: list[DescriptorObservation]) -> AccessionTrait:
    observed = tuple(sorted({" ".join(o.grin_value.split()) for o in observations}))
    if not observations:
        return AccessionTrait("", TraitExclusion.NO_OBSERVATION, observed)
    if any(not o.grin_code for o in observations):
        return AccessionTrait("", TraitExclusion.UNMAPPED_VALUE, observed)
    states = {o.ibpgr_state for o in observations}
    if states == {""}:
        return AccessionTrait("", TraitExclusion.NO_SINGLE_STATE, observed)
    if len(states) > 1:
        return AccessionTrait("", TraitExclusion.CONFLICTING_OBSERVATIONS, observed)
    return AccessionTrait(states.pop(), None, observed)


@dataclass(frozen=True)
class TraitPhoto:
    """One cultivar photo with its accession's trait states.

    Attributes:
        image_path: path relative to the cultivar data root, "/" separators.
        sha256: checksum of the image file; names the input cache.
        accession: genebank accession; every photo of it is in one split.
        planting_id: the planting (study, year, site) the photo was taken in.
        split: the photo's accession split.
        race: the scored race, or "" when the accession has none (`cultivar_races`).
        states: trait id -> IBPGR state, only for the traits the accession has a label for.
    """

    image_path: str
    sha256: str
    accession: str
    planting_id: str
    split: Split
    race: str
    states: dict[str, str]


def read_trait_photos(
    manifest_path: Path,
    split_path: Path,
    labels_by_trait: dict[str, dict[str, AccessionTrait]],
) -> list[TraitPhoto]:
    """Returns every photo of the split, in split-manifest order, with its accession's states.

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
        key = (row["source"], row["source_id"])
        if key not in image_paths:
            raise ValueError(f"{key} is in {split_path} but not in {manifest_path}")
        accession = row["cultivar_label"]
        states = {
            trait_id: labels[accession].state
            for trait_id, labels in labels_by_trait.items()
            if accession in labels and labels[accession].state
        }
        photos.append(
            TraitPhoto(
                image_path=image_paths[key],
                sha256=row["sha256"],
                accession=accession,
                planting_id=row["planting_id"],
                split=Split(row["accession_split"]),
                race=row["race"],
                states=states,
            )
        )
    return photos


def head_states(photos: Sequence[TraitPhoto], trait: CandidateTrait, min_train_accessions: int) -> tuple[str, ...]:
    """A trait head's output order: catalogue states with at least `min_train_accessions`
    training accessions, in catalogue order.

    Rarer states get no output: a head row fitted to a handful of accessions is noise, and
    `shared/` gives every catalogue state without an output the noise floor (CLAUDE.md: no
    hard zeros). Photos of a dropped state are neither trained on nor scored for this trait.
    """
    accessions_by_state: dict[str, set[str]] = defaultdict(set)
    for photo in photos:
        state = photo.states.get(trait.trait_id)
        if state and photo.split is Split.TRAIN:
            accessions_by_state[state].add(photo.accession)
    return tuple(s for s in trait.catalogue_states if len(accessions_by_state[s]) >= min_train_accessions)


def trait_label_report(
    photos: Sequence[TraitPhoto],
    labels_by_trait: dict[str, dict[str, AccessionTrait]],
    min_train_accessions: int,
) -> list[str]:
    """Lines per trait: exclusions, label coverage per split and state support per split."""
    photographed = {photo.accession for photo in photos}
    lines = [f"{len(photos)} photos of {len(photographed)} accessions (accession_split)"]
    for trait in CANDIDATE_TRAITS:
        labels = labels_by_trait[trait.trait_id]
        lines += ["", f"{trait.trait_id} (GRIN {', '.join(trait.descriptors)})"]
        exclusions = Counter(labels[a].exclusion for a in photographed if labels[a].exclusion)
        values = defaultdict(Counter)
        for accession in photographed:
            label = labels[accession]
            if label.exclusion and label.exclusion is not TraitExclusion.NO_OBSERVATION:
                values[label.exclusion][" + ".join(label.observed_values)] += 1
        for exclusion in TraitExclusion:
            common = ", ".join(f"{value} {count}" for value, count in values[exclusion].most_common(6))
            lines.append(f"  excluded, {exclusion.value}: {exclusions[exclusion]} accessions" + (f" [{common}]" if common else ""))

        kept = head_states(photos, trait, min_train_accessions)
        lines.append(f"  head states (>= {min_train_accessions} train accessions): {', '.join(kept) or 'none'}")
        lines.append(f"  {'state':>6} {'train acc/img':>15} {'validation acc/img':>19} {'test acc/img':>14}")
        labelled_states = sorted(
            {p.states[trait.trait_id] for p in photos if trait.trait_id in p.states}, key=trait.catalogue_states.index
        )
        for state in labelled_states:
            cells = []
            for split in Split:
                in_split = [p for p in photos if p.split is split and p.states.get(trait.trait_id) == state]
                cells.append(f"{len({p.accession for p in in_split})}/{len(in_split)}")
            marker = "" if state in kept else "  (no output)"
            lines.append(f"  {state:>6} {cells[0]:>15} {cells[1]:>19} {cells[2]:>14}{marker}")
        totals = []
        for split in Split:
            in_split = [p for p in photos if p.split is split]
            labelled = [p for p in in_split if p.states.get(trait.trait_id) in kept]
            totals.append(f"{len(labelled)}/{len(in_split)}")
        lines.append(f"  {'scored':>6} {totals[0]:>15} {totals[1]:>19} {totals[2]:>14}  (images in a head state / all images)")
    return lines


def read_labelled_trait_photos(
    manifest_path: Path, split_path: Path, descriptors_path: Path
) -> tuple[list[TraitPhoto], dict[str, dict[str, AccessionTrait]]]:
    """Every photo of the split with its accession's states, and every accession's label per
    candidate trait (for reports)."""
    observations = read_observations(descriptors_path)
    accessions = {row["cultivar_label"] for row in read_cultivar_split(split_path)}
    labels_by_trait = {trait.trait_id: trait_labels(trait, accessions, observations) for trait in CANDIDATE_TRAITS}
    return read_trait_photos(manifest_path, split_path, labels_by_trait), labels_by_trait


def candidate_trait(trait_id: str) -> CandidateTrait:
    """The candidate trait with `trait_id`; raises ValueError for any other id."""
    for trait in CANDIDATE_TRAITS:
        if trait.trait_id == trait_id:
            return trait
    raise ValueError(f"{trait_id!r} is not a candidate trait: {[t.trait_id for t in CANDIDATE_TRAITS]}")
