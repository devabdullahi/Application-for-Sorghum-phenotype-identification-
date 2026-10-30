"""Ranking and selection of the core accessions to request (type-eval-v1, T26)."""

import csv
from dataclasses import replace

import pytest

from sorghum_model.core_shortlist import (
    AccessionPassport,
    Exclusion,
    LabelTier,
    accession_availability,
    exclusion_of,
    is_test_eligible,
    label_tier,
    ranked,
    select_core,
    shortlist,
    write_shortlist,
)
from sorghum_model.cultivar_races import AccessionRace
from sorghum_model.grin_accessions import StudyAvailability, StudyRosterRow, parse_study_roster
from sorghum_model.race_crosswalk import CrosswalkRow
from sorghum_model.settings import CoreShortlistSettings


def roster(accession: str, origin: str = "Sudan", availability=StudyAvailability.ORDERABLE, name: str = "") -> StudyRosterRow:
    return StudyRosterRow("1", accession, name, "Sorghum bicolor", origin, availability)


def frontiers(race: str, comparison: str) -> CrosswalkRow:
    return CrosswalkRow(
        source="frontiers-2023-table1", sample_id="SRR1", name="PI1", frontiers_race=race, frontiers_reference="",
        genebank_number="PI 1", identity_status="matched", identity_reason="", grin_accession="PI 1",
        grin_detail_id="1", icrisat_number="IS 9", grin_race=race, grin_race_exclusion="", grin_race_values=race,
        grin_race_studies=1, grin_photographed="no", grin_accession_split="", genesys_race="",
        genesys_provenance="", race_comparison=comparison, comparison_reason="",
    )


def passport(
    accession: str,
    race: str = "Kafir",
    studies: int = 1,
    traits: int = 0,
    origin: str = "Sudan",
    split: str = "",
    orderable: bool = True,
    crosswalk: CrosswalkRow | None = None,
) -> AccessionPassport:
    return AccessionPassport(
        roster=roster(accession, origin),
        orderable=orderable,
        race=AccessionRace(race, None, (race,)),
        race_studies=studies,
        traits_with_states=frozenset(f"trait{index}" for index in range(traits)),
        frontiers=crosswalk,
        grin_accession_split=split,
    )


SMALL = CoreShortlistSettings(development_per_race=2, test_per_race=1, alternates_per_race=1, max_origin_share=1.0)


def test_study_availability_reads_cart_other_lot_and_not_available():
    cells = [
        "<button class='btn-results' onclick='addOne(1,2)'><i class='fa fa-shopping-cart'></i></button>",
        "<span title='other lot'>*Not Available<b></b></span>",
        "Not Available",
        "Historic",
    ]
    rows = "".join(
        f'<tr><td>{index}</td><td>{index}</td><td><a href="accessiondetail.aspx?id={index}">PI {index} </a></td>'
        f"<td>N{index}</td><td><i>Sorghum bicolor</i></td><td> Mali</td><td>{cell}</td><td></td><td>Kafir</td></tr>"
        for index, cell in enumerate(cells)
    )
    page = (
        "<table><tr><th></th><th>ID</th><th>ACCESSION</th><th>NAME</th><th>TAXONOMY</th><th>ORIGIN</th>"
        f"<th>AVAILABILITY</th><th>IMAGE</th><th>VALUE</th></tr>{rows}</table>"
    )
    parsed = parse_study_roster(page)
    assert [row.availability for row in parsed] == [
        StudyAvailability.ORDERABLE,
        StudyAvailability.OTHER_LOT_ORDERABLE,
        StudyAvailability.NOT_AVAILABLE,
        StudyAvailability.NOT_AVAILABLE,
    ]
    assert (parsed[0].accession, parsed[0].origin, parsed[0].name) == ("PI 0", "Mali", "N0")


def test_an_accession_is_orderable_when_any_of_its_lots_is():
    rows = [
        roster("PI 1", availability=StudyAvailability.NOT_AVAILABLE),
        roster("PI 1", availability=StudyAvailability.OTHER_LOT_ORDERABLE),
        roster("PI 2", availability=StudyAvailability.NOT_AVAILABLE),
    ]
    assert accession_availability(rows) == {"PI 1": True, "PI 2": False}


@pytest.mark.parametrize(
    ("studies", "crosswalk", "tier"),
    [
        (1, None, LabelTier.SINGLE),
        (2, None, LabelTier.REPEATED),  # the smallest repeated count
        (1, frontiers("Kafir", "same-race"), LabelTier.CORROBORATED),
    ],
)
def test_label_tier(studies, crosswalk, tier):
    assert label_tier(passport("PI 1", studies=studies, crosswalk=crosswalk)) is tier


def test_a_second_source_that_disagrees_or_no_seed_excludes_the_accession():
    assert exclusion_of(passport("PI 1", crosswalk=frontiers("Durra", "different-race"))) is Exclusion.SECOND_SOURCE_DISAGREES
    assert exclusion_of(passport("PI 1", crosswalk=frontiers("Kafir-durra", "basic-vs-intermediate"))) is (
        Exclusion.SECOND_SOURCE_DISAGREES
    )
    assert exclusion_of(passport("PI 1", orderable=False)) is Exclusion.NO_ORDERABLE_SEED
    assert exclusion_of(passport("PI 1", crosswalk=frontiers("Kafir", "not-compared"))) is None


