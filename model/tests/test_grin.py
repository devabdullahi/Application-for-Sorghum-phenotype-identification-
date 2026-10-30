"""GRIN study pages: which image a row names, several images per accession, and resuming."""

from pathlib import Path

import pytest

from sorghum_model import grin
from sorghum_model.grin import GrinImageStudy, parse_study_page, uploaded_image_path_of_note_link

HEADER = (
    "<table id='searchtable'><thead><tr><th><span></span></th><th>ID</th><th>ACCESSION</th>"
    "<th>NAME</th><th>TAXONOMY</th><th>ORIGIN</th><th>AVAILABILITY</th><th>IMAGE</th><th>VALUE</th>"
    "<th>OBSERVATIONS</th><th>NOTE</th><th>INVENTORY</th></tr></thead><tbody>"
)
FOOTER = "</tbody></table>"


def study_row(accession_id: str, accession: str, image_cell: str, note_cell: str, value: str = "Image of Seed/Panicle") -> str:
    """One row in the layout of a real study page (cells cut from SORGHUM.IMAGE.SP42.2006)."""
    return (
        f"<tr><td>0</td><td>{accession_id}</td><td><a href='accessiondetail.aspx?id={accession_id}'>{accession} </a></td>"
        "<td>ETS 3134</td><td><i>Sorghum bicolor</i></td><td> Ethiopia</td><td>cart</td>"
        f"<td>{image_cell}</td><td>{value}</td><td>0</td><td>{note_cell}</td><td>{accession} **</td></tr>"
    )


def image_cell(path: str) -> str:
    return f'<a href="ImgDisplay.aspx?id=1"><img src="{path}" height="100" alt="PANICLE"></a>'


ETHIOPIAN_UPLOAD = "/gringlobal/uploads/images/npgs/s9/sorghum/ethiopian1998_1999/PI454590.JPG"
# GRIN's real markup: an unquoted link with a stray closing quote, and a thumbnail image.
SP42_NOTE = (
    '<a href =/npgs/images/s9/sorghum/stc2006_sp42/PI454590.jpg">'
    '<IMG src="http://sun.ars-grin.gov/perl/npgs/thumb.pl?file=/pub/npgs/images/s9/sorghum/stc2006_sp42/PI454590.jpg" height=60 ></a>"'
)
SP42_UPLOAD = "/gringlobal/uploads/images/npgs/s9/sorghum/stc2006_sp42/PI454590.jpg"


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ('/npgs/images/s9/sorghum/stc2002/PI1.jpg', "/gringlobal/uploads/images/npgs/s9/sorghum/stc2002/PI1.jpg"),
        ('/npgs/images/s9/sorghum/stc2002/PI1.jpg"', "/gringlobal/uploads/images/npgs/s9/sorghum/stc2002/PI1.jpg"),
        ('  "/npgs/images/x.jpg"  ', "/gringlobal/uploads/images/npgs/x.jpg"),
        ("/npgs/images/", None),  # the prefix alone names no file
        ("/npgs/image/x.jpg", None),
        ("/NPGS/images/x.jpg", None),
        ("ImgDisplay.aspx?id=1", None),
        ("", None),
    ],
)
def test_note_link_maps_to_the_upload_path_only_for_npgs_images(link, expected):
    assert uploaded_image_path_of_note_link(link) == expected


def test_the_note_link_wins_over_an_image_cell_showing_another_planting():
    page = HEADER + study_row("1349526", "PI 454590", image_cell(ETHIOPIAN_UPLOAD), SP42_NOTE) + FOOTER

    [image] = parse_study_page(page)

    assert image.image_path == SP42_UPLOAD
    assert image.photo_id == "1349526"


def test_a_row_without_a_usable_note_link_falls_back_to_the_image_cell():
    rows = (
        study_row("1", "PI 1", image_cell(ETHIOPIAN_UPLOAD), "")
        + study_row("2", "PI 2", image_cell(ETHIOPIAN_UPLOAD.replace("PI454590", "PI2")), '<a href="accessiondetail.aspx?id=2">x</a>')
    )

    images = parse_study_page(HEADER + rows + FOOTER)

    assert [image.image_path for image in images] == [ETHIOPIAN_UPLOAD, ETHIOPIAN_UPLOAD.replace("PI454590", "PI2")]


def test_a_row_with_neither_image_nor_note_link_is_skipped():
    page = HEADER + study_row("1", "PI 1", "", "") + FOOTER
    assert parse_study_page(page) == []


