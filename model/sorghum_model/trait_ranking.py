"""Offline check of trait-first identification (ADR-0001) on GRIN: trait readings through
naive Bayes to a race or accession ranking (T12, #35). Pure numpy; no TensorFlow.

Mirrors `shared/reasoning` (CultivarIdentification.kt) so the numbers say what the app's
reasoning would do with these readings:

- every reading and every table row gets the noise floor the app applies
  (`TraitEstimate.withNoiseFloor`: p * (1 - k * floor) + floor over the k catalogue states);
- each trait is soft evidence: P(reading | class) = sum over states of
  P(state | class) * reading(state), multiplied over traits (naive Bayes);
- a trait without a reading is left out, as the app ignores traits it did not read.

Classes are either races (tables from training accessions' GRIN states per race) or single
accessions (each accession's own GRIN states, as a genebank table would hold them). Readings
are the heads' calibrated outputs, or the accession's GRIN states ("oracle"), which shows the
ceiling a perfect trait reader would reach with these traits.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence

import numpy as np

from sorghum_model.cultivar_traits import HUNDRED_SEED_WEIGHT_TRAIT, CandidateTrait, TraitPhoto, candidate_trait
from sorghum_model.race_evaluation import choose_answer_rule, evaluate_races, top1_accuracy
from sorghum_model.race_photos import race_class_names
from sorghum_model.settings import RaceRuleSearchSettings
from sorghum_model.splits import Split


def with_noise_floor(raw: np.ndarray, floor: float) -> np.ndarray:
    """Rows normalised, then floored as `TraitEstimate.withNoiseFloor`: p * (1 - k * floor) + floor."""
    states = raw.shape[-1]
    if not 0 < floor * states < 1:
        raise ValueError(f"a floor of {floor} over {states} states leaves no mass for the reading")
    totals = raw.sum(axis=-1, keepdims=True)
    if np.any(totals <= 0):
        raise ValueError("every row needs some probability before the floor")
    return raw / totals * (1 - states * floor) + floor


def head_reading(head_probabilities: np.ndarray, head_states: Sequence[str], trait: CandidateTrait, floor: float) -> np.ndarray:
    """A head's outputs as catalogue-wide readings: states without an output get 0, then the floor."""
    raw = np.zeros((len(head_probabilities), len(trait.catalogue_states)))
    for column, state in enumerate(head_states):
        raw[:, trait.catalogue_states.index(state)] = head_probabilities[:, column]
    return with_noise_floor(raw, floor)


def state_reading(states: Sequence[str], trait: CandidateTrait, floor: float) -> np.ndarray:
    """Near-certain readings of known states (the oracle), floored like a user correction."""
    raw = np.zeros((len(states), len(trait.catalogue_states)))
    for row, state in enumerate(states):
        raw[row, trait.catalogue_states.index(state)] = 1.0
    return with_noise_floor(raw, floor)


def race_tables(
    train_photos: Sequence[TraitPhoto], trait: CandidateTrait, races: Sequence[str], floor: float
) -> np.ndarray:
    """(races x catalogue states) P(state | race), counted over training accessions (each
    once), floored. A race with no labelled training accession gets a uniform row."""
    counts = np.zeros((len(races), len(trait.catalogue_states)))
    seen: set[str] = set()
    for photo in train_photos:
        state = photo.states.get(trait.trait_id)
        if not state or photo.race not in races or photo.accession in seen:
            continue
        seen.add(photo.accession)
        counts[list(races).index(photo.race), trait.catalogue_states.index(state)] += 1
    counts[counts.sum(axis=1) == 0] = 1.0
    return with_noise_floor(counts, floor)


def race_log_prior(train_photos: Sequence[TraitPhoto], races: Sequence[str]) -> np.ndarray:
    """ln P(race) from training accessions, each counted once."""
    race_of = {p.accession: p.race for p in train_photos if p.race in races}
    counts = Counter(race_of.values())
    return np.log(np.array([counts[race] for race in races], dtype=float) / len(race_of))