def test_ranking_puts_label_confidence_before_descriptor_coverage():
    candidates = [
        passport("PI 1", traits=6),
        passport("PI 2", studies=2, traits=1),
        passport("PI 3", crosswalk=frontiers("Kafir", "same-race")),
        passport("PI 4", studies=2, traits=3),
    ]
    order = [p.roster.accession for p in ranked(candidates, max_origin_share=1.0, core_size=4)]
    assert order == ["PI 3", "PI 4", "PI 2", "PI 1"]


def test_one_origin_cannot_fill_the_core_while_others_are_left():
    candidates = [passport(f"PI {index}", traits=5, origin="Sudan") for index in range(4)]
    candidates.append(passport("PI 9", traits=0, origin="Mali"))
    order = ranked(candidates, max_origin_share=0.5, core_size=4)  # at most 2 from one origin first
    assert [p.roster.origin for p in order[:3]] == ["Sudan", "Sudan", "Mali"]


def test_core_keeps_enough_test_eligible_accessions():
    ordered = [
        passport("PI 1", studies=2, split="train"),
        passport("PI 2", studies=2, split="validation"),
        passport("PI 3", studies=2, split="train"),
        passport("PI 4", studies=2, split="test"),  # GRIN test photos only: eligible
        passport("PI 5", studies=2, split=""),
    ]
    settings = replace(SMALL, development_per_race=1, test_per_race=2)
    core = select_core(ordered, settings)
    assert [p.roster.accession for p in core] == ["PI 1", "PI 4", "PI 5"]


def test_shortlist_documents_a_shortfall_instead_of_filling_it(tmp_path):
    passports = [
        passport("PI 1", race="Kafir"),
        passport("PI 2", race="Kafir", orderable=False),
        passport("PI 3", race="Kafir-durra"),  # intermediate: never a candidate
        passport("PI 4", race="Durra"),
        passport("PI 5", race="Durra"),
        passport("PI 6", race="Durra"),
        passport("PI 7", race="Durra"),
    ]
    rows, lines = shortlist(passports, SMALL)
    kafir = [row for row in rows if row.race == "Kafir"]
    assert [(row.accession, row.role) for row in kafir] == [("PI 1", "core")]
    assert [row.role for row in rows if row.race == "Durra"] == ["core", "core", "core", "alternate"]
    summary = "\n".join(lines)
    assert "no-orderable-seed 1" in summary
    assert "core short by 2" in summary and "alternates short by 1" in summary

    path = tmp_path / "shortlist.csv"
    write_shortlist(rows, path)
    with path.open(newline="") as file:
        written = list(csv.DictReader(file))
    assert [row["race"] for row in written] == ["Kafir", "Durra", "Durra", "Durra", "Durra"]
    assert all(row["seed_request_seeds"] == "100" for row in written)


def test_icrisat_number_comes_from_the_crosswalk_or_the_grin_top_name():
    named = replace(passport("PI 1"), roster=roster("PI 1", name="IS 1234"))
    rows, _ = shortlist([named, passport("PI 2", crosswalk=frontiers("Kafir", "same-race"))], SMALL)
    assert {row.accession: row.icrisat_number for row in rows} == {"PI 1": "IS 1234", "PI 2": "IS 9"}


@pytest.mark.parametrize(
    "changes",
    [{"test_per_race": 0}, {"alternates_per_race": -1}, {"max_origin_share": 0.0}, {"seeds_per_request": 0}],
)
def test_settings_refuse_out_of_range_values(changes):
    with pytest.raises(ValueError):
        CoreShortlistSettings(**changes)


def test_origin_cap_counts_countries_not_regions():
    candidates = [passport("PI 1", origin="Transvaal, South Africa"), passport("PI 2", origin="South Africa")]
    candidates.append(passport("PI 3", origin="Zimbabwe"))
    order = ranked(candidates, max_origin_share=0.34, core_size=3)  # one per country first
    assert order[-1].roster.origin.endswith("South Africa") and order[1].roster.origin != order[0].roster.origin


def test_a_single_observation_label_is_never_test_eligible():
    assert not is_test_eligible(passport("PI 1", studies=1, split=""))
    assert is_test_eligible(passport("PI 1", studies=2, split=""))
    assert is_test_eligible(passport("PI 1", crosswalk=frontiers("Kafir", "same-race"), split="test"))
    assert not is_test_eligible(passport("PI 1", studies=2, split="train"))


def test_a_race_without_confirmed_labels_reports_a_test_shortfall():
    rows, lines = shortlist([passport(f"PI {index}") for index in range(4)], SMALL)
    assert len([row for row in rows if row.role == "core"]) == 3
    assert "test-eligible short by 1" in "\n".join(lines)
