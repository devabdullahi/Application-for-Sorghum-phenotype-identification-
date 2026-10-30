"""Returned race groups, abstention and the group-aware race metrics."""

import numpy as np
import pytest

from sorghum_model.race_evaluation import (
    UNRECOGNIZED,
    RaceEvaluation,
    choose_answer_rule,
    evaluate_basic_races,
    evaluate_races,
    majority_race_probabilities,
    parent_basic_races,
    planting_race_probabilities,
    planting_shortcut_check,
    race_evaluation_report,
    race_gate_problems,
    returned_group,
    top1_accuracy,
)
from sorghum_model.settings import RaceEvaluationSettings, RaceGateSettings, RaceRuleSearchSettings

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


TWO_RACES = ("Caudatum", "Durra")
# Ten photos: five confident hits, five near ties. A mass up to 0.6 answers the ties with one
# race (correct for three of them); above 0.6 they need two races and, with groups of one
# allowed only, are unrecognized.
CHOICE_PROBABILITIES = np.array([[0.95, 0.05]] * 5 + [[0.6, 0.4]] * 5)
CHOICE_TRUTH = ["Caudatum"] * 5 + ["Caudatum"] * 3 + ["Durra"] * 2
CHOICE_ACCESSIONS = [f"PI {index}" for index in range(10)]
GROUPS_OF_ONE = RaceRuleSearchSettings(coverage_margin=0.0, max_group_sizes=(1,))


def choose(target_coverage, search=GROUPS_OF_ONE):
    return choose_answer_rule(
        CHOICE_TRUTH, CHOICE_ACCESSIONS, CHOICE_PROBABILITIES, TWO_RACES, target_coverage, search
    )


def test_rule_choice_prefers_accuracy_once_coverage_is_met():
    # Coverage 0.5 is enough: abstaining on the five ties gives selective accuracy 1.0.
    chosen = choose(0.5)
    assert chosen.validation.coverage == pytest.approx(0.5)
    assert chosen.validation.selective_accuracy == pytest.approx(1.0)
    assert chosen.settings.group_probability_mass > 0.6


def test_rule_choice_at_just_above_and_below_the_reachable_coverage():
    # At coverage 1.0 (just above 0.5) only masses up to 0.6 qualify: accuracy 8 / 10.
    chosen = choose(1.0)
    assert chosen.validation.coverage == pytest.approx(1.0)
    assert chosen.validation.selective_accuracy == pytest.approx(0.8)
    assert chosen.settings.group_probability_mass <= 0.6
    # Just below 0.5 the abstaining rule still qualifies.
    assert choose(0.49).validation.coverage == pytest.approx(0.5)


def test_rule_choice_adds_the_coverage_margin():
    # 0.5 + 0.02 rules out the abstaining rule.
    with_margin = RaceRuleSearchSettings(coverage_margin=0.02, max_group_sizes=(1,))
    assert choose(0.5, with_margin).validation.coverage == pytest.approx(1.0)


def test_rule_choice_refuses_an_unreachable_coverage():
    never_answers = np.array([[0.5, 0.5]] * 4)
    with pytest.raises(ValueError, match="no answer rule"):
        choose_answer_rule(
            ["Durra"] * 4, ["PI 1"] * 4, never_answers, TWO_RACES, 0.5,
            RaceRuleSearchSettings(min_group_mass=0.9, max_group_sizes=(1,)),
        )


def test_majority_baseline_answers_every_photo_with_the_commonest_training_race():
    probabilities = majority_race_probabilities(["Durra", "Durra", "Caudatum"], TWO_RACES, 3)
    assert probabilities.tolist() == [[0.0, 1.0]] * 3
    assert top1_accuracy(["Durra", "Caudatum", "Durra"], probabilities, TWO_RACES) == pytest.approx(2 / 3)


