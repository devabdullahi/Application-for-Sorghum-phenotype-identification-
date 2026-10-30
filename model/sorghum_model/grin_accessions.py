"""Finds a GRIN-Global sorghum accession by another genebank's number, and reads its passport.

GRIN lists, for each accession, the names and numbers other genebanks use for it: ICRISAT's
International Sorghum number ("IS 1233", group "IS"), the NSSL inventory number ("NSL 55749")
and so on. They are on the accession's public detail page (`accessiondetail?id=`), and GRIN's
public search (`search?q=`) finds accessions by any of them. No login is needed for either.

The search is a fuzzy text search: "IS 1233" also returns "OR020-1233" and lentils. So a hit
is only a candidate, and an accession matches a number only when its detail page lists that
exact number (`identifiers`). Pages are fetched through `grin_descriptors.CachedPageFetcher`,
so a rerun reads them from disk.
"""

import html
import re
import urllib.parse
from dataclasses import dataclass
from enum import Enum

from sorghum_model.grin import GRIN_BASE_URL, StudyTableParser

SORGHUM_GENUS = "Sorghum"


@dataclass(frozen=True)
class SearchHit:
    """One row of a GRIN search result: the accession and its detail page id."""

    detail_id: str
    accession: str
    plant_name: str
    taxon: str

    @property
    def is_sorghum(self) -> bool:
        return self.taxon.startswith(SORGHUM_GENUS)


@dataclass(frozen=True)
class AccessionIdentifier:
    """A name or number GRIN lists for an accession, with GRIN's type and group ("IS")."""

    name: str
    identifier_type: str
    group: str


@dataclass(frozen=True)
class AccessionDetail:
    """What the crosswalk reads from an accession's detail page.

    Attributes:
        accession: GRIN's accession number ("PI 562744").
        taxon: the scientific name GRIN shows.
        identifiers: every name and number GRIN lists for the accession.
        has_orderable_seed: the page lists at least one seed lot with an "add to cart" button
            on the day it was fetched. A snapshot, not a promise that a request is granted.
    """

    accession: str
    taxon: str
    identifiers: tuple[AccessionIdentifier, ...]
    has_orderable_seed: bool

    def lists(self, number: str) -> bool:
        """True when `number` is one of the accession's own numbers, compared without case or spacing."""
        wanted = normalized_number(number)
        return wanted == normalized_number(self.accession) or any(
            normalized_number(identifier.name) == wanted for identifier in self.identifiers
        )

    @property
    def icrisat_numbers(self) -> tuple[str, ...]:
        """The accession's ICRISAT International Sorghum numbers (GRIN group "IS")."""
        return tuple(identifier.name for identifier in self.identifiers if identifier.group == "IS")


def normalized_number(number: str) -> str:
    """ "IS 1233", "is1233" and "IS  1233" all give "IS1233"."""
    return "".join(number.split()).upper()


def search_url(query: str) -> str:
    return f"{GRIN_BASE_URL}search?q={urllib.parse.quote(query)}"


def detail_url(detail_id: str) -> str:
    # The ".aspx" form of this page answered HTTP 502 on 2026-10-30; this form answers.
    return f"{GRIN_BASE_URL}accessiondetail?id={detail_id}"


def parse_search_results(page_html: str) -> list[SearchHit]:
    """The result rows of a GRIN search page, in GRIN's order."""
    parser = StudyTableParser()
    parser.feed(page_html)
    header = next((row for row in parser.rows if "ACCESSION" in row and "TAXONOMY" in row), None)
    if header is None:
        return []
    accession_column = header.index("ACCESSION")
    name_column = header.index("PLANT NAME")
    taxon_column = header.index("TAXONOMY")
    hits = []
    for row in parser.rows:
        if row is header or len(row) <= taxon_column:
            continue
        detail_id = _detail_id(parser.links_of_row[id(row)][accession_column])
        if not detail_id:
            continue
        hits.append(
            SearchHit(
                detail_id=detail_id,
                accession=" ".join(row[accession_column].split()),
                plant_name=row[name_column],
                taxon=row[taxon_column],
            )
        )
    return hits


