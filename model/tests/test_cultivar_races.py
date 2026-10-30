"""Race labels of accessions and the reasons an accession is not scored."""

import pytest

from sorghum_model.cultivar_races import AccessionRace, RaceExclusion, race_labels
from sorghum_model.grin_descriptors import RACE, DescriptorObservation


def race_observation(accession: str, value: str, study: str = "SORGHUM.STC2003") -> DescriptorObservation:
    return DescriptorObservation(
        accession=accession,
        descriptor=RACE.code,
        grin_value=value,
        grin_code=RACE.grin_codes.get(value, ""),
        trait_id="",
        ibpgr_state="",
        study=study,
        source_url="https://example.org",
    )


def label_of(*values: str) -> AccessionRace:
    observations = [race_observation("PI 1", value, study=f"S{index}") for index, value in enumerate(values)]
    return race_labels({"PI 1"}, observations)["PI 1"]


@pytest.mark.parametrize(
    ("value", "expected_race"),
    [
        ("Bicolor", "Bicolor"),  # code 01, the first scored race
        ("Kafir-durra", "Kafir-durra"),  # code 15, the last scored race
        ("durra-BICOLOR", "Durra-bicolor"),  # GRIN's table spelling is written
    ],
)
def test_the_fifteen_races_are_scored(value, expected_race):
    label = label_of(value)
    assert label.race == expected_race
    assert label.exclusion is None


@pytest.mark.parametrize(
    ("value", "exclusion"),
    [
        ("Shattercane", RaceExclusion.NOT_A_RACE),  # code 16, just past the scored codes
        ("Unknown", RaceExclusion.RACE_UNKNOWN),  # code 17
        ("Mixed", RaceExclusion.NOT_A_RACE),
        ("Breeding line", RaceExclusion.NOT_A_RACE),
        ("Margaritiferum", RaceExclusion.UNMAPPED_VALUE),  # not in GRIN's race table
    ],
)
def test_values_that_are_not_one_race_are_excluded(value, exclusion):
    label = label_of(value)
    assert label.race == ""
    assert label.exclusion is exclusion
    assert label.observed_values == (value,)


def test_an_accession_without_a_race_observation_is_excluded():
    other_descriptor = DescriptorObservation("PI 1", "GLUMECOLOR", "Red", "2", "glumeColour", "4", "S", "u")
    label = race_labels({"PI 1"}, [other_descriptor])["PI 1"]
    assert label.exclusion is RaceExclusion.NO_RACE_OBSERVATION
    assert label.observed_values == ()


def test_one_race_in_several_plantings_is_scored():
    assert label_of("Durra", "Durra").race == "Durra"
    # GRIN capitalises one value differently across studies; that is not a disagreement.
    assert label_of("Durra-bicolor", "Durra-Bicolor").race == "Durra-bicolor"


def test_plantings_that_disagree_are_excluded_rather_than_voted():
    label = label_of("Durra", "Durra", "Durra-bicolor")
    assert label.exclusion is RaceExclusion.CONFLICTING_OBSERVATIONS
    assert label.observed_values == ("Durra", "Durra-bicolor")
    # A race plus "Mixed" is a disagreement too.
    assert label_of("Caudatum", "Mixed").exclusion is RaceExclusion.CONFLICTING_OBSERVATIONS


def test_every_requested_accession_gets_a_label_and_others_are_ignored():
    observations = [race_observation("PI 1", "Guinea"), race_observation("PI 9", "Kafir")]
    labels = race_labels({"PI 1", "PI 2"}, observations)
    assert labels.keys() == {"PI 1", "PI 2"}
    assert labels["PI 2"].exclusion is RaceExclusion.NO_RACE_OBSERVATION


def test_a_label_has_a_race_or_an_exclusion_but_not_both():
    with pytest.raises(ValueError):
        AccessionRace("Durra", RaceExclusion.RACE_UNKNOWN, ("Durra",))
    with pytest.raises(ValueError):
        AccessionRace("", None, ())
