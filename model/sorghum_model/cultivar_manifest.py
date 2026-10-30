"""Cultivar image manifest and its grouped splits.

Separate from the species manifest (`manifest.py`) because the label is different: a row here
names a cultivar or genebank accession (e.g. "PI 533871"), not one of the species classes.
The manifest is committed; the images are not.

Two splits are written for every row, both by group and never by image:

- `accession_split`: every photo of an accession lands in one split. This is the split for
  trait heads (CLAUDE.md: splits by plant, plot or accession), because a trait head must
  generalise to accessions it has never seen.
- `planting_split`: for evaluating direct cultivar identification. An accession photographed
  in several plantings (study, year, site) keeps one planting for test and, with three or
  more, one for validation; the rest train. The test photo is a different plant, season and
  photo session from every training photo of that accession, like the cross-plot split of
  Sorghum-100. Accessions with one planting cannot be tested this way and are `train`.
"""

import csv
import hashlib
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from sorghum_model.splits import Split, assign_split

# Licence codes a cultivar row may carry. GRIN-Global images are taken by USDA-ARS staff,
# which makes them US federal government works with no copyright in the US (17 U.S.C. 105).
# ASSUMPTION - confirm: GRIN shows no licence statement on the images themselves.
CULTIVAR_ALLOWED_LICENSES: frozenset[str] = frozenset(
    {"us-gov-public-domain", "cc0", "cc-by", "cc-by-sa", "odc-by"}
)


@dataclass(frozen=True)
class CultivarImageRecord:
    """One photo labelled with the cultivar or accession it shows.

    Attributes:
        image_path: path relative to the data root, using "/" separators.
        cultivar_label: accession number as the genebank writes it ("PI 533871"); the class.
        accession_name: the accession's cultivar or local name, when the genebank has one.
        taxon: taxon name from the genebank.
        origin: where the accession was collected or bred.
        source: dataset the photo came from, e.g. "grin".
        source_id: id of the photo inside its source.
        planting_id: the planting (study, year, site) the photo was taken in. Two photos of
            one accession with different planting ids show different plants and sessions.
        license: licence code, one of CULTIVAR_ALLOWED_LICENSES.
        attribution: credit line.
        source_url: where the photo was downloaded from.
        sha256: checksum of the image file.
    """

    image_path: str
    cultivar_label: str
    accession_name: str
    taxon: str
    origin: str
    source: str
    source_id: str
    planting_id: str
    license: str
    attribution: str
    source_url: str
    sha256: str

    def __post_init__(self) -> None:
        if self.license not in CULTIVAR_ALLOWED_LICENSES:
            raise ValueError(f"{self.source}/{self.source_id}: licence {self.license!r} is not allowed")
        for required in ("image_path", "cultivar_label", "source", "source_id", "planting_id", "sha256"):
            if not getattr(self, required):
                raise ValueError(f"{self.source}/{self.source_id}: {required} is empty")


CULTIVAR_MANIFEST_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(CultivarImageRecord))


def write_cultivar_manifest(records: list[CultivarImageRecord], path: Path) -> None:
    """Writes rows sorted by source and id (stable diffs), via a temporary file and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CULTIVAR_MANIFEST_COLUMNS)
        writer.writeheader()
        for record in sorted(records, key=lambda r: (r.source, r.source_id)):
            writer.writerow(asdict(record))
    temporary.replace(path)


def read_cultivar_manifest(path: Path) -> list[CultivarImageRecord]:
    with path.open(newline="", encoding="utf-8") as file:
        return [CultivarImageRecord(**row) for row in csv.DictReader(file)]


def assign_planting_splits(records: list[CultivarImageRecord], salt: str) -> dict[tuple[str, str], Split]:
    """Returns the planting split of every record, keyed by (source, source_id).

    Keyed by id rather than sha256 because a genebank can reuse one photo file for two
    plantings; see the module docstring for the rule.

    Which planting of an accession is held out is decided by a hash of the salt, accession
    and planting, so it is stable when new plantings or accessions are added.
    """
    plantings_by_accession: dict[str, set[str]] = defaultdict(set)
    for record in records:
        plantings_by_accession[record.cultivar_label].add(record.planting_id)

    split_of_planting: dict[tuple[str, str], Split] = {}
    for accession, plantings in plantings_by_accession.items():
        ordered = sorted(plantings, key=lambda planting: _stable_hash(f"{salt}:{accession}:{planting}"))
        for index, planting in enumerate(ordered):
            if len(ordered) >= 2 and index == 0:
                split = Split.TEST
            elif len(ordered) >= 3 and index == 1:
                split = Split.VALIDATION
            else:
                split = Split.TRAIN
            split_of_planting[(accession, planting)] = split

    return {
        (record.source, record.source_id): split_of_planting[(record.cultivar_label, record.planting_id)]
        for record in records
    }


SPLIT_COLUMNS: tuple[str, ...] = (
    "sha256",
    "source",
    "source_id",
    "cultivar_label",
    "planting_id",
    "accession_split",
    "planting_split",
)


def write_cultivar_split(
    records: list[CultivarImageRecord],
    path: Path,
    validation_fraction: float,
    test_fraction: float,
    salt: str,
) -> None:
    """Writes both splits for every record (accession-grouped and planting-grouped)."""
    planting_splits = assign_planting_splits(records, salt)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SPLIT_COLUMNS)
        writer.writeheader()
        for record in sorted(records, key=lambda r: (r.source, r.source_id)):
            accession_split = assign_split(record.cultivar_label, validation_fraction, test_fraction, salt)
            writer.writerow(
                {
                    "sha256": record.sha256,
                    "source": record.source,
                    "source_id": record.source_id,
                    "cultivar_label": record.cultivar_label,
                    "planting_id": record.planting_id,
                    "accession_split": accession_split.value,
                    "planting_split": planting_splits[(record.source, record.source_id)].value,
                }
            )


def _stable_hash(text: str) -> bytes:
    return hashlib.sha256(text.encode()).digest()
