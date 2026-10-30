"""GRIN-Global descriptor observations for the photographed sorghum accessions.

GRIN records, per accession and per planting ("study"), the race and the morphological
descriptors that the app's trait catalogue reads from photos. This module fetches them for
the accessions in the GRIN image studies (`grin.py`) and maps each GRIN value to the
IBPGR/ICRISAT 1993 state code the app uses
(`shared/src/commonMain/kotlin/com/sorghum/traits/TraitCatalogue.kt`).

GRIN codes its own descriptors, which are not the IBPGR list: for example GRIN glume colour 1
is "Purple" while IBPGR glume colour 1 is "White". So every mapping below is explicit, and a
GRIN value with no single IBPGR equivalent maps to blank instead of a guess (CLAUDE.md: never
guess a trait). Study pages show the value's label ("Purple"), not its code; the code tables
below come from each descriptor's GRIN page (descriptordetail.aspx, read 2026-10-30).
"""

import csv
import os
import re
import urllib.parse
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from sorghum_model.downloads import RequestPacer
from sorghum_model.grin import GRIN_BASE_URL, StudyTableParser


@dataclass(frozen=True)
class GrinDescriptor:
    """A GRIN sorghum descriptor and how its values map to one catalogue trait.

    Attributes:
        code: GRIN's short descriptor name, e.g. "GLUMECOLOR".
        descriptor_id: id of the descriptor's page (descriptordetail.aspx?id=...).
        grin_codes: GRIN value label -> GRIN code, as the descriptor page lists them. Empty for
            numeric descriptors.
        trait_id: the catalogue trait the values map to, or "" when the descriptor is kept
            for evaluation only (race).
        ibpgr_state_of_grin_code: GRIN code -> IBPGR state code. GRIN codes left out have no
            single IBPGR equivalent and map to blank.
    """

    code: str
    descriptor_id: int
    grin_codes: dict[str, str]
    trait_id: str
    ibpgr_state_of_grin_code: dict[str, str]


RACE = GrinDescriptor(
    code="RACE",
    descriptor_id=69065,
    # Harlan & de Wet (1972): five basic races and their ten intermediates.
    grin_codes={
        "Bicolor": "01", "Guinea": "02", "Caudatum": "03", "Kafir": "04", "Durra": "05",
        "Guinea-bicolor": "06", "Caudatum-bicolor": "07", "Kafir-bicolor": "08",
        "Durra-bicolor": "09", "Guinea-caudatum": "10", "Guinea-kafir": "11",
        "Guinea-durra": "12", "Kafir-caudatum": "13", "Durra-caudatum": "14",
        "Kafir-durra": "15", "Shattercane": "16", "Unknown": "17",
    },
    # Race is not a photo trait; it is the "type" label for evaluation (ADR-0011).
    trait_id="",
    ibpgr_state_of_grin_code={},
)

GLUME_COLOUR = GrinDescriptor(
    code="GLUMECOLOR",
    descriptor_id=69042,
    grin_codes={
        "Purple": "1", "Red": "2", "Tan": "3", "Black": "4", "Sienna": "5", "Mahogany": "6",
        "Straw": "7", "Mixed": "8", "Segregating": "9",
    },
    trait_id="glumeColour",
    # IBPGR: 1 White, 2 Sienna, 3 Mahogany, 4 Red, 5 Purple, 6 Black, 7 Grey, 8 Other.
    # Straw -> White: IBPGR has no straw state and its "white" glumes are the pale, straw-
    # coloured ones (ASSUMPTION - confirm). Tan has no IBPGR glume state; Mixed and
    # Segregating describe a mixed accession, not one plant, so all three stay blank.
    ibpgr_state_of_grin_code={"1": "5", "2": "4", "4": "6", "5": "2", "6": "3", "7": "1"},
)

GRAIN_COLOUR = GrinDescriptor(
    code="KERCOLOR",
    descriptor_id=69005,
    grin_codes={"White": "1", "Red": "2", "Yellow": "3", "Brown": "4", "Buff": "5", "Mixed": "6", "Purple": "7"},
    trait_id="grainColour",
    # IBPGR: 1 White, 2 Yellow, 3 Red, 4 Brown, 5 Buff, 6 Other. Purple is not an IBPGR grain
    # colour, so it is "Other"; Mixed stays blank.
    ibpgr_state_of_grin_code={"1": "1", "2": "3", "3": "2", "4": "4", "5": "5", "7": "6"},
)

