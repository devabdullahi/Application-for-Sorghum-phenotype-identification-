"""GRIN descriptor value -> IBPGR state mapping, and parsing of descriptor and study pages."""

import pytest

from sorghum_model.grin_descriptors import (
    COMBINED_PANICLE_DESCRIPTOR,
    DESCRIPTORS,
    GLUME_COLOUR,
    GRAIN_COLOUR,
    MIDRIB_COLOUR,
    PANICLE_COMPACTNESS,
    PANICLE_SHAPE,
    PLANT_PIGMENTATION,
    RACE,
    SEED_WEIGHT,
    DescriptorObservation,
    combine_panicle_observations,
    coverage_report,
    hundred_seed_weight_state,
    ibpgr_state_for,
    parse_descriptor_studies,
    parse_observations,
)

# IBPGR state codes of each catalogue trait (TraitCatalogue.kt); every mapped state must be one.
CATALOGUE_STATES = {
    "glumeColour": {"1", "2", "3", "4", "5", "6", "7", "8"},
    "grainColour": {"1", "2", "3", "4", "5", "6"},
    "panicleCompactnessAndShape": {str(code) for code in range(1, 14)},
    "plantPigmentation": {"1", "2"},
    "midribColour": {"1", "2", "3", "4", "5", "6"},
}


@pytest.mark.parametrize("descriptor", [d for d in DESCRIPTORS if d.ibpgr_state_of_grin_code])
def test_every_mapping_uses_real_grin_codes_and_catalogue_states(descriptor):
    assert set(descriptor.ibpgr_state_of_grin_code) <= set(descriptor.grin_codes.values())
    assert set(descriptor.ibpgr_state_of_grin_code.values()) <= CATALOGUE_STATES[descriptor.trait_id]


@pytest.mark.parametrize(
    "descriptor, value, expected",
    [
        (GLUME_COLOUR, "Purple", ("1", "5")),  # GRIN 1 is IBPGR 5: codes differ between lists
        (GLUME_COLOUR, "Straw", ("7", "1")),
        (GLUME_COLOUR, "Tan", ("3", "")),  # no IBPGR tan glume state
        (GLUME_COLOUR, "Mixed", ("8", "")),
        (GRAIN_COLOUR, "Red", ("2", "3")),
        (GRAIN_COLOUR, "yellow", ("3", "2")),  # labels compare case-insensitively
        (GRAIN_COLOUR, "Purple", ("7", "6")),
        (PLANT_PIGMENTATION, "Purple-red", ("4", "1")),
        (PLANT_PIGMENTATION, "Tan", ("3", "2")),
        (PLANT_PIGMENTATION, "Tan-red", ("6", "")),
        (MIDRIB_COLOUR, "Colorless", ("1", "1")),
        (MIDRIB_COLOUR, "Mixed", ("5", "")),
        (RACE, "Durra-caudatum", ("14", "")),
        (RACE, "A new race", ("", "")),  # unknown label: no code, no state
    ],
)
def test_ibpgr_state_for(descriptor, value, expected):
    assert ibpgr_state_for(descriptor, value) == expected


@pytest.mark.parametrize(
    "grams, expected",
    [("1.99", "3"), ("2.0", "5"), ("2.99", "5"), ("3.0", "7"), ("5.4", "7"), ("0", ""), ("n/a", "")],
)
def test_hundred_seed_weight_bins_match_the_catalogue_edges(grams, expected):
    assert hundred_seed_weight_state(grams) == expected
    assert ibpgr_state_for(SEED_WEIGHT, grams) == (grams, expected)


def observation(accession, descriptor, value, study="S1"):
    grin_code, state = ibpgr_state_for(descriptor, value)
    return DescriptorObservation(accession, descriptor.code, value, grin_code, descriptor.trait_id, state, study, "u")


@pytest.mark.parametrize(
    "compactness, shape, expected",
    [
        ("Compact", "Elliptical", "9"),
        ("Compact", "Oval", "10"),
        ("Semi-compact", "Elliptical", "8"),
        ("Loose", "Broomcorn", "12"),
        ("Loose", "Lax", "1"),
        ("Semi-loose", "Elliptical", ""),  # erect or drooping branches unknown
    ],
)
def test_combined_panicle_state(compactness, shape, expected):
    rows = [observation("PI 1", PANICLE_COMPACTNESS, compactness), observation("PI 1", PANICLE_SHAPE, shape)]
    (combined,) = combine_panicle_observations(rows)
    assert combined.descriptor == COMBINED_PANICLE_DESCRIPTOR
    assert combined.ibpgr_state == expected


def test_combined_panicle_needs_both_descriptors_in_the_same_study():
    rows = [
        observation("PI 1", PANICLE_COMPACTNESS, "Compact", study="S1"),
        observation("PI 1", PANICLE_SHAPE, "Oval", study="S2"),
    ]
    assert combine_panicle_observations(rows) == []


def test_parse_descriptor_studies():
    page = (
        '<td><a href="method.aspx?id=21001">S9.SORGHUM</a></td>'
        '<td><a href="methodaccession.aspx?id1=69065&id2=21001 ">3347 Accessions</a></td>'
        '<td><a href="method.aspx?id=491155">SORGHUM.ETHIOPIAN.1998</a></td>'
        '<td><a href="methodaccession.aspx?id1=69065&amp;id2=491155">2148 Accessions</a></td>'
    )
    assert parse_descriptor_studies(page, 69065) == [
        ("S9.SORGHUM", "https://npgsweb.ars-grin.gov/gringlobal/methodaccession.aspx?id1=69065&id2=21001"),
        ("SORGHUM.ETHIOPIAN.1998", "https://npgsweb.ars-grin.gov/gringlobal/methodaccession.aspx?id1=69065&id2=491155"),
    ]


STUDY_PAGE = """<table><thead><tr><th></th><th>ID</th><th>ACCESSION</th><th>NAME</th><th>VALUE</th></tr></thead>
<tbody><tr><td>0</td><td>1</td><td><a>PI 533903 </a></td><td>x</td><td>Bicolor</td></tr>
<tr><td>1</td><td>2</td><td><a>PI 999 </a></td><td>y</td><td>Durra</td></tr></tbody></table>"""


def test_parse_observations_keeps_only_requested_accessions():
    (row,) = parse_observations(STUDY_PAGE, RACE, "S9.SORGHUM", "u", {"PI 533903"})
    assert (row.accession, row.grin_value, row.grin_code, row.study) == ("PI 533903", "Bicolor", "01", "S9.SORGHUM")


def test_coverage_report_counts_accessions_and_majority_race():
    rows = [
        observation("PI 1", RACE, "Durra", "S1"),
        observation("PI 1", RACE, "Durra", "S2"),
        observation("PI 1", RACE, "Caudatum", "S3"),
        observation("PI 2", GLUME_COLOUR, "Tan"),
    ]
    report = "\n".join(coverage_report(rows, photographed={"PI 1", "PI 2"}, downloaded={"PI 1"}))
    assert "Durra                1" in report
    assert "1 with conflicting plantings" in report
