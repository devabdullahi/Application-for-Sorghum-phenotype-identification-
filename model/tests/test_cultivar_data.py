"""GRIN study-page parsing and the cultivar manifest's grouped splits."""

from collections import Counter

import pytest

from sorghum_model.cultivar_manifest import (
    CultivarImageRecord,
    assign_planting_splits,
    drop_repeated_rows,
    find_accession_split_leaks,
    read_cultivar_manifest,
    read_cultivar_split,
    write_cultivar_manifest,
    write_cultivar_split,
)
from sorghum_model.cultivar_races import AccessionRace, RaceExclusion
from sorghum_model.grin import parse_study_page
from sorghum_model.splits import Split

# Two rows cut from a real study page (SORGHUM.IMAGE.STC.2002), plus one row without an image.
STUDY_PAGE = """
<table id='searchtable'><thead><tr><th><span></span></th><th>ID</th><th>ACCESSION</th>
<th>NAME</th><th>TAXONOMY</th><th>ORIGIN</th><th>AVAILABILITY</th><th>IMAGE</th><th>VALUE</th>
<th>OBSERVATIONS</th><th>NOTE</th><th>INVENTORY</th></tr></thead><tbody>
<tr><td>0</td><td>1006814</td><td><a href="accessiondetail.aspx?id=1006814">PI 704184 </a></td>
<td>88-07085</td><td><a href='t'><i>Sorghum bicolor</i> (L.) Moench subsp. <i>bicolor</i> </a></td>
<td>Andhra Pradesh, India</td><td><button>cart</button></td>
<td><a href="ImgDisplay.aspx?id=1006814"><img src="/gringlobal/uploads/images/npgs/s9/sorghum/stc2002/GRIF512.jpg" alt="PANICLE"></a></td>
<td>Image of Seed/Panicle</td><td>0</td>
<td><a href="/npgs/images/s9/sorghum/stc2002/GRIF512.jpg"><IMG src="http://sun.ars-grin.gov/perl/npgs/thumb.pl?file=x.jpg"></a></td>
<td>PI 704184 **</td></tr>
<tr><td>1</td><td>1019942</td><td><a href="accessiondetail.aspx?id=1019942">PI 2363 </a></td>
<td>161</td><td><i>Sorghum bicolor</i></td><td>District of Columbia, United States</td>
<td>Not Available</td><td></td><td>Image of Seed/Panicle</td><td>0</td><td></td><td>PI 2363 **</td></tr>
</tbody></table>
"""


def test_parse_study_page_reads_labels_and_image_path():
    images = parse_study_page(STUDY_PAGE)

    assert len(images) == 1  # the row without an image is skipped
    image = images[0]
    assert image.accession_id == "1006814"
    assert image.accession_number == "PI 704184"
    assert image.accession_name == "88-07085"
    assert image.taxon == "Sorghum bicolor (L.) Moench subsp. bicolor"
    assert image.origin == "Andhra Pradesh, India"
    # The label comes from the ACCESSION column, not the file name (GRIF512 was renamed).
    assert image.image_path == "/gringlobal/uploads/images/npgs/s9/sorghum/stc2002/GRIF512.jpg"


def test_parse_study_page_refuses_a_changed_layout():
    with pytest.raises(ValueError, match="layout changed"):
        parse_study_page("<table><tr><th>ID</th><th>ACCESSION</th></tr></table>")


def make_cultivar_record(accession: str, planting: str, **overrides) -> CultivarImageRecord:
    fields = {
        "image_path": f"grin/{planting}/{accession}.jpg",
        "cultivar_label": accession,
        "accession_name": "",
        "taxon": "Sorghum bicolor",
        "origin": "",
        "source": "grin",
        "source_id": f"{planting}/{accession}",
        "planting_id": planting,
        "license": "us-gov-public-domain",
        "attribution": "USDA-ARS GRIN-Global",
        "source_url": "https://example.org/x.jpg",
        "sha256": f"{hash((accession, planting)) & (2**256 - 1):064x}",
    }
    fields.update(overrides)
    return CultivarImageRecord(**fields)


def test_planting_split_holds_out_one_planting_per_accession():
    records = [
        make_cultivar_record("PI 1", "A"),
        make_cultivar_record("PI 2", "A"),
        make_cultivar_record("PI 2", "B"),
        make_cultivar_record("PI 3", "A"),
        make_cultivar_record("PI 3", "B"),
        make_cultivar_record("PI 3", "C"),
    ]
    splits = assign_planting_splits(records, "salt")

    def splits_of(accession):
        return Counter(split for (_, source_id), split in splits.items() if source_id.endswith(f"/{accession}"))

    assert splits_of("PI 1") == Counter({Split.TRAIN: 1})  # one planting: cannot be tested
    assert splits_of("PI 2") == Counter({Split.TEST: 1, Split.TRAIN: 1})
    assert splits_of("PI 3") == Counter({Split.TEST: 1, Split.VALIDATION: 1, Split.TRAIN: 1})