def parse_accession_detail(page_html: str) -> AccessionDetail:
    """Reads an accession detail page (see `AccessionDetail`)."""
    heading = re.search(r"Details for:(.*?)</h1>", page_html, re.S)
    if heading is None:
        raise ValueError("not a GRIN accession detail page (no 'Details for:' heading)")
    # "PI 682397, Sorghum bicolor (L.) Moench subsp. bicolor, IS 8134": number, taxon, top name.
    parts = [" ".join(part.split()) for part in _text(heading.group(1)).split(",")]
    accession = parts[0]
    taxon = parts[1] if len(parts) > 1 else ""
    return AccessionDetail(
        accession=accession,
        taxon=taxon,
        identifiers=_identifiers(page_html),
        has_orderable_seed=_has_orderable_seed(page_html),
    )


def _identifiers(page_html: str) -> tuple[AccessionIdentifier, ...]:
    start = page_html.find("Accession Names and Identifiers")
    if start < 0:
        return ()
    # The panel ends where the next panel heading starts.
    end = page_html.find('class="panel-heading"', start)
    panel = page_html[start : end if end > 0 else len(page_html)]
    # Each entry is a bold name, then "Type: ..." and, for numbered groups, "Group: ...".
    entries = re.split(r'<div class="col-md-12"><b>', panel)[1:]
    identifiers = []
    for entry in entries:
        name = _text(entry.split("</b>", 1)[0])
        identifier_type = re.search(r">Type:\s*([^<]*)<", entry)
        group = re.search(r">Group:\s*([^<]*)<", entry)
        identifiers.append(
            AccessionIdentifier(
                name=" ".join(name.split()),
                identifier_type=identifier_type.group(1).strip() if identifier_type else "",
                group=group.group(1).strip() if group else "",
            )
        )
    return tuple(identifiers)


def _has_orderable_seed(page_html: str) -> bool:
    table = re.search(r"<table id='available'.*?</table>", page_html, re.S)
    if table is None:
        return False
    rows = re.findall(r"<tr>(.*?)</tr>", table.group(0), re.S)
    return any("<td>Seed</td>" in row and "addOneForm(" in row for row in rows)


def _detail_id(links: list[str]) -> str:
    for link in links:
        match = re.search(r"accessiondetail(?:\.aspx)?\?id=(\d+)", link)
        if match:
            return match.group(1)
    return ""


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))



class StudyAvailability(Enum):
    """What a study page's AVAILABILITY cell says about the accession's seed, on the day fetched.

    GRIN shows a cart button when the study's own seed lot can be ordered, "*Not Available"
    when that lot cannot but another lot of the accession can, and "Not Available" (or
    "Historic") when none can.
    """

    ORDERABLE = "orderable"
    OTHER_LOT_ORDERABLE = "other-lot-orderable"
    NOT_AVAILABLE = "not-available"

    @property
    def is_orderable(self) -> bool:
        return self is not StudyAvailability.NOT_AVAILABLE


@dataclass(frozen=True)
class StudyRosterRow:
    """The passport columns of one accession row of a GRIN study page (`methodaccession`)."""

    detail_id: str
    accession: str
    name: str
    taxon: str
    origin: str
    availability: StudyAvailability


def parse_study_roster(page_html: str) -> list[StudyRosterRow]:
    """The accession rows of a GRIN study page with their name, origin and availability."""
    parser = StudyTableParser()
    parser.feed(page_html)
    if not parser.rows:
        return []
    header, *rows = parser.rows
    wanted = ("ID", "ACCESSION", "NAME", "TAXONOMY", "ORIGIN", "AVAILABILITY")
    if any(column not in header for column in wanted):
        raise ValueError(f"study page has no {', '.join(wanted)} columns; the page layout changed")
    column = {name: header.index(name) for name in wanted}
    roster = []
    for row in rows:
        if len(row) < len(header):
            continue
        roster.append(
            StudyRosterRow(
                detail_id=row[column["ID"]],
                accession=" ".join(row[column["ACCESSION"]].split()),
                name=row[column["NAME"]],
                taxon=row[column["TAXONOMY"]],
                origin=row[column["ORIGIN"]],
                availability=_study_availability(row[column["AVAILABILITY"]]),
            )
        )
    return roster


def _study_availability(cell_text: str) -> StudyAvailability:
    text = cell_text.strip()
    if not text:
        return StudyAvailability.ORDERABLE  # the cell holds only the cart button
    if text.startswith("*"):
        return StudyAvailability.OTHER_LOT_ORDERABLE
    return StudyAvailability.NOT_AVAILABLE
