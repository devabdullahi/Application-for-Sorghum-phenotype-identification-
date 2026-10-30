"""Naive Bayes over trait readings, mirrored from shared/reasoning, on tiny hand-made tables."""

import numpy as np
import pytest

from sorghum_model.cultivar_traits import CandidateTrait, TraitPhoto
from sorghum_model.splits import Split
from sorghum_model.trait_ranking import (
    accession_tables,
    head_reading,
    log_likelihoods,
    posteriors,
    race_log_prior,
    race_tables,
    state_reading,
    tie_aware_top_k,
    with_noise_floor,
)

COLOUR = CandidateTrait("colour", ("X",), ("1", "2", "3"))
RACES = ("Durra", "Kafir")
FLOOR = 0.01


def photo(accession: str, race: str, state: str | None) -> TraitPhoto:
    return TraitPhoto(f"{accession}.jpg", accession, accession, "P", Split.TRAIN, race, {"colour": state} if state else {})


def test_noise_floor_matches_shared():
    # TraitEstimate.withNoiseFloor: p * (1 - k * floor) + floor.
    floored = with_noise_floor(np.array([[2.0, 0.0, 0.0]]), FLOOR)
    assert floored[0] == pytest.approx([0.97 + 0.01, 0.01, 0.01])
    assert floored.sum() == pytest.approx(1.0)
    with pytest.raises(ValueError):
        with_noise_floor(np.array([[1.0, 0.0, 0.0]]), 0.4)


def test_head_states_without_an_output_get_only_the_floor():
    reading = head_reading(np.array([[0.25, 0.75]]), ("1", "3"), COLOUR, FLOOR)
    assert reading[0] == pytest.approx([0.25 * 0.97 + 0.01, 0.01, 0.75 * 0.97 + 0.01])


def test_race_tables_count_accessions_once_and_never_hold_a_zero():
    train = [photo("A", "Durra", "1"), photo("A", "Durra", "1"), photo("B", "Durra", "2"), photo("C", "Kafir", None)]
    tables = race_tables(train, COLOUR, RACES, FLOOR)
    assert tables[0] == pytest.approx([0.5 * 0.97 + 0.01, 0.5 * 0.97 + 0.01, 0.01])
    assert tables[1] == pytest.approx([1 / 3] * 3)  # no labelled Kafir accession: uniform
    assert (tables > 0).all()


def test_a_misread_trait_does_not_veto_the_true_race():
    train = [photo("A", "Durra", "1"), photo("B", "Kafir", "3")]
    tables = {"colour": race_tables(train, COLOUR, RACES, FLOOR)}
    # A Durra photo read with certainty as state 3, which no Durra accession has.
    reading = {"colour": state_reading(["3"], COLOUR, FLOOR)}
    posterior = posteriors(log_likelihoods(reading, tables, {"colour": np.array([True])}))
    assert posterior[0, 0] > 0
    assert posterior[0].argmax() == 1


def test_an_unread_trait_leaves_the_prior():
    train = [photo("A", "Durra", "1"), photo("B", "Durra", "1"), photo("C", "Kafir", "3")]
    tables = {"colour": race_tables(train, COLOUR, RACES, FLOOR)}
    reading = {"colour": state_reading(["3"], COLOUR, FLOOR)}
    prior = race_log_prior(train, RACES)
    posterior = posteriors(log_likelihoods(reading, tables, {"colour": np.array([False])}), prior)
    assert posterior[0] == pytest.approx([2 / 3, 1 / 3])


def test_accession_rows_are_their_own_states_or_uniform():
    rows, has_state = accession_tables(["A", "B"], {"A": {"colour": "2"}}, COLOUR, FLOOR)
    assert rows[0] == pytest.approx([0.01, 0.98, 0.01])
    assert rows[1] == pytest.approx([1 / 3] * 3)
    assert has_state.tolist() == [True, False]


def test_tied_classes_share_the_top_k_chance():
    scores = np.array([[1.0, 1.0, 1.0, 0.0], [2.0, 1.0, 1.0, 1.0]])
    # Row 0: true class 0 tied with two others -> top-1 chance 1/3, top-3 chance 1.
    # Row 1: true class 1, one better and two tied -> top-1 0, top-2 1/3.
    true_columns = np.array([0, 1])
    assert tie_aware_top_k(scores, true_columns, 1) == pytest.approx((1 / 3 + 0) / 2)
    assert tie_aware_top_k(scores, true_columns, 2) == pytest.approx((2 / 3 + 1 / 3) / 2)
    assert tie_aware_top_k(scores, true_columns, 3) == pytest.approx((1 + 2 / 3) / 2)


def test_ranking_check_finds_races_a_trait_separates():
    from sorghum_model.settings import RaceRuleSearchSettings
    from sorghum_model.trait_ranking import ranking_check

    def labelled(index: int, split: Split) -> TraitPhoto:
        race, state = (("Durra", "1"), ("Kafir", "4"))[index % 2]
        states = {"glumeColour": state, "hundredSeedWeight": "5"}
        return TraitPhoto(f"{split.value}{index}.jpg", f"{split.value}{index}", f"{split.value}-A{index}", "P", split, race, states)

    photos = [labelled(i, split) for split in Split for i in range(20)]
    outputs = {}
    for split in (Split.VALIDATION, Split.TEST):
        in_split = [p for p in photos if p.split is split]
        outputs[f"sha256/{split.value}"] = np.array([p.sha256 for p in in_split])
        # The head reads glume colour right with 0.9 confidence.
        outputs[f"glumeColour/{split.value}"] = np.array(
            [[0.9, 0.1] if p.states["glumeColour"] == "1" else [0.1, 0.9] for p in in_split]
        )
    result = ranking_check(photos, {"glumeColour": ("1", "4")}, outputs, 0.01, 0.8, RaceRuleSearchSettings())
    for variant in ("heads", "oracle", "oracleWithSeedWeight"):
        assert result["variants"][variant]["testTop1"] == pytest.approx(1.0)
        assert result["variants"][variant]["test"]["selectiveAccuracy"] == pytest.approx(1.0)
    # Each accession shares its glume colour with the 29 other accessions of its race over
    # train, validation and test (all in the table), so exact matching is a 1-in-30 guess.
    assert result["variants"]["oracle"]["accessionMatching"]["top1"] == pytest.approx(1 / 30)
