"""GRIN-Global (USDA National Plant Germplasm System) sorghum seed/panicle images.

USDA-ARS photographed harvested panicles and threshed grain of sorghum accessions, with a
centimetre ruler, on a grey board, in eleven plantings (St. Croix, Isabela, Ethiopian and
Sudan collections, 1993-2012). Each accession of a planting has one image, labelled by its
accession number (PI or GRIF). These are the only accession-labelled sorghum close-ups found
that anyone can download without an account (decision note: docs/architecture/adr/
0011-cultivar-accuracy-target.md).

The images are listed on the "Image (IMAGE)" descriptor's study pages, which are HTML only
(no JSON API), so each study page is parsed for its accession rows. Downloads go through
`downloads.py`, which paces requests to one per second.
"""

import html
import html.parser
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sorghum_model.cultivar_manifest import CultivarImageRecord
from sorghum_model.downloads import download_file, get_text
from sorghum_model.manifest import sha256_of_file

GRIN_BASE_URL = "https://npgsweb.ars-grin.gov/gringlobal/"

# GRIN-Global descriptor "Image (IMAGE)" for crop SORGHUM; its studies list the photographed
# accessions.
SORGHUM_IMAGE_DESCRIPTOR_ID = 69107

SOURCE_NAME = "grin"
LICENSE_CODE = "us-gov-public-domain"


@dataclass(frozen=True)
class GrinImageStudy:
    """One planting whose accessions were photographed. `name` is GRIN's study name."""

    name: str
    method_id: int

    @property
    def page_url(self) -> str:
        return f"{GRIN_BASE_URL}methodaccession.aspx?id1={SORGHUM_IMAGE_DESCRIPTOR_ID}&id2={self.method_id}"


# Every study listed on descriptordetail.aspx?id=69107 on 2026-10-29, with its accession count
# there: 1604 + 1531 + 25 + 207 + 363 + 373 + 1392 + 409 + 780 + 2688 + 22.
SORGHUM_IMAGE_STUDIES: tuple[GrinImageStudy, ...] = (
    GrinImageStudy("SORGHUM.IMAGE.ETHIOPIAN.1998-1999", 495004),
    GrinImageStudy("SORGHUM.IMAGE.ISABELA.2010", 494602),
    GrinImageStudy("SORGHUM.IMAGE.SEED", 494999),
    GrinImageStudy("SORGHUM.IMAGE.SP36.2004", 493372),
    GrinImageStudy("SORGHUM.IMAGE.SP41.2006", 493373),
    GrinImageStudy("SORGHUM.IMAGE.SP42.2006", 493374),
    GrinImageStudy("SORGHUM.IMAGE.STC.2002", 492631),
    GrinImageStudy("SORGHUM.IMAGE.STC.2005", 495001),
    GrinImageStudy("SORGHUM.IMAGE.STC.2007", 494276),
    GrinImageStudy("SORGHUM.IMAGE.STC1993.SUDAN", 495211),
    GrinImageStudy("SORGHUM.PUERTO.VALLARTA.2012", 495284),
)


@dataclass(frozen=True)
class GrinAccessionImage:
    """One row of a study page: an accession and the path of its image on the GRIN server."""

    accession_id: str
    accession_number: str
    accession_name: str
    taxon: str
    origin: str
    image_path: str


def parse_study_page(page_html: str) -> list[GrinAccessionImage]:
    """Reads the accession rows of a study page. Rows without an image are skipped.

    Columns are found by their header (ID, ACCESSION, NAME, TAXONOMY, ORIGIN, IMAGE), so a
    reordered table still parses; a page without those headers raises ValueError.
    """
    parser = StudyTableParser()
    parser.feed(page_html)
    header, *rows = parser.rows
    required = ("ID", "ACCESSION", "NAME", "TAXONOMY", "ORIGIN", "IMAGE")
    missing = [name for name in required if name not in header]
    if missing:
        raise ValueError(f"GRIN study page has no column(s) {missing}; the page layout changed")
    column = {name: header.index(name) for name in required}

    images = []
    for row in rows:
        if len(row) < len(header):
            continue
        image_sources = parser.images_of_row[id(row)][column["IMAGE"]]
        uploads = [source for source in image_sources if "/uploads/images/" in source]
        if not uploads:
            continue
        images.append(
            GrinAccessionImage(
                accession_id=row[column["ID"]],
                accession_number=" ".join(row[column["ACCESSION"]].split()),
                accession_name=row[column["NAME"]],
                taxon=" ".join(row[column["TAXONOMY"]].split()),
                origin=row[column["ORIGIN"]],
                image_path=uploads[0],
            )
        )
    return images


def download_study(
    study: GrinImageStudy,
    data_root: Path,
    on_failure: Callable[[GrinAccessionImage, Exception], None],
) -> Iterator[CultivarImageRecord]:
    """Downloads every image of one study, yielding each manifest row as its file is ready.

    Files go to `<data_root>/grin/<study name>/<file name>`. Files already on disk are not
    fetched again, so an interrupted run resumes. An image that fails to download is passed
    to `on_failure` and left out.
    """
    for image in parse_study_page(get_text(study.page_url)):
        url = urllib.parse.urljoin(GRIN_BASE_URL, image.image_path)
        file_name = Path(urllib.parse.urlparse(url).path).name
        relative_path = f"{SOURCE_NAME}/{study.name}/{file_name}"
        destination = data_root / relative_path
        try:
            download_file(url, destination)
        except Exception as error:  # noqa: BLE001 - reported per image; the run continues
            on_failure(image, error)
            continue
        yield CultivarImageRecord(
            image_path=relative_path,
            cultivar_label=image.accession_number,
            accession_name=image.accession_name,
            taxon=image.taxon,
            origin=image.origin,
            source=SOURCE_NAME,
            source_id=f"{study.name}/{image.accession_id}",
            planting_id=study.name,
            license=LICENSE_CODE,
            attribution=f"USDA-ARS GRIN-Global, {study.name}, accession {image.accession_number}",
            source_url=url,
            sha256=sha256_of_file(destination),
        )


class StudyTableParser(html.parser.HTMLParser):
    """Collects the text and <img> sources of every cell of a GRIN study page's table rows.

    `rows` holds each row's cell texts (header row first); `images_of_row[id(row)]` holds the
    image sources of each cell of that row.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.images_of_row: dict[int, list[list[str]]] = {}
        self._row: list[str] | None = None
        self._row_images: list[list[str]] = []
        self._cell_text: list[str] | None = None
        self._cell_images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row, self._row_images = [], []
        elif tag in ("td", "th") and self._row is not None:
            self._cell_text, self._cell_images = [], []
        elif tag == "img" and self._cell_text is not None:
            source = dict(attrs).get("src")
            if source:
                self._cell_images.append(html.unescape(source))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell_text is not None:
            self._row.append(" ".join("".join(self._cell_text).split()))
            self._row_images.append(self._cell_images)
            self._cell_text = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
                self.images_of_row[id(self._row)] = self._row_images
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell_text is not None:
            self._cell_text.append(data)