PANICLE_COMPACTNESS = GrinDescriptor(
    code="PANICLECOM",
    descriptor_id=69061,
    grin_codes={"Compact": "1", "Semi-compact": "2", "Semi-loose": "3", "Loose": "4", "Mixed": "5"},
    trait_id="panicleCompactnessAndShape",
    # Alone, compactness never fixes one IBPGR state (IBPGR combines it with shape and branch
    # habit); see `combined_panicle_state`.
    ibpgr_state_of_grin_code={},
)

PANICLE_SHAPE = GrinDescriptor(
    code="PANICLESHP",
    descriptor_id=69066,
    grin_codes={
        "Lax": "1", "Oval": "2", "Elliptical": "3", "Rectangular": "4", "Broomcorn": "5",
        "Segregating": "6", "Sprankletop": "7", "Mixed": "8",
    },
    trait_id="panicleCompactnessAndShape",
    # Broomcorn is IBPGR 12 whatever the compactness. Lax -> 1 "Very lax panicle"
    # (ASSUMPTION - confirm: GRIN does not grade laxness). Other shapes need compactness too.
    ibpgr_state_of_grin_code={"1": "1", "5": "12"},
)

PLANT_PIGMENTATION = GrinDescriptor(
    code="PLANTCOL",
    descriptor_id=69063,
    grin_codes={
        "Purple": "1", "Red": "2", "Tan": "3", "Purple-red": "4", "Red-purple": "5",
        "Tan-red": "6", "Tan-purple": "7", "Mixed": "8", "Black": "9",
    },
    trait_id="plantPigmentation",
    # IBPGR: 1 Pigmented, 2 Tan. Purple, red and black plants are pigmented. Tan-red and
    # tan-purple are intermediate and Mixed is a mixed accession: blank.
    ibpgr_state_of_grin_code={"1": "1", "2": "1", "3": "2", "4": "1", "5": "1", "9": "1"},
)

MIDRIB_COLOUR = GrinDescriptor(
    code="MIDRIBCOL",
    descriptor_id=69009,
    grin_codes={"Colorless": "1", "Green": "2", "Yellow": "3", "Brown": "4", "Mixed": "5"},
    trait_id="midribColour",
    # IBPGR: 1 White, 2 Dull green, 3 Yellow, 4 Brown, 5 Purple, 6 Other. A colourless midrib
    # is the white (pithy) midrib (ASSUMPTION - confirm). Mixed stays blank.
    ibpgr_state_of_grin_code={"1": "1", "2": "2", "3": "3", "4": "4"},
)

SEED_WEIGHT = GrinDescriptor(
    code="SEEDWEIGHT",
    descriptor_id=69108,
    grin_codes={},  # numeric: grams per 100 seeds
    trait_id="hundredSeedWeight",
    ibpgr_state_of_grin_code={},  # binned by `hundred_seed_weight_state`
)

# Every descriptor fetched. GRIN has no grain lustre descriptor, so that trait has no data.
DESCRIPTORS: tuple[GrinDescriptor, ...] = (
    RACE, GLUME_COLOUR, GRAIN_COLOUR, PANICLE_COMPACTNESS, PANICLE_SHAPE,
    PLANT_PIGMENTATION, MIDRIB_COLOUR, SEED_WEIGHT,
)

# Must equal TraitCatalogue.HUNDRED_SEED_WEIGHT's bins in shared/ (3 below 2.0 g, 5 from
# 2.0 g, 7 from 3.0 g); Python cannot read the Kotlin catalogue, so a change there is copied here.
HUNDRED_SEED_WEIGHT_UPPER_EDGES_GRAMS: tuple[float, float] = (2.0, 3.0)

# Label of the combined descriptor rows written by `combined_panicle_state`.
COMBINED_PANICLE_DESCRIPTOR = "PANICLECOM+PANICLESHP"

# (compactness code, shape code) -> IBPGR panicle compactness and shape state. Only the pairs
# that name one IBPGR state; loose and semi-loose panicles also need the branch habit (erect
# or drooping), which GRIN does not record.
_COMBINED_PANICLE_STATES: dict[tuple[str, str], str] = {
    ("2", "3"): "8",   # semi-compact elliptical -> 8 Semi-compact elliptic
    ("1", "3"): "9",   # compact elliptical -> 9 Compact elliptic
    ("1", "2"): "10",  # compact oval -> 10 Compact oval
}


@dataclass(frozen=True)
class DescriptorObservation:
    """One GRIN observation of one descriptor on one accession in one planting.

    `ibpgr_state` is blank when the GRIN value has no single IBPGR equivalent, and for race.
    """

    accession: str
    descriptor: str
    grin_value: str
    grin_code: str
    trait_id: str
    ibpgr_state: str
    study: str
    source_url: str


OBSERVATION_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(DescriptorObservation))


