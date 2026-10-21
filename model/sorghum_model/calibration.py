"""Temperature scaling, calibration error and the sorghum decision threshold.

Naive Bayes downstream needs honest probabilities (risk R4), so the species head is
temperature-scaled after INT8 quantization, on validation data, and its ECE is reported.
"""

from dataclasses import dataclass

import numpy as np

# Search range for the inverse temperature 1/T. 0.05..20 covers models from wildly
# overconfident (T = 20) to strongly underconfident (T = 0.05).
_MIN_INVERSE_TEMPERATURE = 0.05
_MAX_INVERSE_TEMPERATURE = 20.0
_SEARCH_ITERATIONS = 100


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """Row-wise softmax of logits divided by temperature, stable for large logits."""
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    scaled = logits / temperature
    shifted = scaled - scaled.max(axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def negative_log_likelihood(logits: np.ndarray, labels: np.ndarray, temperature: float) -> float:
    """Mean negative log-likelihood of the true labels after temperature scaling."""
    scaled = logits / temperature
    shifted = scaled - scaled.max(axis=1, keepdims=True)
    log_normaliser = np.log(np.exp(shifted).sum(axis=1))
    return float(np.mean(log_normaliser - shifted[np.arange(len(labels)), labels]))


def fit_temperature(logits: np.ndarray, labels: np.ndarray) -> float:
    """Returns the temperature that minimises validation NLL.

    NLL is convex in the inverse temperature (a log-sum-exp minus a linear term), so a
    golden-section search over 1/T finds the global minimum without an optimiser library.
    """
    if len(logits) == 0:
        raise ValueError("need at least one validation example to fit a temperature")
    golden = (np.sqrt(5) - 1) / 2
    low, high = _MIN_INVERSE_TEMPERATURE, _MAX_INVERSE_TEMPERATURE
    for _ in range(_SEARCH_ITERATIONS):
        left = high - golden * (high - low)
        right = low + golden * (high - low)
        if negative_log_likelihood(logits, labels, 1 / left) < negative_log_likelihood(
            logits, labels, 1 / right
        ):
            high = right
        else:
            low = left
    return float(1 / ((low + high) / 2))


def expected_calibration_error(probabilities: np.ndarray, labels: np.ndarray, bins: int) -> float:
    """ECE: weighted mean gap between top-1 confidence and accuracy over equal-width bins."""
    confidences = probabilities.max(axis=1)
    correct = probabilities.argmax(axis=1) == labels
    edges = np.linspace(0, 1, bins + 1)
    error = 0.0
    for lower, upper in zip(edges[:-1], edges[1:]):
        # The first bin includes 0 so every confidence lands in exactly one bin.
        in_bin = (confidences > lower) & (confidences <= upper)
        if lower == 0:
            in_bin |= confidences == 0
        if in_bin.any():
            gap = abs(confidences[in_bin].mean() - correct[in_bin].mean())
            error += in_bin.mean() * gap
    return float(error)


@dataclass(frozen=True)
class SorghumThreshold:
    """Lowest P(sorghum) that reaches the precision target, with its validation numbers."""

    threshold: float
    precision: float
    recall: float
    predicted_sorghum: int


def choose_sorghum_threshold(
    sorghum_probabilities: np.ndarray,
    is_sorghum: np.ndarray,
    precision_target: float,
    min_predictions: int,
) -> SorghumThreshold:
    """Picks the gate threshold on P(sorghum).

    Among thresholds whose precision reaches the target and that pass at least
    `min_predictions` photos, the lowest is chosen, since it keeps the most true sorghum
    (highest recall). Raises ValueError when no threshold qualifies, because shipping a gate
    that cannot meet its precision target would pass look-alikes on to cultivar matching.
    """
    positives = int(is_sorghum.sum())
    if positives == 0:
        raise ValueError("validation split has no sorghum photos")

    best: SorghumThreshold | None = None
    for candidate in np.unique(sorghum_probabilities):
        passed = sorghum_probabilities >= candidate
        predicted = int(passed.sum())
        if predicted < min_predictions:
            continue
        true_positives = int((passed & is_sorghum).sum())
        precision = true_positives / predicted
        if precision >= precision_target:
            best = SorghumThreshold(
                threshold=float(candidate),
                precision=precision,
                recall=true_positives / positives,
                predicted_sorghum=predicted,
            )
            # Candidates are ascending, so the first qualifying one has the highest recall.
            break
    if best is None:
        raise ValueError(
            f"no threshold reaches sorghum precision {precision_target} with at least "
            f"{min_predictions} predictions; more or cleaner data is needed"
        )
    return best
