"""Accession identity across genebanks, race comparison and the agreement report."""

import zipfile

import pytest

from sorghum_model.cultivar_races import AccessionRace, RaceExclusion
from sorghum_model.frontiers_races import FrontiersSample, genebank_number, read_frontiers_table
from sorghum_model.grin_accessions import (
    detail_url,
    normalized_number,
    parse_accession_detail,
    parse_search_results,
    search_url,
)
from sorghum_model.race_crosswalk import (
    IdentityResolution,
    IdentityStatus,
    RaceComparison,
    basic_parents,
    compare_races,
    crosswalk_report,
    crosswalk_row,
    frontiers_race_group,
    read_crosswalk,
    resolve_genebank_number,
    wilson_interval,
    write_crosswalk,
)


def search_page(*rows: tuple[str, str, str, str]) -> str:
    """A GRIN search result page; each row is (detail id, accession, plant name, taxon)."""
    body = "".join(
        f'<tr><td>{index}</td><td><a href="accessiondetail.aspx?id={detail_id}">{accession}</a></td>'
        f"<td>{name}</td><td><i>{taxon}</i></td></tr>"
        for index, (detail_id, accession, name, taxon) in enumerate(rows)
    )
    return f"<table><tr><th></th><th>ACCESSION</th><th>PLANT NAME</th><th>TAXONOMY</th></tr>{body}</table>"


def detail_page(accession: str, *identifiers: tuple[str, str, str], orderable: bool = True) -> str:
    """A GRIN accession detail page; each identifier is (name, type, group)."""
    entries = "".join(
        f'<div class="row"><div class="col-md-12"><b>{name}</b></div></div>'
        f'<div class="row"><div class="col-md-10">Type: {kind}</div></div>'
        + (f'<div class="row"><div class="col-md-10">Group: {group}</div></div>' if group else "")
        for name, kind, group in identifiers
    )
    cart = "<button onclick='addOneForm(1, \"SD\", 2)'></button>" if orderable else ""
    return (
        f"<h1>Details for: {accession}, <i>Sorghum bicolor</i> (L.) Moench subsp. <i>bicolor</i>, X</h1>"
        f"<table id='available'><tbody><tr><td>Seed</td><td>100 count</td><td>{cart}</td></tr></tbody></table>"
        f'<div class="panel-heading">Accession Names and Identifiers</div><div class="panel-body">{entries}</div>'
        '<div class="panel-heading">Narrative</div>'
    )


def fetcher(pages: dict[str, str]):
    requested: list[str] = []

    def fetch(url: str) -> str:
        requested.append(url)
        return pages[url]

    return fetch, requested


def sample(name: str, race: str) -> FrontiersSample:
    return FrontiersSample("SRR1", name, race, "Valluru et al, 2019", genebank_number(name))


# Frontiers names


@pytest.mark.parametrize(
    ("name", "number"),
    [("IS1233", "IS 1233"), ("PI383856", "PI 383856"), ("NSL55749", "NSL 55749"), ("is 12", "IS 12"), ("SCIV1", "")],
)
def test_genebank_numbers_are_written_as_grin_writes_them(name, number):
    assert genebank_number(name) == number


def test_frontiers_table_is_read_by_sheet_name_under_its_title_row(tmp_path):
    path = tmp_path / "tables.xlsx"
    strings = ["Table 1", "ID", "Name", "SorghumRace", "Reference", "IS1233", "Bicolor", "Jensen et al, 2019"]
    shared = "".join(f"<si><t>{text}</t></si>" for text in strings)

    def cell(reference: str, index: int) -> str:
        return f'<c r="{reference}" t="s"><v>{index}</v></c>'

    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        f'<row r="1">{cell("A1", 0)}</row>'
        f'<row r="2">{cell("A2", 1)}{cell("B2", 2)}{cell("C2", 3)}{cell("L2", 4)}</row>'
        f'<row r="3">{cell("A3", 5)}{cell("B3", 5)}{cell("C3", 6)}{cell("L3", 7)}</row>'
        "</sheetData></worksheet>"
    )
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relationship = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w") as workbook:
        workbook.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{main}" xmlns:r="{relationship}"><sheets>'
            '<sheet name="Other" sheetId="1" r:id="rId1"/><sheet name="Table1" sheetId="2" r:id="rId2"/>'
            "</sheets></workbook>",
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>',
        )
        workbook.writestr("xl/sharedStrings.xml", f'<sst xmlns="{main}">{shared}</sst>')
        workbook.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{main}"><sheetData/></worksheet>')
        workbook.writestr("xl/worksheets/sheet2.xml", sheet)

    assert read_frontiers_table(path) == [FrontiersSample("IS1233", "IS1233", "Bicolor", "Jensen et al, 2019", "IS 1233")]