def test_planting_baseline_uses_each_plantings_commonest_race_or_the_overall_one():
    probabilities = planting_race_probabilities(
        train_races=["Durra", "Durra", "Caudatum"],
        train_plantings=["A", "A", "B"],
        plantings=["B", "A", "unseen"],
        races=TWO_RACES,
    )
    assert probabilities.tolist() == [[1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]


@pytest.mark.parametrize(
    "fields",
    [
        {"coverage_margin": -0.01},
        {"coverage_margin": 0.1},
        {"min_group_mass": 0.49},
        {"min_group_mass": 0.9, "max_group_mass": 0.8},
        {"max_group_mass": 1.0},
        {"group_mass_step": 0.0},
        {"group_mass_step": 0.11},
        {"max_group_sizes": ()},
        {"max_group_sizes": (4,)},
        {"max_group_sizes": (0,)},
    ],
)
def test_rule_search_settings_refuse_values_outside_their_range(fields):
    with pytest.raises(ValueError):
        RaceRuleSearchSettings(**fields)


def test_rule_search_settings_accept_their_range_edges_and_list_the_grid():
    RaceRuleSearchSettings(coverage_margin=0.0, group_mass_step=0.1, max_group_sizes=(1, 3))
    RaceRuleSearchSettings(coverage_margin=0.099, min_group_mass=0.99, max_group_mass=0.99)
    masses = RaceRuleSearchSettings().group_masses()
    assert masses[0] == 0.5 and masses[-1] == 0.99 and len(masses) == 50



def scored(hits, answered, photos=100):
    return RaceEvaluation(photos, answered, hits, answered, {}, {}, {})


GATE = RaceGateSettings()


def test_gate_passes_at_its_thresholds():
    # 72 / 80 = 0.90 selective at coverage 0.80, 0.10 over a 0.80 baseline, delta 0.
    at_bar = scored(hits=72, answered=80)
    assert race_gate_problems(at_bar, at_bar, 0.80, GATE) == []


def test_gate_reports_each_miss_just_past_its_threshold():
    just_under_accuracy = scored(hits=88, answered=100)  # 0.88
    assert race_gate_problems(just_under_accuracy, just_under_accuracy, 0.5, GATE) == [
        "selective accuracy 0.880 < 0.89"
    ]
    just_under_coverage = scored(hits=79, answered=79)
    assert race_gate_problems(just_under_coverage, just_under_coverage, 0.5, GATE) == ["coverage 0.790 < 0.80"]
    good = scored(hits=90, answered=100)
    assert race_gate_problems(good, good, 0.81, GATE) == ["only 0.090 above the best baseline (0.810)"]
    float_three_points_better = scored(hits=93, answered=100)
    assert race_gate_problems(good, float_three_points_better, 0.5, GATE) == [
        "float/INT8 selective accuracy delta 0.030 > 0.02"
    ]


@pytest.mark.parametrize(
    "fields",
    [
        {"min_selective_accuracy": 0.0},
        {"min_selective_accuracy": 1.01},
        {"min_coverage": 0.0},
        {"min_points_over_baseline": -0.01},
        {"min_points_over_baseline": 1.0},
        {"max_int8_accuracy_delta": -0.01},
        {"max_int8_accuracy_delta": 0.5},
    ],
)
def test_gate_settings_refuse_values_outside_their_range(fields):
    with pytest.raises(ValueError):
        RaceGateSettings(**fields)


FAMILY = ("Durra", "Durra-bicolor", "Guinea", "Kafir-caudatum")


def test_parent_basic_races_reads_both_parents_of_an_intermediate():
    assert parent_basic_races("Durra") == {"Durra"}
    assert parent_basic_races("Durra-bicolor") == {"Durra", "Bicolor"}
    with pytest.raises(ValueError):
        parent_basic_races("Shattercane")


def test_basic_race_metric_counts_a_shared_parent_as_a_hit_and_keeps_abstentions():
    one_race = RaceEvaluationSettings(group_probability_mass=0.9, max_group_size=1)
    probabilities = np.array(
        [
            [0.95, 0.05, 0.0, 0.0],  # Durra-bicolor photo answered Durra: a basic-race hit
            [0.0, 0.0, 0.95, 0.05],  # Kafir-caudatum photo answered Guinea: a miss
            [0.5, 0.5, 0.0, 0.0],  # needs two races: abstains
        ]
    )
    result = evaluate_basic_races(["Durra-bicolor", "Kafir-caudatum", "Durra"], probabilities, FAMILY, one_race)
    assert (result.photo_count, result.answered_count, result.hit_count) == (3, 2, 1)
    assert result.coverage == pytest.approx(2 / 3)
    assert result.selective_accuracy == pytest.approx(1 / 2)


def test_planting_check_compares_the_model_with_the_planting_baseline_inside_each_planting():
    one_race = RaceEvaluationSettings(group_probability_mass=0.9, max_group_size=1)
    # Planting A trained mostly on Durra; the model gets both A photos right, the baseline one.
    probabilities = np.array([[1.0, 0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]])
    checks = planting_shortcut_check(
        true_races=["Durra", "Guinea", "Durra"],
        accessions=["PI 1", "PI 2", "PI 3"],
        plantings=["A", "A", "B"],
        probabilities=probabilities,
        races=FAMILY,
        settings=one_race,
        train_races=["Durra", "Durra", "Guinea"],
        train_plantings=["A", "A", "B"],
    )
    assert [(c.planting_id, c.photo_count) for c in checks] == [("A", 2), ("B", 1)]
    assert checks[0].selective_accuracy == pytest.approx(1.0)
    assert checks[0].planting_baseline_accuracy == pytest.approx(0.5)
    assert checks[0].gain_over_baseline == pytest.approx(0.5)
    assert checks[1].selective_accuracy == 0.0 and checks[1].planting_baseline_accuracy == 0.0
