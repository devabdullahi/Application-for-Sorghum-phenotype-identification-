"""The ship bar an exported model must meet (ExportSettings), checked before any file is written.

Kept free of TensorFlow so it is unit-tested in the light environment.
"""

import numpy as np

from sorghum_model.settings import ExportSettings


# Accuracies are fractions of whole photos, so 0.85 - 0.83 must count as exactly 0.02 and not
# as the 0.0200000000000001 floating point gives.
_FLOAT_TOLERANCE = 1e-9


class BelowShipBarError(ValueError):
    """The model misses the ship bar and `--allow-below-bar` was not given."""


def sorghum_decision_accuracy(
    sorghum_probabilities: np.ndarray, is_sorghum: np.ndarray, threshold: float
) -> float:
    """Accuracy of "is this sorghum?" as the app decides it: P(sorghum) >= threshold."""
    if len(is_sorghum) == 0:
        return 0.0
    return float(((sorghum_probabilities >= threshold) == is_sorghum).mean())


def ship_bar_problems(
    sorghum_accuracy: float, float_accuracy: float, int8_accuracy: float, settings: ExportSettings
) -> list[str]:
    """Describes each missed bar; empty when the model may ship."""
    problems = []
    if sorghum_accuracy < settings.min_sorghum_accuracy - _FLOAT_TOLERANCE:
        problems.append(
            f"held-out sorghum-vs-not accuracy {sorghum_accuracy:.3f} is below "
            f"{settings.min_sorghum_accuracy:.2f}"
        )
    delta = abs(float_accuracy - int8_accuracy)
    if delta > settings.max_quantization_accuracy_delta + _FLOAT_TOLERANCE:
        problems.append(
            f"float vs INT8 accuracy differs by {delta:.3f} (float {float_accuracy:.3f}, "
            f"INT8 {int8_accuracy:.3f}), more than {settings.max_quantization_accuracy_delta:.2f}"
        )
    return problems


def enforce_ship_bar(problems: list[str], allow_below_bar: bool) -> bool:
    """Raises BelowShipBarError unless the bar is met or explicitly waived.

    Returns whether the export is below the bar, for `belowBar` in the metadata.
    """
    if problems and not allow_below_bar:
        raise BelowShipBarError(
            "the model misses the ship bar:\n  "
            + "\n  ".join(problems)
            + "\nNothing was written. Pass --allow-below-bar only for a diagnostic export."
        )
    return bool(problems)