# GRIN pages


def test_search_results_keep_accession_detail_id_and_taxon():
    hits = parse_search_results(
        search_page(("10", "PI 562744", "'KAOLIANG'", "Sorghum bicolor"), ("11", "W6 1", "x", "Lens culinaris"))
    )
    assert [(hit.detail_id, hit.accession, hit.is_sorghum) for hit in hits] == [
        ("10", "PI 562744", True),
        ("11", "W6 1", False),
    ]


def test_detail_page_gives_identifiers_icrisat_number_and_seed():
    detail = parse_accession_detail(
        detail_page("PI 682397", ("IS 8134", "Institute identifier", "IS"), ("NSL 55749", "Site identifier", "NSSL"))
    )
    assert detail.accession == "PI 682397"
    assert detail.taxon == "Sorghum bicolor (L.) Moench subsp. bicolor"
    assert detail.icrisat_numbers == ("IS 8134",)
    assert detail.lists("NSL55749") and detail.lists("pi 682397") and not detail.lists("IS 813")
    assert detail.has_orderable_seed


def test_a_seed_lot_without_a_cart_button_is_not_orderable():
    assert not parse_accession_detail(detail_page("PI 1", orderable=False)).has_orderable_seed


def test_numbers_compare_without_case_or_spacing():
    assert normalized_number(" is  1233") == normalized_number("IS1233") == "IS1233"


# Identity


def test_a_number_listed_by_one_sorghum_accession_is_matched():
    fetch, requested = fetcher(
        {
            search_url("IS 1233"): search_page(
                ("1", "PI 474665", "IS 28038", "Sorghum bicolor"),
                ("2", "PI 562744", "'KAOLIANG'", "Sorghum bicolor"),
                ("3", "W6 61936", "OR020-1233", "Erigeron speciosus"),
            ),
            detail_url("1"): detail_page("PI 474665", ("IS 28038", "Institute identifier", "IS")),
            detail_url("2"): detail_page("PI 562744", ("IS 1233", "Institute identifier", "IS")),
        }
    )
    resolution = resolve_genebank_number("IS 1233", fetch, max_candidates=10)
    assert resolution.status is IdentityStatus.MATCHED
    assert resolution.detail.accession == "PI 562744" and resolution.detail_id == "2"
    assert detail_url("3") not in requested  # not sorghum, never opened


def test_a_number_listed_by_two_accessions_is_ambiguous():
    fetch, _ = fetcher(
        {
            search_url("IS 5"): search_page(("1", "PI 1", "", "Sorghum bicolor"), ("2", "PI 2", "", "Sorghum bicolor")),
            detail_url("1"): detail_page("PI 1", ("IS 5", "Institute identifier", "IS")),
            detail_url("2"): detail_page("PI 2", ("IS 5", "Institute identifier", "IS")),
        }
    )
    resolution = resolve_genebank_number("IS 5", fetch, max_candidates=10)
    assert resolution.status is IdentityStatus.AMBIGUOUS and resolution.detail is None
    assert "PI 1, PI 2" in resolution.reason


def test_a_number_no_accession_lists_fails_and_a_sample_name_fails_without_a_search():
    fetch, requested = fetcher(
        {
            search_url("IS 7"): search_page(("1", "PI 1", "IS 77", "Sorghum bicolor")),
            detail_url("1"): detail_page("PI 1", ("IS 77", "Institute identifier", "IS")),
        }
    )
    assert resolve_genebank_number("IS 7", fetch, max_candidates=10).status is IdentityStatus.FAILED
    assert resolve_genebank_number("", fetch, max_candidates=10).status is IdentityStatus.FAILED
    assert len(requested) == 2


def test_only_the_first_candidates_are_opened():
    fetch, requested = fetcher(
        {
            search_url("IS 9"): search_page(("1", "PI 1", "", "Sorghum bicolor"), ("2", "PI 2", "", "Sorghum bicolor")),
            detail_url("1"): detail_page("PI 1"),
        }
    )
    resolution = resolve_genebank_number("IS 9", fetch, max_candidates=1)
    assert resolution.status is IdentityStatus.FAILED and "1 of 2" in resolution.reason
    assert detail_url("2") not in requested


# Race comparison


