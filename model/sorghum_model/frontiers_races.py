"""The race labels of the Frontiers 2023 sorghum race genomics panel (Table 1).

The panel's Table 1 (Frontiers in Plant Science 2023, CC BY 4.0, figshare article 22292089)
lists 281 sequenced samples with the race the authors assigned. It is a second, independent
race source for accessions GRIN-Global also holds, so it shows how often two curators agree
on a race (ADR-0011: the ceiling of a race metric is the agreement of its labels).

Its `Name` column is a genebank number for most rows, written without a space ("IS1233",
"PI383856", "NSL55749"). Rows from Yan et al. 2018 are named by sample ("SCIV1") and have no
genebank number, so they cannot be matched to any genebank.

The workbook is read with the standard library (an .xlsx file is a zip of XML parts), so this
one table does not add a spreadsheet dependency.
"""

import re
import zipfile
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

FRONTIERS_ARTICLE_ID = 22292089
# The Table 1-19 workbook of the article (figshare file 39642142), read on 2026-10-30.
FRONTIERS_TABLE_URL = "https://ndownloader.figshare.com/files/39642142"
# figshare's published checksum of that file (article version 1).
FRONTIERS_TABLE_MD5 = "6bd452eea38bbd378e1cc75c2b0f34f7"
FRONTIERS_TABLE_SHEET = "Table1"
FRONTIERS_LICENSE = "CC BY 4.0"
FRONTIERS_SOURCE = "frontiers-2023-table1"

_SPREADSHEET_NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RELATIONSHIP_NAMESPACE = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PACKAGE_RELATIONSHIP_NAMESPACE = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# The genebank number prefixes the table uses: GRIN plant introductions, NSSL inventory numbers
# (listed by GRIN as site identifiers) and ICRISAT's International Sorghum numbers.
_GENEBANK_NUMBER = re.compile(r"^(PI|NSL|IS)\s*(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class FrontiersSample:
    """One row of Table 1.

    Attributes:
        sample_id: the `ID` column (an SRA run, or the IS number for Jensen et al. 2019 rows).
        name: the `Name` column as written.
        race: the `SorghumRace` column as written ("Bicolor-caudatum").
        reference: the study the sequence comes from.
        genebank_number: `name` written the way GRIN writes numbers ("IS 1233"), or "" when the
            name is not a genebank number.
    """

    sample_id: str
    name: str
    race: str
    reference: str
    genebank_number: str


def genebank_number(name: str) -> str:
    """Returns "IS 1233" for "IS1233" (likewise PI and NSL), or "" for a sample name."""
    match = _GENEBANK_NUMBER.match(name.strip())
    if match is None:
        return ""
    return f"{match.group(1).upper()} {match.group(2)}"


def read_frontiers_table(path: Path, sheet_name: str = FRONTIERS_TABLE_SHEET) -> list[FrontiersSample]:
    """Reads the samples of Table 1 from the article's workbook.

    The header row is found by its `ID`, `Name` and `SorghumRace` cells (row 2 in the 2023
    file, under a title row), so a re-saved copy with the title removed still reads.
    """
    rows = read_sheet_rows(path, sheet_name)
    header_index = next(
        (index for index, row in enumerate(rows) if {"ID", "Name", "SorghumRace"} <= set(row.values())),
        None,
    )
    if header_index is None:
        raise ValueError(f"{path} sheet {sheet_name}: no header row with ID, Name and SorghumRace")
    column_of = {value: column for column, value in rows[header_index].items()}
    samples = []
    for row in rows[header_index + 1 :]:
        sample_id = row.get(column_of["ID"], "").strip()
        if not sample_id:
            continue
        name = row.get(column_of["Name"], "").strip()
        samples.append(
            FrontiersSample(
                sample_id=sample_id,
                name=name,
                race=row.get(column_of["SorghumRace"], "").strip(),
                reference=row.get(column_of.get("Reference", ""), "").strip(),
                genebank_number=genebank_number(name),
            )
        )
    return samples


def read_sheet_rows(path: Path, sheet_name: str) -> list[dict[str, str]]:
    """Every row of one sheet as {column letter: cell text}, in sheet order."""
    with zipfile.ZipFile(path) as workbook:
        shared_strings = _shared_strings(workbook)
        sheet = ElementTree.fromstring(workbook.read(_sheet_part(workbook, sheet_name)))
    rows = []
    for row in sheet.iter(f"{_SPREADSHEET_NAMESPACE}row"):
        cells = {}
        for cell in row.findall(f"{_SPREADSHEET_NAMESPACE}c"):
            column = re.sub(r"\d", "", cell.get("r", ""))
            cells[column] = _cell_text(cell, shared_strings)
        rows.append(cells)
    return rows


def _shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.iter(f"{_SPREADSHEET_NAMESPACE}t"))
        for item in root.findall(f"{_SPREADSHEET_NAMESPACE}si")
    ]


def _sheet_part(workbook: zipfile.ZipFile, sheet_name: str) -> str:
    """The zip path of a sheet, looked up by name (sheet1.xml is not always the first sheet)."""
    sheets = ElementTree.fromstring(workbook.read("xl/workbook.xml")).iter(f"{_SPREADSHEET_NAMESPACE}sheet")
    relationship_id = next(
        (sheet.get(f"{_RELATIONSHIP_NAMESPACE}id") for sheet in sheets if sheet.get("name") == sheet_name), None
    )
    if relationship_id is None:
        raise ValueError(f"workbook has no sheet named {sheet_name}")
    relationships = ElementTree.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    for relationship in relationships.iter(f"{_PACKAGE_RELATIONSHIP_NAMESPACE}Relationship"):
        if relationship.get("Id") == relationship_id:
            return "xl/" + relationship.get("Target", "").removeprefix("/xl/")
    raise ValueError(f"workbook has no part for sheet {sheet_name}")


def _cell_text(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(f"{_SPREADSHEET_NAMESPACE}t"))
    value = cell.find(f"{_SPREADSHEET_NAMESPACE}v")
    if value is None or value.text is None:
        return ""
    if cell.get("t") == "s":
        return shared_strings[int(value.text)]
    return value.text