def log_likelihoods(readings: dict[str, np.ndarray], tables: dict[str, np.ndarray], is_read: dict[str, np.ndarray]) -> np.ndarray:
    """(photos x classes) sum over read traits of ln(sum_s P(s | class) * reading(s)).

    `is_read[trait]` marks the photos with a reading of the trait; the others skip it.
    """
    total = None
    for trait_id, reading in readings.items():
        per_trait = np.log(reading @ tables[trait_id].T) * is_read[trait_id][:, np.newaxis]
        total = per_trait if total is None else total + per_trait
    if total is None:
        raise ValueError("no readings")
    return total


def posteriors(log_likelihood: np.ndarray, log_prior: np.ndarray | None = None) -> np.ndarray:
    """Row-wise softmax of log likelihood (+ log prior)."""
    scores = log_likelihood if log_prior is None else log_likelihood + log_prior
    shifted = scores - scores.max(axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def accession_tables(
    accessions: Sequence[str], states_by_accession: dict[str, dict[str, str]], trait: CandidateTrait, floor: float
) -> tuple[np.ndarray, np.ndarray]:
    """(accessions x catalogue states) rows from each accession's own GRIN state, floored;
    an accession without a state for the trait gets a uniform row. Also returns which
    accessions have a state."""
    raw = np.ones((len(accessions), len(trait.catalogue_states)))
    has_state = np.zeros(len(accessions), dtype=bool)
    for row, accession in enumerate(accessions):
        state = states_by_accession.get(accession, {}).get(trait.trait_id)
        if state:
            raw[row] = 0.0
            raw[row, trait.catalogue_states.index(state)] = 1.0
            has_state[row] = True
    return with_noise_floor(raw, floor), has_state


def tie_aware_top_k(scores: np.ndarray, true_columns: np.ndarray, k: int) -> float:
    """Mean chance that the true class is in the top k when tied scores are ordered at random.

    With b classes strictly better and t others tied with the true one, the true class lands
    uniformly at rank b+1 .. b+t+1, so it is in the top k with chance clip(k - b, 0, t+1)/(t+1).
    Trait profiles have few states, so many accessions share a profile and ties are common.
    """
    true_scores = scores[np.arange(len(scores)), true_columns][:, np.newaxis]
    # Relative tolerance: equal profiles give equal sums of logs up to float rounding.
    tolerance = 1e-9 * np.maximum(1.0, np.abs(true_scores))
    better = (scores > true_scores + tolerance).sum(axis=1)
    tied = (np.abs(scores - true_scores) <= tolerance).sum(axis=1) - 1
    return float(np.mean(np.clip(k - better, 0, tied + 1) / (tied + 1)))


def states_by_accession(photos: Sequence[TraitPhoto]) -> dict[str, dict[str, str]]:
    """Each accession's GRIN states (the same on all its photos)."""
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for photo in photos:
        result[photo.accession].update(photo.states)
    return dict(result)


def ranking_check(
    photos: Sequence[TraitPhoto],
    head_states: dict[str, tuple[str, ...]],
    head_outputs: dict[str, np.ndarray],
    floor: float,
    target_coverage: float,
    search: RaceRuleSearchSettings,
) -> dict:
    """Race and accession ranking on validation and test from trait readings alone.

    `head_outputs` is the `trait-heads-vN-outputs.npz` content: calibrated INT8 probabilities
    per "<head>/<split>" and the photos' sha256 per "sha256/<split>". Variants:
    `heads` reads every head; `oracle` reads the same traits from GRIN (a perfect reader);
    `oracleWithSeedWeight` adds GRIN's 100-seed weight (a perfect measured reader). The race
    answer rule is chosen on validation (`race_evaluation.choose_answer_rule`), then test is
    scored with it. Race tables and prior come from training accessions only.
    """
    # race_class_names reads only `race` and `split`, which trait photos have too.
    races = race_class_names([p for p in photos if p.race])
    train = [p for p in photos if p.split is Split.TRAIN and p.race]
    by_split = {split: [p for p in photos if p.split is split] for split in (Split.VALIDATION, Split.TEST)}
    for split, split_photos in by_split.items():
        if [p.sha256 for p in split_photos] != list(head_outputs[f"sha256/{split.value}"]):
            raise ValueError(f"head outputs do not list the {split.value} photos of this split in order")

    head_traits = [candidate_trait(trait_id) for trait_id in head_states]
    variants = {
        "heads": head_traits,
        "oracle": head_traits,
        "oracleWithSeedWeight": [*head_traits, HUNDRED_SEED_WEIGHT_TRAIT],
    }
    tables = {trait.trait_id: race_tables(train, trait, races, floor) for trait in variants["oracleWithSeedWeight"]}
    log_prior = race_log_prior(train, races)
    genebank = sorted({p.accession for p in photos if p.states})
    genebank_states = states_by_accession(photos)

    def readings(variant: str, split: Split) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
        split_photos = by_split[split]
        values, is_read = {}, {}
        for trait in variants[variant]:
            if variant == "heads":
                values[trait.trait_id] = head_reading(
                    head_outputs[f"{trait.trait_id}/{split.value}"], head_states[trait.trait_id], trait, floor
                )
                is_read[trait.trait_id] = np.ones(len(split_photos), dtype=bool)
            else:
                states = [p.states.get(trait.trait_id, trait.catalogue_states[0]) for p in split_photos]
                values[trait.trait_id] = state_reading(states, trait, floor)
                is_read[trait.trait_id] = np.array([trait.trait_id in p.states for p in split_photos])
        return values, is_read

    result: dict = {"races": list(races), "floor": floor, "variants": {}}
    for variant, traits in variants.items():
        race_posteriors = {}
        for split in by_split:
            values, is_read = readings(variant, split)
            race_posteriors[split] = posteriors(log_likelihoods(values, {t.trait_id: tables[t.trait_id] for t in traits}, is_read), log_prior)
        scored = {split: [i for i, p in enumerate(by_split[split]) if p.race in races] for split in by_split}
        truth = {split: [by_split[split][i].race for i in scored[split]] for split in by_split}
        accessions = {split: [by_split[split][i].accession for i in scored[split]] for split in by_split}
        summary: dict = {
            "traits": [t.trait_id for t in traits],
            "testRacePhotos": len(scored[Split.TEST]),
            "testTop1": top1_accuracy(truth[Split.TEST], race_posteriors[Split.TEST][scored[Split.TEST]], races),
            "testTop3": tie_aware_top_k(
                race_posteriors[Split.TEST][scored[Split.TEST]],
                np.array([races.index(r) for r in truth[Split.TEST]]), 3,
            ),
        }
        try:
            chosen = choose_answer_rule(
                truth[Split.VALIDATION], accessions[Split.VALIDATION],
                race_posteriors[Split.VALIDATION][scored[Split.VALIDATION]], races, target_coverage, search,
            )
            test = evaluate_races(
                truth[Split.TEST], accessions[Split.TEST], race_posteriors[Split.TEST][scored[Split.TEST]], races,
                chosen.settings,
            )
            summary["answerRule"] = chosen.settings.__dict__
            summary["test"] = {
                "coverage": test.coverage, "selectiveAccuracy": test.selective_accuracy,
                "accuracyOverAllPhotos": test.accuracy, "meanGroupSize": test.mean_group_size,
            }
        except ValueError as error:
            summary["answerRule"] = {"reachable": False, "reason": str(error)}

        # Accession matching over every labelled accession, as a genebank table would hold them.
        test_photos = by_split[Split.TEST]
        values, is_read = readings(variant, Split.TEST)
        scores = np.zeros((len(test_photos), len(genebank)))
        for trait in traits:
            rows, _ = accession_tables(genebank, genebank_states, trait, floor)
            scores += np.log(values[trait.trait_id] @ rows.T) * is_read[trait.trait_id][:, np.newaxis]
        in_table = [i for i, p in enumerate(test_photos) if p.accession in genebank]
        true_columns = np.array([genebank.index(test_photos[i].accession) for i in in_table])
        summary["accessionMatching"] = {
            "candidates": len(genebank),
            "testPhotos": len(in_table),
            **{f"top{k}": tie_aware_top_k(scores[in_table], true_columns, k) for k in (1, 10, 100)},
        }
        result["variants"][variant] = summary
    return result