@pytest.mark.parametrize(
    ("first", "second", "comparison"),
    [
        ("Caudatum", "caudatum", RaceComparison.SAME),
        ("Bicolor-caudatum", "Caudatum-bicolor", RaceComparison.SAME),  # GRIN writes parents the other way round
        ("Caudatum", "Durra-caudatum", RaceComparison.BASIC_VS_INTERMEDIATE),
        ("Caudatum-durra", "Durra-bicolor", RaceComparison.INTERMEDIATES_SHARE_A_PARENT),
        ("Guinea", "Durra", RaceComparison.DIFFERENT),
        ("Guinea", "Unknown", RaceComparison.NOT_COMPARED),
        ("", "Durra", RaceComparison.NOT_COMPARED),
    ],
)
def test_races_are_compared_by_their_basic_parents(first, second, comparison):
    assert compare_races(first, second) is comparison


def test_only_one_or_two_basic_races_make_a_race_name():
    assert basic_parents("Durra") == {"Durra"}
    assert basic_parents("Bicolor-guinea-durra") == frozenset()
    assert basic_parents("Margaritiferum") == frozenset()
    assert frontiers_race_group("Guinea-kafir") == "Intermediate"
    assert frontiers_race_group("Kafir") == "Kafir"


def matched(accession: str) -> IdentityResolution:
    detail = parse_accession_detail(detail_page(accession, ("IS 1", "Institute identifier", "IS")))
    return IdentityResolution(IdentityStatus.MATCHED, "listed", detail, "9")


def test_a_row_keeps_both_labels_and_the_reason_for_a_mismatch():
    row = crosswalk_row(
        sample("PI383856", "Caudatum"),
        matched("PI 383856"),
        AccessionRace("Durra-caudatum", None, ("Durra-caudatum",)),
        grin_race_studies=2,
        accession_split="test",
    )
    assert (row.frontiers_race, row.grin_race, row.icrisat_number) == ("Caudatum", "Durra-caudatum", "IS 1")
    assert row.race_comparison == RaceComparison.BASIC_VS_INTERMEDIATE.value
    assert row.comparison_reason == "basic-vs-intermediate: Frontiers Caudatum, GRIN Durra-caudatum"
    assert (row.grin_photographed, row.grin_accession_split) == ("yes", "test")
    assert row.genesys_race == "" and "401" in row.genesys_provenance


def test_an_excluded_grin_label_is_not_compared_and_says_why():
    row = crosswalk_row(
        sample("PI1", "Durra"),
        matched("PI 1"),
        AccessionRace("", RaceExclusion.CONFLICTING_OBSERVATIONS, ("Durra", "Durra-bicolor")),
        grin_race_studies=2,
        accession_split="",
    )
    assert row.race_comparison == RaceComparison.NOT_COMPARED.value
    assert row.comparison_reason == "GRIN has no scored race (conflicting-observations: Durra + Durra-bicolor)"
    assert row.grin_photographed == "no"


def test_a_failed_identity_is_not_compared():
    failed = IdentityResolution(IdentityStatus.FAILED, "name is not a genebank number (PI, NSL or IS)")
    row = crosswalk_row(sample("SCIV1", "Bicolor"), failed, None, 0, "")
    assert (row.identity_status, row.race_comparison, row.grin_accession) == ("failed", "not-compared", "")


def test_crosswalk_round_trips_and_reports_agreement_with_denominators(tmp_path):
    rows = [
        crosswalk_row(sample("PI1", "Durra"), matched("PI 1"), AccessionRace("Durra", None, ("Durra",)), 1, ""),
        crosswalk_row(sample("PI2", "Durra"), matched("PI 2"), AccessionRace("Caudatum", None, ("Caudatum",)), 1, ""),
        crosswalk_row(sample("SCIV1", "Bicolor"), IdentityResolution(IdentityStatus.FAILED, "x"), None, 0, ""),
    ]
    path = tmp_path / "crosswalk.csv"
    write_crosswalk(rows, path)
    assert sorted(read_crosswalk(path), key=lambda r: r.name) == sorted(rows, key=lambda r: r.name)

    report = "\n".join(crosswalk_report(rows))
    durra_line = next(line for line in report.splitlines() if line.strip().startswith("Durra"))
    assert " 1/2 0.50 " in durra_line
    assert "Race mismatches (1)" in report
    assert "different-race: Frontiers Durra, GRIN Caudatum" in report


# Interval


def test_wilson_interval_stays_inside_zero_and_one():
    low, high = wilson_interval(9, 9)
    assert high == 1.0 and 0.65 < low < 0.71  # 9/9: about [0.70, 1.00]
    low, high = wilson_interval(9, 12)
    assert low == pytest.approx(0.4677, abs=1e-3) and high == pytest.approx(0.9111, abs=1e-3)
    assert wilson_interval(0, 0) == (0.0, 1.0)
