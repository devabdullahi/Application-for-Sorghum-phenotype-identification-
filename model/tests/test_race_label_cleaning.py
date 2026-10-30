"""Confirmed basic-race training labels, exclusion reasons and the fallback (T32, #62)."""

import pytest

from sorghum_model.core_shortlist import LabelTier
from sorghum_model.grin_descriptors import RACE, DescriptorObservation
from sorghum_model.race_crosswalk import CrosswalkRow
from sorghum_model.race_label_cleaning import (
    TrainingLabelExclusion,
    clean_basic_race_labels,
    cleaning_report,
    read_training_labels,
    short_races,
    strict_label,
    training_weight,
    write_training_labels,
)
from sorghum_model.settings import RaceLabelCleaningSettings

SETTINGS = RaceLabelCleaningSettings()


def frontiers(accession: str, comparison: str, race: str = "Caudatum") -> CrosswalkRow:
    return CrosswalkRow(
        source="frontiers-2023-table1", sample_id="S1", name=accession, frontiers_race=race, frontiers_reference="",
        genebank_number=accession, identity_status="matched", identity_reason="", grin_accession=accession,
        grin_detail_id="1", icrisat_number="", grin_race=race, grin_race_exclusion="", grin_race_values=race,
        grin_race_studies=1, grin_photographed="yes", grin_accession_split="train", genesys_race="",
        genesys_provenance="", race_comparison=comparison, comparison_reason="",
    )


def race_observation(accession: str, value: str, study: str) -> DescriptorObservation:
    return DescriptorObservation(accession, RACE.code, value, "", "", "", study, "")


def split_row(accession: str, split: str, race: str = "", exclusion: str = "") -> dict[str, str]:
    return {"cultivar_label": accession, "accession_split": split, "race": race, "race_exclusion": exclusion}


# strict_label: one reason per accession


def test_two_agreeing_grin_plantings_confirm_a_label():
    assert strict_label("Durra", "", 2, None) == (LabelTier.REPEATED, None)


def test_one_grin_observation_is_excluded_as_single_observation():
    assert strict_label("Durra", "", 1, None) == (LabelTier.SINGLE, TrainingLabelExclusion.SINGLE_OBSERVATION)


def test_frontiers_naming_the_same_race_confirms_a_single_observation():
    assert strict_label("Caudatum", "", 1, frontiers("PI 1", "same-race")) == (LabelTier.CORROBORATED, None)


@pytest.mark.parametrize("comparison", ["basic-vs-intermediate", "different-race", "intermediates-share-a-parent"])
def test_frontiers_disagreeing_excludes_even_a_repeated_label(comparison):
    tier, exclusion = strict_label("Caudatum", "", 2, frontiers("PI 1", comparison))
    assert tier is LabelTier.REPEATED
    assert exclusion is TrainingLabelExclusion.SECOND_SOURCE_DISAGREES


def test_frontiers_without_a_comparison_leaves_the_grin_label_alone():
    assert strict_label("Durra", "", 1, frontiers("PI 1", "not-compared"))[1] is TrainingLabelExclusion.SINGLE_OBSERVATION


def test_intermediates_conflicts_and_missing_races_are_not_basic_race_labels():
    assert strict_label("Durra-bicolor", "", 3, None) == (None, TrainingLabelExclusion.INTERMEDIATE_RACE)
    assert strict_label("", "conflicting-observations", 2, None) == (
        None, TrainingLabelExclusion.CONFLICTING_OBSERVATIONS,
    )
    assert strict_label("", "no-race-observation", 0, None) == (None, TrainingLabelExclusion.NO_SCORED_RACE)
    assert strict_label("", "not-a-race", 1, None) == (None, TrainingLabelExclusion.NO_SCORED_RACE)


# short_races: the fallback threshold, at, below and above it


def test_a_race_at_the_minimum_is_not_short_and_one_below_is():
    settings = RaceLabelCleaningSettings(min_confirmed_train_accessions_per_race=20)
    counts = {"Bicolor": 19, "Caudatum": 20, "Durra": 21, "Guinea": 20, "Kafir": 20}
    assert short_races(counts, settings) == ("Bicolor",)


def test_a_race_with_no_confirmed_accession_is_short():
    counts = {"Bicolor": 30, "Caudatum": 30, "Durra": 30, "Guinea": 30}
    assert short_races(counts, SETTINGS) == ("Kafir",)


# training_weight


def test_weights_with_and_without_the_fallback():
    single = TrainingLabelExclusion.SINGLE_OBSERVATION
    assert training_weight(None, uses_fallback=False, settings=SETTINGS) == 1.0
    assert training_weight(single, uses_fallback=False, settings=SETTINGS) == 0.0
    assert training_weight(single, uses_fallback=True, settings=SETTINGS) == SETTINGS.single_observation_weight
    for never_trained in (
        TrainingLabelExclusion.SECOND_SOURCE_DISAGREES,
        TrainingLabelExclusion.CONFLICTING_OBSERVATIONS,
        TrainingLabelExclusion.INTERMEDIATE_RACE,
        TrainingLabelExclusion.NO_SCORED_RACE,
    ):
        assert training_weight(never_trained, uses_fallback=True, settings=SETTINGS) == 0.0


@pytest.mark.parametrize("weight", [0.0, -0.1, 1.01])
def test_settings_refuse_a_weight_outside_zero_to_one(weight):
    with pytest.raises(ValueError):
        RaceLabelCleaningSettings(single_observation_weight=weight)


