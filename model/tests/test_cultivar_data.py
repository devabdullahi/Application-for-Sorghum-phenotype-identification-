"""GRIN study-page parsing and the cultivar manifest's grouped splits."""

import csv
from collections import Counter

import pytest

from sorghum_model.cultivar_manifest import (
    CultivarImageRecord,
    assign_planting_splits,
    read_cultivar_manifest,
    write_cultivar_manifest,
    write_cultivar_split,
)
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


def test_accession_split_keeps_every_photo_of_an_accession_together(tmp_path):
    records = [make_cultivar_record(f"PI {i}", planting) for i in range(50) for planting in ("A", "B")]
    out = tmp_path / "split.csv"
    write_cultivar_split(records, out, 0.15, 0.15, "salt")

    with out.open() as file:
        rows = list(csv.DictReader(file))
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
