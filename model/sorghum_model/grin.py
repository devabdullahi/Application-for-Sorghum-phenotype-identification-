"""GRIN-Global (USDA National Plant Germplasm System) sorghum seed/panicle images.

USDA-ARS photographed harvested panicles and threshed grain of sorghum accessions, with a
centimetre ruler, on a grey board, in eleven plantings (St. Croix, Isabela, Ethiopian and
Sudan collections, 1993-2012). Each accession of a planting has one image, a few have two to
four, labelled by its accession number (PI or GRIF). These are the only accession-labelled sorghum close-ups found
that anyone can download without an account (decision note: docs/architecture/adr/
0011-cultivar-accuracy-target.md).

The images are listed on the "Image (IMAGE)" descriptor's study pages, which are HTML only
(no JSON API), so each study page is parsed for its accession rows. Downloads go through
`downloads.py`, which paces requests to one per second.

Which column names the image: a row's IMAGE cell shows the accession's first image in GRIN,
which can come from another planting (in SORGHUM.IMAGE.SP42.2006, 132 of 373 rows show an
Isabela or Ethiopian photo), and repeats that first image on the "Second/Third/Fourth image"
rows. The NOTE column links the row's own image on the old NPGS server, so that link is used,
mapped to the same file on the GRIN-Global server.
"""

import html
import html.parser
import urllib.parse
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from sorghum_model.cultivar_manifest import CultivarImageRecord
from sorghum_model.downloads import download_file
from sorghum_model.manifest import sha256_of_file

GRIN_BASE_URL = "https://npgsweb.ars-grin.gov/gringlobal/"

# GRIN-Global descriptor "Image (IMAGE)" for crop SORGHUM; its studies list the photographed
# accessions.
SORGHUM_IMAGE_DESCRIPTOR_ID = 69107

SOURCE_NAME = "grin"
LICENSE_CODE = "us-gov-public-domain"

# The NOTE column links images on the old NPGS server ("/npgs/images/s9/sorghum/stc2002/PI1.jpg").
# GRIN-Global serves the same file under its uploads folder; checked by hand on 2026-10-30 for
# rows of SP42.2006 and ISABELA.2010, where the two servers' paths differ only by this prefix.
NOTE_IMAGE_PREFIX = "/npgs/images/"
UPLOADED_IMAGE_PREFIX = "/gringlobal/uploads/images/npgs/"


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
    """One image of a study page: an accession and the path of the image on the GRIN server.

    `photo_id` names the image inside its study: the accession id when the accession has one
    image there, else "<accession id>/<file name>", so every image has its own manifest row.
    """

    accession_id: str
    accession_number: str
    accession_name: str
    taxon: str
    origin: str
    image_path: str
    photo_id: str


def uploaded_image_path_of_note_link(link: str) -> str | None:
    """Maps a NOTE column link to the image's path on the GRIN-Global server, or None.

    GRIN writes some links unquoted with a stray closing quote (`href =/npgs/...jpg"`), so
    quotes and spaces around the link are dropped. A link outside NOTE_IMAGE_PREFIX, or one
    naming no file after it, is not an image link.
    """
    cleaned = link.strip().strip("\"'").strip()
    if not cleaned.startswith(NOTE_IMAGE_PREFIX) or len(cleaned) == len(NOTE_IMAGE_PREFIX):
        return None
    return UPLOADED_IMAGE_PREFIX + cleaned.removeprefix(NOTE_IMAGE_PREFIX)