def ibpgr_state_for(descriptor: GrinDescriptor, grin_value: str) -> tuple[str, str]:
    """Returns (GRIN code, IBPGR state) for a value as a study page shows it.

    Either may be blank: the GRIN code when the label is not in the descriptor's table (GRIN
    added a value), the IBPGR state when there is no single equivalent.
    """
    value = grin_value.strip()
    if descriptor is SEED_WEIGHT:
        return value, hundred_seed_weight_state(value)
    codes_by_label = {label.lower(): code for label, code in descriptor.grin_codes.items()}
    grin_code = codes_by_label.get(value.lower(), "")
    return grin_code, descriptor.ibpgr_state_of_grin_code.get(grin_code, "")


def hundred_seed_weight_state(grams_text: str) -> str:
    """Bins a 100-seed weight in grams into the catalogue's 3/5/7 states; blank if not a number."""
    try:
        grams = float(grams_text)
    except ValueError:
        return ""
    if not grams > 0:
        return ""
    lower_edge, upper_edge = HUNDRED_SEED_WEIGHT_UPPER_EDGES_GRAMS
    if grams < lower_edge:
        return "3"
    if grams < upper_edge:
        return "5"
    return "7"


def combined_panicle_state(compactness_code: str, shape_code: str) -> str:
    """IBPGR panicle compactness-and-shape state from GRIN's two descriptors, or blank."""
    if shape_code in PANICLE_SHAPE.ibpgr_state_of_grin_code:
        return PANICLE_SHAPE.ibpgr_state_of_grin_code[shape_code]
    return _COMBINED_PANICLE_STATES.get((compactness_code, shape_code), "")


def parse_descriptor_studies(page_html: str, descriptor_id: int) -> list[tuple[str, str]]:
    """(study name, study page URL) for every study listed on a descriptor's page."""
    pattern = re.compile(
        r'href="method\.aspx\?id=(\d+)"[^>]*>\s*([^<]+?)\s*</a>.*?'
        rf'href="(methodaccession\.aspx\?id1={descriptor_id}&(?:amp;)?id2=\1)\s*"',
        re.S,
    )
    studies = []
    for match in pattern.finditer(page_html):
        relative = match.group(3).replace("&amp;", "&")
        studies.append((match.group(2), urllib.parse.urljoin(GRIN_BASE_URL, relative)))
    return studies


def parse_observations(
    page_html: str, descriptor: GrinDescriptor, study: str, source_url: str, accessions: set[str]
) -> list[DescriptorObservation]:
    """Reads a study page's (accession, value) rows, keeping only `accessions`."""
    parser = StudyTableParser()
    parser.feed(page_html)
    if not parser.rows:
        return []
    header, *rows = parser.rows
    if "ACCESSION" not in header or "VALUE" not in header:
        raise ValueError(f"{source_url}: no ACCESSION/VALUE column; the page layout changed")
    accession_column, value_column = header.index("ACCESSION"), header.index("VALUE")

    observations = []
    for row in rows:
        if len(row) < len(header):
            continue
        accession = " ".join(row[accession_column].split())
        value = row[value_column].strip()
        if accession not in accessions or not value:
            continue
        grin_code, ibpgr_state = ibpgr_state_for(descriptor, value)
        observations.append(
            DescriptorObservation(
                accession=accession,
                descriptor=descriptor.code,
                grin_value=value,
                grin_code=grin_code,
                trait_id=descriptor.trait_id,
                ibpgr_state=ibpgr_state,
                study=study,
                source_url=source_url,
            )
        )
    return observations


def combine_panicle_observations(observations: Iterable[DescriptorObservation]) -> list[DescriptorObservation]:
    """Adds one combined row per accession and study that has both compactness and shape.

    The combined row carries the IBPGR state (`combined_panicle_state`); the two GRIN rows
    stay as they are.
    """
    by_key: dict[tuple[str, str], dict[str, DescriptorObservation]] = {}
    for observation in observations:
        if observation.descriptor in (PANICLE_COMPACTNESS.code, PANICLE_SHAPE.code):
            by_key.setdefault((observation.accession, observation.study), {})[observation.descriptor] = observation
    combined = []
    for (accession, study), pair in sorted(by_key.items()):
        compactness, shape = pair.get(PANICLE_COMPACTNESS.code), pair.get(PANICLE_SHAPE.code)
        if compactness is None or shape is None:
            continue
        combined.append(
            DescriptorObservation(
                accession=accession,
                descriptor=COMBINED_PANICLE_DESCRIPTOR,
                grin_value=f"{compactness.grin_value} / {shape.grin_value}",
                grin_code=f"{compactness.grin_code}+{shape.grin_code}",
                trait_id=PANICLE_COMPACTNESS.trait_id,
                ibpgr_state=combined_panicle_state(compactness.grin_code, shape.grin_code),
                study=study,
                source_url=shape.source_url,
            )
        )
    return combined


