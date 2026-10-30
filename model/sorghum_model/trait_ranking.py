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

from sorghum_model.cultivar_traits import CandidateTrait, TraitPhoto


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