def parse_study_page(page_html: str) -> list[GrinAccessionImage]:
    """Reads the images of a study page, one per distinct (accession, image) pair.

    A row's image is the one its NOTE column links (see the module docstring); a row without
    a usable NOTE link falls back to its IMAGE cell, and a row with neither is skipped. Rows
    repeating an earlier row's accession and image are skipped.

    Columns are found by their header (ID, ACCESSION, NAME, TAXONOMY, ORIGIN, IMAGE, NOTE),
    so a reordered table still parses; a page without those headers raises ValueError.
    """
    parser = StudyTableParser()
    parser.feed(page_html)
    header, *rows = parser.rows
    required = ("ID", "ACCESSION", "NAME", "TAXONOMY", "ORIGIN", "IMAGE", "NOTE")
    missing = [name for name in required if name not in header]
    if missing:
        raise ValueError(f"GRIN study page has no column(s) {missing}; the page layout changed")
    column = {name: header.index(name) for name in required}

    rows_with_images: list[tuple[list[str], str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if len(row) < len(header):
            continue
        image_path = _row_image_path(
            parser.links_of_row[id(row)][column["NOTE"]], parser.images_of_row[id(row)][column["IMAGE"]]
        )
        if image_path is None:
            continue
        key = (row[column["ID"]], image_path)
        if key in seen:
            continue
        seen.add(key)
        rows_with_images.append((row, image_path))

    images_per_accession = Counter(row[column["ID"]] for row, _ in rows_with_images)
    images = []
    for row, image_path in rows_with_images:
        accession_id = row[column["ID"]]
        photo_id = accession_id
        if images_per_accession[accession_id] > 1:
            photo_id = f"{accession_id}/{Path(image_path).name}"
        images.append(
            GrinAccessionImage(
                accession_id=accession_id,
                accession_number=" ".join(row[column["ACCESSION"]].split()),
                accession_name=row[column["NAME"]],
                taxon=" ".join(row[column["TAXONOMY"]].split()),
                origin=row[column["ORIGIN"]],
                image_path=image_path,
                photo_id=photo_id,
            )
        )
    return images


def _row_image_path(note_links: list[str], image_sources: list[str]) -> str | None:
    """The row's own image (first NOTE image link), else the IMAGE cell's upload, else None."""
    for link in note_links:
        image_path = uploaded_image_path_of_note_link(link)
        if image_path is not None:
            return image_path
    uploads = [source for source in image_sources if "/uploads/images/" in source]
    return uploads[0] if uploads else None


def download_study(
    study: GrinImageStudy,
    page_html: str,
    data_root: Path,
    on_failure: Callable[[GrinAccessionImage, Exception], None],
    previous_source_urls: Mapping[str, str] | None = None,
) -> Iterator[CultivarImageRecord]:
    """Downloads every image of one study page, yielding each manifest row as its file is ready.

    Files go to `<data_root>/grin/<study name>/<file name>`. Files already on disk are not
    fetched again, so an interrupted run resumes, unless `previous_source_urls` (manifest
    image path -> source URL, from the last run's manifest) says the file there came from
    another URL: earlier runs saved the IMAGE cell's image, which can be another planting's
    photo under this row's file name. Keys are compared case-folded because the data drive's
    file system ignores case. An image that fails to download, or whose file name another
    image of the study already uses, is passed to `on_failure` and left out.
    """
    previous_url_of_path = {path.casefold(): url for path, url in (previous_source_urls or {}).items()}
    used_paths: set[str] = set()
    for image in parse_study_page(page_html):
        url = urllib.parse.urljoin(GRIN_BASE_URL, image.image_path)
        file_name = Path(urllib.parse.urlparse(url).path).name
        relative_path = f"{SOURCE_NAME}/{study.name}/{file_name}"
        destination = data_root / relative_path
        if relative_path.casefold() in used_paths:
            on_failure(image, ValueError(f"{relative_path} is already used by another image of {study.name}"))
            continue
        # Claimed before the download, so which image owns a file name never depends on which
        # downloads happened to fail.
        used_paths.add(relative_path.casefold())
        previous_url = previous_url_of_path.get(relative_path.casefold())
        if previous_url is not None and previous_url != url:
            destination.unlink(missing_ok=True)
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
            source_id=f"{study.name}/{image.photo_id}",
            planting_id=study.name,
            license=LICENSE_CODE,
            attribution=f"USDA-ARS GRIN-Global, {study.name}, accession {image.accession_number}",
            source_url=url,
            sha256=sha256_of_file(destination),
        )


class StudyTableParser(html.parser.HTMLParser):
    """Collects the text, <img> sources and <a> links of every cell of a GRIN study page's rows.

    `rows` holds each row's cell texts (header row first); `images_of_row[id(row)]` and
    `links_of_row[id(row)]` hold the image sources and link targets of each cell of that row.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.images_of_row: dict[int, list[list[str]]] = {}
        self.links_of_row: dict[int, list[list[str]]] = {}
        self._row: list[str] | None = None
        self._row_images: list[list[str]] = []
        self._row_links: list[list[str]] = []
        self._cell_text: list[str] | None = None
        self._cell_images: list[str] = []
        self._cell_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row, self._row_images, self._row_links = [], [], []
        elif tag in ("td", "th") and self._row is not None:
            self._cell_text, self._cell_images, self._cell_links = [], [], []
        elif tag == "img" and self._cell_text is not None:
            source = dict(attrs).get("src")
            if source:
                self._cell_images.append(html.unescape(source))
        elif tag == "a" and self._cell_text is not None:
            target = dict(attrs).get("href")
            if target:
                self._cell_links.append(html.unescape(target))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell_text is not None:
            self._row.append(" ".join("".join(self._cell_text).split()))
            self._row_images.append(self._cell_images)
            self._row_links.append(self._cell_links)
            self._cell_text = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
                self.images_of_row[id(self._row)] = self._row_images
                self.links_of_row[id(self._row)] = self._row_links
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell_text is not None:
            self._cell_text.append(data)
