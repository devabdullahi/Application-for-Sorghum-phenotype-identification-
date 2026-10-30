"""Returned race groups, abstention and the group-aware race metrics."""

import numpy as np
import pytest

from sorghum_model.race_evaluation import (
    UNRECOGNIZED,
    evaluate_races,
    race_evaluation_report,
    returned_group,
)
from sorghum_model.settings import RaceEvaluationSettings

RACES = ("Bicolor", "Caudatum", "Durra", "Guinea", "Kafir")
SETTINGS = RaceEvaluationSettings(group_probability_mass=0.9, max_group_size=3)


def test_group_stops_once_the_probability_mass_is_reached():
    # 0.5 + 0.4 equals 0.9 exactly: the group stops at two races.
    assert returned_group(np.array([0.05, 0.5, 0.4, 0.05, 0.0]), RACES, SETTINGS) == ("Caudatum", "Durra")
    # Just below the mass after two races: a third race joins.
    assert returned_group(np.array([0.06, 0.5, 0.39, 0.05, 0.0]), RACES, SETTINGS) == (
        "Caudatum",
        "Durra",
        "Bicolor",
    )
    # A confident model returns one race.
    assert returned_group(np.array([0.0, 0.95, 0.05, 0.0, 0.0]), RACES, SETTINGS) == ("Caudatum",)


def test_a_group_larger_than_the_maximum_is_unrecognized():
    # Three races are needed: still answered (at the maximum).
    at_maximum = np.array([0.3, 0.3, 0.3, 0.1, 0.0])
    assert returned_group(at_maximum, RACES, SETTINGS) == ("Bicolor", "Caudatum", "Durra")
    # Four races are needed: one above the maximum, so the model abstains.
    above_maximum = np.array([0.25, 0.25, 0.25, 0.25, 0.0])
    assert returned_group(above_maximum, RACES, SETTINGS) is None


def test_ties_are_broken_by_race_order():
    assert returned_group(np.array([0.0, 0.0, 0.5, 0.5, 0.0]), RACES, SETTINGS) == ("Durra", "Guinea")


def test_group_refuses_mismatched_lengths():
    with pytest.raises(ValueError):
        returned_group(np.array([1.0]), RACES, SETTINGS)


def evaluation():
    probabilities = np.array(
        [
            [0.0, 0.95, 0.05, 0.0, 0.0],  # Caudatum: hit, group of one
            [0.0, 0.5, 0.4, 0.1, 0.0],  # Durra in group (Caudatum, Durra): hit, top-1 Caudatum
            [0.25, 0.25, 0.25, 0.25, 0.0],  # Durra: unrecognized
            [0.0, 0.0, 0.0, 0.0, 1.0],  # Guinea predicted as Kafir: miss
        ]
    )
    true_races = ["Caudatum", "Durra", "Durra", "Guinea"]
    accessions = ["PI 1", "PI 2", "PI 2", "PI 3"]
    return evaluate_races(true_races, accessions, probabilities, RACES, SETTINGS)


def test_abstentions_lower_coverage_and_accuracy_but_not_selective_accuracy():
    result = evaluation()
    assert result.photo_count == 4
    assert result.coverage == pytest.approx(3 / 4)
    assert result.accuracy == pytest.approx(2 / 4)  # the abstention counts against accuracy
    assert result.selective_accuracy == pytest.approx(2 / 3)
    assert result.mean_group_size == pytest.approx((1 + 2 + 1) / 3)


def test_support_and_confusion_count_photos_accessions_and_abstentions():
    result = evaluation()
    assert result.support == {"Caudatum": (1, 1), "Durra": (2, 1), "Guinea": (1, 1)}
    assert result.hits_by_race == {"Caudatum": 1, "Durra": 1}
    assert result.confusion == {
        ("Caudatum", "Caudatum"): 1,
        ("Durra", "Caudatum"): 1,
        ("Durra", UNRECOGNIZED): 1,
        ("Guinea", "Kafir"): 1,
    }


def test_excluded_labels_cannot_be_scored():
    with pytest.raises(ValueError, match="not model classes"):
        evaluate_races(["Mixed"], ["PI 1"], np.array([[1.0, 0, 0, 0, 0]]), RACES, SETTINGS)


def test_report_has_a_row_per_race_and_an_unrecognized_column():
    lines = race_evaluation_report(evaluation(), RACES)
    assert lines[0].startswith("photos 4, coverage 0.750, group-aware accuracy 0.500")
    durra_confusion = next(line for line in lines if line.startswith("Durra") and len(line.split()) == 7)
    assert durra_confusion.split()[1:] == ["0", "1", "0", "0", "0", "1"]
    assert lines[-1].endswith(f"5 {UNRECOGNIZED}")


@pytest.mark.parametrize(
    ("mass", "size"),
    [(0.49, 3), (1.0, 3), (0.9, 0), (0.9, 16)],
)
def test_settings_refuse_values_outside_their_range(mass, size):
    with pytest.raises(ValueError):
        RaceEvaluationSettings(group_probability_mass=mass, max_group_size=size)


def test_settings_accept_their_range_edges():
    RaceEvaluationSettings(group_probability_mass=0.5, max_group_size=1)
    RaceEvaluationSettings(group_probability_mass=0.999, max_group_size=15)