def fetch_observations(
    accessions: set[str],
    fetch_page: Callable[[str], str],
    descriptors: Iterable[GrinDescriptor] = DESCRIPTORS,
) -> Iterator[DescriptorObservation]:
    """Reads every study page of every descriptor, yielding observations for `accessions`.

    `fetch_page` returns a page's HTML for a URL; pass a `CachedPageFetcher` so a rerun after
    a failure skips the pages it already has.
    """
    for descriptor in descriptors:
        page_url = f"{GRIN_BASE_URL}descriptordetail.aspx?id={descriptor.descriptor_id}"
        for study, study_url in parse_descriptor_studies(fetch_page(page_url), descriptor.descriptor_id):
            yield from parse_observations(fetch_page(study_url), descriptor, study, study_url, accessions)


class CachedPageFetcher:
    """Fetches GRIN pages through a folder of saved copies, one file per URL.

    A page is saved only once it has been read in full (written to a temporary file, then
    renamed), so an interrupted run keeps every finished page and the rerun fetches only the
    rest. Pages are kept as HTML rather than parsed rows, so a corrected mapping table is
    applied by rerunning without fetching anything. Single-threaded, like the downloaders.
    """

    def __init__(self, cache_dir: Path, fetch: Callable[[str], str], pacer: RequestPacer) -> None:
        self._cache_dir = cache_dir
        self._fetch = fetch
        self._pacer = pacer

    def __call__(self, url: str) -> str:
        cached = self._cache_dir / cache_file_name(url)
        if cached.exists():
            return cached.read_text(encoding="utf-8")
        self._pacer.wait()
        page = self._fetch(url)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = cached.with_name(f"{cached.name}.{os.getpid()}.tmp")
        temporary.write_text(page, encoding="utf-8")
        temporary.replace(cached)
        return page


def cache_file_name(url: str) -> str:
    """A stable, readable file name for a GRIN page URL ("methodaccession_id1-69065_id2-21001.html")."""
    parsed = urllib.parse.urlparse(url)
    page = Path(parsed.path).name.removesuffix(".aspx")
    query = "_".join(f"{key}-{value}" for key, value in urllib.parse.parse_qsl(parsed.query))
    return f"{page}_{query}.html" if query else f"{page}.html"


def write_observations(observations: list[DescriptorObservation], path: Path) -> None:
    """Writes rows sorted by accession, descriptor and study, via a temporary file and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OBSERVATION_COLUMNS)
        writer.writeheader()
        for observation in sorted(observations, key=lambda o: (o.accession, o.descriptor, o.study)):
            writer.writerow(asdict(observation))
    temporary.replace(path)


def coverage_report(
    observations: list[DescriptorObservation], photographed: set[str], downloaded: set[str]
) -> list[str]:
    """Lines saying, per descriptor, how many accessions have a value and a mapped state.

    Counted over all photographed accessions and over those whose images are downloaded.
    Ends with the race distribution (an accession counts once, under its most frequent race).
    """
    lines = [f"{'descriptor':24} {'any value':>18} {'mapped state':>18}   (photographed / downloaded)"]
    for descriptor in [*[d.code for d in DESCRIPTORS], COMBINED_PANICLE_DESCRIPTOR]:
        rows = [o for o in observations if o.descriptor == descriptor]
        with_value = {o.accession for o in rows}
        mapped = {o.accession for o in rows if o.ibpgr_state}
        lines.append(
            f"{descriptor:24} {len(with_value & photographed):>8} / {len(with_value & downloaded):<8}"
            f" {len(mapped & photographed):>8} / {len(mapped & downloaded):<8}"
        )
    lines.append("grain lustre: GRIN has no lustre descriptor (0 accessions)")

    races_by_accession: dict[str, list[str]] = {}
    for observation in observations:
        if observation.descriptor == RACE.code:
            races_by_accession.setdefault(observation.accession, []).append(observation.grin_value)
    race_counts: dict[str, int] = {}
    for races in races_by_accession.values():
        most_frequent = max(sorted(set(races)), key=races.count)
        race_counts[most_frequent] = race_counts.get(most_frequent, 0) + 1
    conflicting = sum(1 for races in races_by_accession.values() if len(set(races)) > 1)
    lines.append(f"race distribution ({len(races_by_accession)} accessions, {conflicting} with conflicting plantings):")
    for race, count in sorted(race_counts.items(), key=lambda item: -item[1]):
        lines.append(f"  {race:20} {count}")
    return lines
