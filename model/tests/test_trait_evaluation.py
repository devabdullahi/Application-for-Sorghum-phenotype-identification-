"""Trait head scores and the R6 gate."""

import numpy as np
import pytest

from sorghum_model.settings import TraitGateSettings, TraitLabelSettings
from sorghum_model.trait_evaluation import TraitEvaluation, evaluate_trait, trait_gate_problems

STATES = ("1", "4", "5")


def test_scores_accuracy_macro_recall_support_and_confusion():
    truth = ["5", "5", "5", "1"]
    accessions = ["A", "A", "B", "C"]
    probabilities = np.array([[0.1, 0.1, 0.8], [0.1, 0.1, 0.8], [0.6, 0.2, 0.2], [0.2, 0.7, 0.1]])
    evaluation = evaluate_trait(truth, accessions, probabilities, STATES, ece_bins=10)
    assert evaluation.accuracy == pytest.approx(0.5)
    # Recall 2/3 for state 5 and 0 for state 1; state 4 has no photos and is not averaged.
    assert evaluation.macro_recall == pytest.approx(1 / 3)
    assert evaluation.support == {"5": (3, 2), "1": (1, 1)}
    assert evaluation.confusion == {("5", "5"): 2, ("5", "1"): 1, ("1", "4"): 1}


def test_photos_of_a_state_without_an_output_are_refused():
    with pytest.raises(ValueError, match="not head outputs"):
        evaluate_trait(["2"], ["A"], np.array([[0.2, 0.3, 0.5]]), STATES, ece_bins=10)


def test_probabilities_need_one_column_per_state():
    with pytest.raises(ValueError, match="one column per state"):
        evaluate_trait(["1"], ["A"], np.array([[0.5, 0.5]]), STATES, ece_bins=10)


def evaluation(accuracy: float, macro_recall: float = 0.8, ece: float = 0.02) -> TraitEvaluation:
    photos = 1000
    return TraitEvaluation(
        photo_count=photos,
        correct_count=round(accuracy * photos),
        recall_by_state={"1": macro_recall, "2": macro_recall},
        support={},
        confusion={},
        ece=ece,
    )


GATE = TraitGateSettings()


def test_a_head_at_every_bar_passes():
    head = evaluation(0.70, macro_recall=0.50, ece=0.05)
    float_head = evaluation(0.72)
    assert trait_gate_problems(head, float_head, best_baseline_accuracy=0.60, gate=GATE) == []


@pytest.mark.parametrize(
    ("head", "float_accuracy", "baseline", "problem"),
    [
        (evaluation(0.699), 0.699, 0.50, "accuracy 0.699 < 0.70"),
        (evaluation(0.75), 0.75, 0.651, "above the best baseline"),
        (evaluation(0.75, macro_recall=0.499), 0.75, 0.50, "macro recall"),
        (evaluation(0.75, ece=0.051), 0.75, 0.50, "ECE"),
        (evaluation(0.75), 0.771, 0.50, "float/INT8"),
    ],
)
def test_a_head_just_below_a_bar_fails_on_it(head, float_accuracy, baseline, problem):
    problems = trait_gate_problems(head, evaluation(float_accuracy), baseline, GATE)
    assert len(problems) == 1
    assert problem in problems[0]


def test_settings_refuse_values_out_of_range():
    with pytest.raises(ValueError):
        TraitGateSettings(min_accuracy=0)
    with pytest.raises(ValueError):
        TraitGateSettings(max_ece=0)
    with pytest.raises(ValueError):
        TraitLabelSettings(min_train_accessions_per_state=0)


def test_heads_are_matched_to_outputs_by_shape_and_agreement():
    from sorghum_model.trait_evaluation import match_heads_to_outputs

    glume = np.array([[3.0, 0, 0], [0, 3.0, 0], [0, 0, 3.0]])
    grain = np.array([[0, 3.0, 0], [0, 3.0, 0], [3.0, 0, 0]])
    panicle = np.array([[1.0, 0], [0, 1.0], [1.0, 0]])
    # The converter put them in another order.
    outputs = [panicle, grain + 0.1, glume - 0.1]
    assert match_heads_to_outputs({"glume": glume, "grain": grain, "panicle": panicle}, outputs) == {
        "glume": 2, "grain": 1, "panicle": 0,
    }


def test_a_head_without_an_agreeing_output_is_refused():
    from sorghum_model.trait_evaluation import match_heads_to_outputs

    head = np.array([[3.0, 0], [0, 3.0]])
    with pytest.raises(ValueError, match="agrees"):
        match_heads_to_outputs({"h": head}, [-head])
    with pytest.raises(ValueError, match="shape"):
        match_heads_to_outputs({"h": head}, [np.zeros((2, 3))])