def test_settings_accept_the_weight_range_ends_and_refuse_a_zero_minimum():
    RaceLabelCleaningSettings(single_observation_weight=1.0)
    RaceLabelCleaningSettings(single_observation_weight=0.01, min_confirmed_train_accessions_per_race=1)
    with pytest.raises(ValueError):
        RaceLabelCleaningSettings(min_confirmed_train_accessions_per_race=0)


# clean_basic_race_labels: the whole manifest


def _every_race_confirmed(count: int) -> tuple[list[dict[str, str]], list[DescriptorObservation]]:
    rows, observations = [], []
    for race in ("Bicolor", "Caudatum", "Durra", "Guinea", "Kafir"):
        for index in range(count):
            accession = f"PI {race}{index}"
            rows.append(split_row(accession, "train", race))
            observations += [race_observation(accession, race, "S1"), race_observation(accession, race, "S2")]
    return rows, observations


def test_with_every_race_confirmed_singles_are_not_trained_on():
    settings = RaceLabelCleaningSettings(min_confirmed_train_accessions_per_race=2)
    rows, observations = _every_race_confirmed(2)
    rows.append(split_row("PI single", "train", "Kafir"))
    observations.append(race_observation("PI single", "Kafir", "S1"))
    cleaned = clean_basic_race_labels(rows, observations, [], settings)
    assert not cleaned.uses_fallback
    single = next(r for r in cleaned.rows if r.accession == "PI single")
    assert single.exclusion == "single-observation"
    assert single.training_weight == 0.0
    assert single.kept_by_fallback == "no"


def test_a_short_race_turns_on_the_fallback_for_every_race():
    settings = RaceLabelCleaningSettings(min_confirmed_train_accessions_per_race=3)
    rows, observations = _every_race_confirmed(3)
    # Kafir loses one confirmation and so falls to 2 confirmed accessions, below 3.
    observations = [o for o in observations if not (o.accession == "PI Kafir0" and o.study == "S2")]
    rows.append(split_row("PI caudatum-single", "train", "Caudatum"))
    observations.append(race_observation("PI caudatum-single", "Caudatum", "S1"))
    cleaned = clean_basic_race_labels(rows, observations, [], settings)

    assert cleaned.short_races == ("Kafir",)
    by_accession = {r.accession: r for r in cleaned.rows}
    # The single-observation label of a race that is not short is weighted too.
    for accession in ("PI Kafir0", "PI caudatum-single"):
        assert by_accession[accession].training_weight == settings.single_observation_weight
        assert by_accession[accession].kept_by_fallback == "yes"
    assert by_accession["PI Kafir1"].training_weight == 1.0


def test_test_accessions_are_never_read_and_validation_is_never_weighted():
    rows = [
        split_row("PI train", "train", "Durra"),
        split_row("PI val", "validation", "Durra"),
        split_row("PI test", "test", "Durra"),
    ]
    observations = [race_observation(a, "Durra", s) for a in ("PI train", "PI val", "PI test") for s in ("S1", "S2")]
    cleaned = clean_basic_race_labels(rows, observations, [], SETTINGS)
    assert [r.accession for r in cleaned.rows] == ["PI train", "PI val"]
    assert cleaned.test_accessions_skipped == 1
    validation = cleaned.rows[1]
    assert validation.is_confirmed and validation.training_weight == 0.0


def test_photos_are_counted_per_accession_and_two_splits_are_refused():
    rows = [split_row("PI 1", "train", "Durra"), split_row("PI 1", "train", "Durra")]
    cleaned = clean_basic_race_labels(rows, [race_observation("PI 1", "Durra", "S1")], [], SETTINGS)
    assert cleaned.rows[0].photos == 2
    with pytest.raises(ValueError, match="two accession splits"):
        clean_basic_race_labels(rows + [split_row("PI 1", "validation", "Durra")], [], [], SETTINGS)


def test_frontiers_rows_are_carried_into_the_manifest():
    rows = [split_row("PI 1", "train", "Caudatum"), split_row("PI 2", "train", "Caudatum")]
    observations = [race_observation("PI 1", "Caudatum", "S1"), race_observation("PI 2", "Caudatum", "S1")]
    crosswalk = [frontiers("PI 1", "same-race"), frontiers("PI 2", "basic-vs-intermediate", "Caudatum-guinea")]
    by_accession = {r.accession: r for r in clean_basic_race_labels(rows, observations, crosswalk, SETTINGS).rows}
    assert by_accession["PI 1"].label_tier == "corroborated" and by_accession["PI 1"].is_confirmed
    assert by_accession["PI 2"].exclusion == "second-source-disagrees"
    assert by_accession["PI 2"].frontiers_race == "Caudatum-guinea"
    assert by_accession["PI 2"].training_weight == 0.0


def test_manifest_round_trips_and_the_report_names_the_fallback(tmp_path):
    rows, observations = _every_race_confirmed(1)
    cleaned = clean_basic_race_labels(rows, observations, [], SETTINGS)
    path = tmp_path / "labels.csv"
    write_training_labels(cleaned.rows, path)
    assert read_training_labels(path) == list(cleaned.rows)
    report = "\n".join(cleaning_report(cleaned, SETTINGS))
    assert "Fallback ON" in report
    assert "test accessions not read: 0" in report