def test_an_accession_with_several_images_gets_one_image_per_note_link():
    # PI 482968 in SORGHUM.IMAGE.ISABELA.2010: four rows, every IMAGE cell showing the first.
    first = image_cell("/gringlobal/uploads/images/npgs/s9/sorghum/isabela2010/PI482968_brown.jpg")
    rows = "".join(
        study_row("1377904", "PI 482968", first, f'<a href ="/npgs/images/s9/sorghum/isabela2010/PI482968_{name}.jpg"></a>', value)
        for name, value in (
            ("wild", "Fourth image of Seed/Panicle"),
            ("brown", "Image of Seed/Panicle"),
            ("white", "Second image of Seed/Panicle"),
            ("brown", "Image of Seed/Panicle"),  # an exact repeat of a row is one image
        )
    )
    rows += study_row("1377905", "PI 482969", image_cell(ETHIOPIAN_UPLOAD), SP42_NOTE)

    images = parse_study_page(HEADER + rows + FOOTER)

    assert [image.photo_id for image in images] == [
        "1377904/PI482968_wild.jpg",
        "1377904/PI482968_brown.jpg",
        "1377904/PI482968_white.jpg",
        "1377905",  # a single image keeps the plain accession id, as in earlier manifests
    ]
    assert len({image.image_path for image in images}) == 4


def test_a_page_without_a_note_column_is_a_changed_layout():
    page = HEADER.replace("<th>NOTE</th>", "") + FOOTER
    with pytest.raises(ValueError, match="NOTE"):
        parse_study_page(page)


STUDY = GrinImageStudy("SORGHUM.IMAGE.SP42.2006", 493374)


@pytest.fixture
def fake_downloads(monkeypatch) -> list[str]:
    """Replaces the network: a download writes the URL into the file and is recorded."""
    fetched: list[str] = []

    def download_file(url: str, destination: Path) -> None:
        if destination.exists():
            return
        fetched.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(url)

    monkeypatch.setattr(grin, "download_file", download_file)
    return fetched


def test_download_refetches_a_file_that_came_from_another_url(tmp_path, fake_downloads):
    page = HEADER + study_row("1349526", "PI 454590", image_cell(ETHIOPIAN_UPLOAD), SP42_NOTE) + FOOTER
    relative_path = f"grin/{STUDY.name}/PI454590.jpg"
    # An earlier run saved the Ethiopian photo under this row's name (upper-case extension).
    (tmp_path / relative_path).parent.mkdir(parents=True)
    (tmp_path / relative_path).write_text("ethiopian photo")
    previous = {relative_path.upper(): "https://npgsweb.ars-grin.gov" + ETHIOPIAN_UPLOAD}

    [record] = grin.download_study(STUDY, page, tmp_path, pytest.fail, previous)

    assert fake_downloads == ["https://npgsweb.ars-grin.gov" + SP42_UPLOAD]
    assert record.source_url == "https://npgsweb.ars-grin.gov" + SP42_UPLOAD
    assert record.source_id == f"{STUDY.name}/1349526"
    assert (tmp_path / relative_path).read_text() == record.source_url


def test_download_keeps_a_file_that_came_from_the_same_url(tmp_path, fake_downloads):
    page = HEADER + study_row("1349526", "PI 454590", image_cell(ETHIOPIAN_UPLOAD), SP42_NOTE) + FOOTER
    relative_path = f"grin/{STUDY.name}/PI454590.jpg"
    (tmp_path / relative_path).parent.mkdir(parents=True)
    (tmp_path / relative_path).write_text("sp42 photo")
    previous = {relative_path: "https://npgsweb.ars-grin.gov" + SP42_UPLOAD}

    list(grin.download_study(STUDY, page, tmp_path, pytest.fail, previous))

    assert fake_downloads == []
    assert (tmp_path / relative_path).read_text() == "sp42 photo"


def test_download_refuses_two_images_with_one_file_name(tmp_path, fake_downloads):
    rows = study_row("1", "PI 1", "", '<a href="/npgs/images/a/PI1.jpg"></a>') + study_row(
        "2", "PI 2", "", '<a href="/npgs/images/b/pi1.JPG"></a>'
    )
    failures = []

    records = list(
        grin.download_study(STUDY, HEADER + rows + FOOTER, tmp_path, lambda image, error: failures.append(image))
    )

    assert [record.cultivar_label for record in records] == ["PI 1"]
    assert [image.accession_number for image in failures] == ["PI 2"]
