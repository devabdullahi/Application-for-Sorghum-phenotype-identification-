import numpy as np
import pytest

from sorghum_model.calibration import (
    choose_sorghum_threshold,
    expected_calibration_error,
    fit_temperature,
    negative_log_likelihood,
    softmax,
)


def test_softmax_rows_sum_to_one_and_survive_large_logits():
    probabilities = softmax(np.array([[1000.0, 0.0], [1.0, 1.0]]))
    assert probabilities.sum(axis=1) == pytest.approx([1, 1])
    assert probabilities[1] == pytest.approx([0.5, 0.5])


def test_fit_temperature_undoes_known_overconfidence():
    rng = np.random.default_rng(0)
    # Logits whose calibrated temperature is 1, then sharpened 3x.
    true_logits = rng.normal(size=(4000, 3))
    true_probabilities = softmax(true_logits)
    labels = np.array([rng.choice(3, p=p) for p in true_probabilities])
    temperature = fit_temperature(true_logits * 3, labels)
    assert temperature == pytest.approx(3, rel=0.15)


def test_fitted_temperature_is_no_worse_than_one():
    rng = np.random.default_rng(1)
    logits = rng.normal(size=(500, 4)) * 5
    labels = rng.integers(0, 4, 500)
    temperature = fit_temperature(logits, labels)
    assert negative_log_likelihood(logits, labels, temperature) <= negative_log_likelihood(
        logits, labels, 1.0
    )


def test_ece_is_zero_when_confidence_matches_accuracy():
    probabilities = np.array([[0.5, 0.5]] * 4)
    labels = np.array([0, 1, 0, 1])
    assert expected_calibration_error(probabilities, labels, bins=10) == pytest.approx(0)


def test_ece_of_confidently_wrong_model_is_its_confidence():
    probabilities = np.array([[0.9, 0.1]] * 10)
    labels = np.ones(10, dtype=int)
    assert expected_calibration_error(probabilities, labels, bins=10) == pytest.approx(0.9)


def test_threshold_is_lowest_reaching_precision_target():
    probabilities = np.array([0.95, 0.9, 0.8, 0.7, 0.6])
    is_sorghum = np.array([True, True, True, False, True])
    chosen = choose_sorghum_threshold(probabilities, is_sorghum, 0.99, min_predictions=1)
    # 0.6 and 0.7 include the look-alike at 0.7 (precision 0.8 and 0.75); 0.8 is clean.
    assert chosen.threshold == 0.8
    assert chosen.precision == 1.0
    assert chosen.recall == 0.75


def test_threshold_needs_enough_predictions():
    probabilities = np.array([0.9, 0.5])
    is_sorghum = np.array([True, False])
    with pytest.raises(ValueError, match="no threshold"):
        choose_sorghum_threshold(probabilities, is_sorghum, 0.99, min_predictions=2)