def test_planting_split_is_stable_when_other_accessions_are_added():
    base = [make_cultivar_record("PI 2", "A"), make_cultivar_record("PI 2", "B")]
    grown = base + [make_cultivar_record("PI 9", "A"), make_cultivar_record("PI 9", "C")]
    before = assign_planting_splits(base, "salt")
    after = assign_planting_splits(grown, "salt")
    assert all(after[key] == split for key, split in before.items())


def races_for(records: list[CultivarImageRecord]) -> dict[str, AccessionRace]:
    return {record.cultivar_label: AccessionRace("Durra", None, ("Durra",)) for record in records}


def test_accession_split_keeps_every_photo_of_an_accession_together(tmp_path):
    records = [make_cultivar_record(f"PI {i}", planting) for i in range(50) for planting in ("A", "B")]
    out = tmp_path / "split.csv"
    write_cultivar_split(records, races_for(records), out, 0.15, 0.15, "salt")

    rows = read_cultivar_split(out)
    assert find_accession_split_leaks(rows) == []
    splits_per_accession: dict[str, set[str]] = {}
    for row in rows:
        splits_per_accession.setdefault(row["cultivar_label"], set()).add(row["accession_split"])
    assert all(len(splits) == 1 for splits in splits_per_accession.values())


def test_manifest_round_trips_and_rejects_unknown_licences(tmp_path):
    records = [make_cultivar_record("PI 1", "A")]
    path = tmp_path / "m.csv"
    write_cultivar_manifest(records, path)
    assert read_cultivar_manifest(path) == records

    with pytest.raises(ValueError, match="licence"):
        make_cultivar_record("PI 1", "A", license="all-rights-reserved")


def test_parse_study_page_skips_rows_repeating_an_accession_and_image():
    # GRIN lists an accession with four images as four rows whose IMAGE cell shows the first.
    first_row_start = STUDY_PAGE.index("<tr><td>0</td>")
    first_row = STUDY_PAGE[first_row_start : STUDY_PAGE.index("</tr>", first_row_start) + len("</tr>")]
    page = STUDY_PAGE.replace(first_row, first_row * 4)
    assert len(parse_study_page(page)) == 1


def test_drop_repeated_rows_drops_only_exact_copies():
    record = make_cultivar_record("PI 1", "A")
    other_planting = make_cultivar_record("PI 1", "B")
    unique, dropped = drop_repeated_rows([record, record, other_planting, record])
    assert unique == [record, other_planting]
    assert dropped == 2


def test_split_refuses_two_different_rows_with_one_source_id(tmp_path):
    record = make_cultivar_record("PI 1", "A")
    changed = make_cultivar_record("PI 1", "A", sha256="f" * 64)
    with pytest.raises(ValueError, match="occur twice"):
        write_cultivar_split([record, changed], races_for([record]), tmp_path / "s.csv", 0.15, 0.15, "salt")


def test_split_refuses_an_accession_without_a_race_label(tmp_path):
    record = make_cultivar_record("PI 1", "A")
    with pytest.raises(ValueError, match="no race label"):
        write_cultivar_split([record], {}, tmp_path / "s.csv", 0.15, 0.15, "salt")


def test_split_writes_the_race_or_the_exclusion(tmp_path):
    records = [make_cultivar_record("PI 1", "A"), make_cultivar_record("PI 2", "A")]
    races = {
        "PI 1": AccessionRace("Caudatum", None, ("Caudatum",)),
        "PI 2": AccessionRace("", RaceExclusion.CONFLICTING_OBSERVATIONS, ("Caudatum", "Durra")),
    }
    out = tmp_path / "s.csv"
    write_cultivar_split(records, races, out, 0.15, 0.15, "salt")
    by_accession = {row["cultivar_label"]: row for row in read_cultivar_split(out)}
    assert (by_accession["PI 1"]["race"], by_accession["PI 1"]["race_exclusion"]) == ("Caudatum", "")
    assert (by_accession["PI 2"]["race"], by_accession["PI 2"]["race_exclusion"]) == ("", "conflicting-observations")


def split_row(accession: str, sha256: str, split: str) -> dict[str, str]:
    return {"cultivar_label": accession, "sha256": sha256, "accession_split": split}


def test_leak_check_finds_an_accession_in_two_splits():
    rows = [split_row("PI 1", "a", "train"), split_row("PI 1", "b", "test")]
    assert find_accession_split_leaks(rows) == ["accession PI 1 is in ['test', 'train']"]


def test_leak_check_finds_one_file_under_two_accessions_in_two_splits():
    rows = [split_row("PI 1", "same", "train"), split_row("PI 2", "same", "validation")]
    assert find_accession_split_leaks(rows) == ["image file same is in ['train', 'validation']"]
    # The same file under two accessions of one split does not leak.
    assert find_accession_split_leaks([split_row("PI 1", "same", "test"), split_row("PI 2", "same", "test")]) == []
