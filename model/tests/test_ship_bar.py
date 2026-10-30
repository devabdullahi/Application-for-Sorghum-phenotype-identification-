import numpy as np
import pytest

from sorghum_model.settings import ExportSettings
from sorghum_model.ship_bar import (
    BelowShipBarError,
    converter_version_problems,
    enforce_ship_bar,
    ship_bar_problems,
    sorghum_decision_accuracy,
)

SETTINGS = ExportSettings(min_sorghum_accuracy=0.90, max_quantization_accuracy_delta=0.02)


def test_decision_accuracy_uses_the_threshold():
    probabilities = np.array([0.9, 0.6, 0.2, 0.8])
    is_sorghum = np.array([True, True, False, False])
    assert sorghum_decision_accuracy(probabilities, is_sorghum, 0.7) == 0.5


def test_bar_met_exactly():
    assert ship_bar_problems(0.90, 0.85, 0.83, SETTINGS) == []


def test_sorghum_accuracy_just_below_the_bar():
    problems = ship_bar_problems(0.899, 0.85, 0.85, SETTINGS)
    assert len(problems) == 1 and "sorghum-vs-not" in problems[0]


def test_quantization_delta_just_above_the_bar():
    problems = ship_bar_problems(0.95, 0.85, 0.829, SETTINGS)
    assert len(problems) == 1 and "INT8" in problems[0]


def test_export_refuses_below_the_bar_unless_allowed():
    problems = ship_bar_problems(0.5, 0.9, 0.5, SETTINGS)
    with pytest.raises(BelowShipBarError, match="--allow-below-bar"):
        enforce_ship_bar(problems, allow_below_bar=False)
    assert enforce_ship_bar(problems, allow_below_bar=True) is True
    assert enforce_ship_bar([], allow_below_bar=False) is False


@pytest.mark.parametrize("field, value", [("min_sorghum_accuracy", 0.5), ("max_quantization_accuracy_delta", -0.01)])
def test_settings_reject_out_of_range_bars(field, value):
    with pytest.raises(ValueError):
        ExportSettings(**{field: value})


@pytest.mark.parametrize(
    ("version", "is_accepted"),
    [("2.17.0", True), ("2.17.1", True), ("2.16.2", False), ("2.18.0", False), ("2.20.0", False)],
)
def test_converter_must_match_the_phone_runtime(version, is_accepted):
    problems = converter_version_problems(version, ExportSettings(converter_tensorflow_version="2.17"))
    assert (problems == []) is is_accepted
