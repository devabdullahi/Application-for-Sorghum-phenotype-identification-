"""Held-out scores of a learned trait head and its R6 gate (T12, #35). Pure numpy; no TensorFlow.

A trait head gives calibrated probabilities over its descriptor states. Unlike the race
answer, a trait is never abstained on: `shared/` turns every output into a `TraitEstimate`
and naive Bayes weighs it, so the head is scored on every photo whose accession has a state
the head outputs. Reported per head: top-1 accuracy, macro recall (mean per-state recall, so
a head that only knows the commonest state scores low), ECE, per-state support and recall,
and the confusion matrix. Each is compared with the majority-state and planting baselines
(`race_evaluation.majority_race_probabilities` and `planting_race_probabilities` work on any
label, not only races).
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from sorghum_model.calibration import expected_calibration_error
from sorghum_model.settings import TraitGateSettings

# Differences of float ratios fall short of exact values (0.9 - 0.8 < 0.1).
_RATIO_TOLERANCE = 1e-9


@dataclass(frozen=True)
class TraitEvaluation:
    """Scores of one head on one split.

    Attributes:
        photo_count: photos scored.
        correct_count: photos whose most probable state is the true state.
        recall_by_state: state -> share of its photos predicted as that state.
        support: state -> (photos, accessions) in this split.
        confusion: (true state, top-1 state) -> photos.
        ece: expected calibration error of the probabilities as given (pass calibrated ones).
    """

    photo_count: int
    correct_count: int
    recall_by_state: dict[str, float]
    support: dict[str, tuple[int, int]]
    confusion: dict[tuple[str, str], int]
    ece: float

    @property
    def accuracy(self) -> float:
        return self.correct_count / self.photo_count if self.photo_count else 0.0

    @property
    def macro_recall(self) -> float:
        """Mean recall over the states present in the split."""
        return float(np.mean(list(self.recall_by_state.values()))) if self.recall_by_state else 0.0


def evaluate_trait(
    true_states: Sequence[str],
    accessions: Sequence[str],
    probabilities: np.ndarray,
    states: Sequence[str],
    ece_bins: int,
) -> TraitEvaluation:
    """Scores one split; row i of `probabilities` belongs to photo i, columns follow `states`."""
    if not len(true_states) == len(accessions) == len(probabilities):
        raise ValueError("true_states, accessions and probabilities must have one entry per photo")
    if probabilities.ndim != 2 or probabilities.shape[1] != len(states):
        raise ValueError(f"probabilities need one column per state ({len(states)})")
    unknown = sorted(set(true_states) - set(states))
    if unknown:
        raise ValueError(f"true states {unknown} are not head outputs; photos of other states must not be scored")

    predicted = [states[index] for index in probabilities.argmax(axis=1)]
    confusion = Counter(zip(true_states, predicted, strict=True))
    photos_by_state = Counter(true_states)
    accessions_by_state = {
        state: len({a for a, s in zip(accessions, true_states, strict=True) if s == state}) for state in photos_by_state
    }
    labels = np.array([list(states).index(state) for state in true_states], dtype=np.int64)
    return TraitEvaluation(
        photo_count=len(true_states),
        correct_count=sum(1 for t, p in zip(true_states, predicted, strict=True) if t == p),
        recall_by_state={
            state: confusion[(state, state)] / count for state, count in sorted(photos_by_state.items())
        },
        support={state: (photos_by_state[state], accessions_by_state[state]) for state in photos_by_state},
        confusion=dict(confusion),
        ece=expected_calibration_error(probabilities, labels, ece_bins) if len(labels) else 0.0,
    )


def trait_gate_problems(
    int8_test: TraitEvaluation,
    float_test: TraitEvaluation,
    best_baseline_accuracy: float,
    gate: TraitGateSettings,
) -> list[str]:
    """Every way a head's INT8 test result misses the R6 gate; empty when it passes.

    `float_test` is the float model on the same photos; `best_baseline_accuracy` the better of
    the majority-state and planting baselines on test.
    """
    problems = []
    if int8_test.accuracy < gate.min_accuracy:
        problems.append(f"accuracy {int8_test.accuracy:.3f} < {gate.min_accuracy:.2f}")
    margin = int8_test.accuracy - best_baseline_accuracy
    if margin < gate.min_points_over_baseline - _RATIO_TOLERANCE:
        problems.append(f"only {margin:.3f} above the best baseline ({best_baseline_accuracy:.3f})")
    if int8_test.macro_recall < gate.min_macro_recall:
        problems.append(f"macro recall {int8_test.macro_recall:.3f} < {gate.min_macro_recall:.2f}")
    if int8_test.ece > gate.max_ece + _RATIO_TOLERANCE:
        problems.append(f"ECE {int8_test.ece:.3f} > {gate.max_ece:.2f}")
    delta = abs(float_test.accuracy - int8_test.accuracy)
    if delta > gate.max_int8_accuracy_delta + _RATIO_TOLERANCE:
        problems.append(f"float/INT8 accuracy delta {delta:.3f} > {gate.max_int8_accuracy_delta:.2f}")
    return problems


def trait_evaluation_report(evaluation: TraitEvaluation, states: Sequence[str]) -> list[str]:
    """Human-readable lines: headline numbers, per-state support and recall, confusion matrix."""
    lines = [
        f"photos {evaluation.photo_count}, accuracy {evaluation.accuracy:.3f}, "
        f"macro recall {evaluation.macro_recall:.3f}, ECE {evaluation.ece:.3f}",
        f"{'state':>6} {'photos':>7} {'accessions':>10} {'recall':>7}",
    ]
    for state in states:
        photos, accession_count = evaluation.support.get(state, (0, 0))
        recall = evaluation.recall_by_state.get(state, 0.0)
        lines.append(f"{state:>6} {photos:>7} {accession_count:>10} {recall:>7.3f}")
    lines.append("confusion (rows: true state; columns: top-1 state)")
    lines.append(f"{'':>6} " + " ".join(f"{state:>5}" for state in states))
    for state in states:
        lines.append(f"{state:>6} " + " ".join(f"{evaluation.confusion.get((state, column), 0):>5}" for column in states))
    return lines


def match_heads_to_outputs(
    float_logits_by_head: dict[str, np.ndarray], int8_logits_by_output: Sequence[np.ndarray]
) -> dict[str, int]:
    """Which TFLite output index carries each head.

    The converter does not keep output names or order, so each head is matched, among the
    outputs with its number of states, to the one whose top-1 agrees most with the float
    head on the same photos. Raises ValueError when the match is not one-to-one or a best
    agreement is below one half, because then a head would be read from the wrong output.
    """
    matched: dict[str, int] = {}
    for head, float_logits in float_logits_by_head.items():
        agreements = {
            index: float(np.mean(output.argmax(axis=1) == float_logits.argmax(axis=1)))
            for index, output in enumerate(int8_logits_by_output)
            if output.shape == float_logits.shape
        }
        if not agreements:
            raise ValueError(f"no output has the shape of head {head} {float_logits.shape}")
        best = max(agreements, key=agreements.get)
        if agreements[best] < 0.5:
            raise ValueError(f"head {head}: best output {best} agrees with the float head on only {agreements[best]:.2f}")
        matched[head] = best
    if len(set(matched.values())) != len(matched):
        raise ValueError(f"two heads matched one output: {matched}")
    return matched
