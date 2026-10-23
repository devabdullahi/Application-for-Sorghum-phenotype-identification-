"""Downloads openly licensed, human-identified photos from GBIF occurrence records.

GBIF adds what iNaturalist lacks: herbarium sheets (most of the pearl and finger millet
images that exist), botanical-garden specimens and other citizen-science portals
(observation.org, Pl@ntNet). iNaturalist's own GBIF dataset is skipped because `inat.py`
already downloads it, and the same photo under two sources would leak across splits.

Each record's `basisOfRecord` goes into the label source, so training can later drop, say,
herbarium sheets if they turn out to hurt field-photo accuracy. API reference:
https://techdocs.gbif.org/en/openapi/v1/occurrence
"""

import hashlib
from collections.abc import Iterator

from sorghum_model.downloads import PhotoToDownload, get_json
from sorghum_model.manifest import ALLOWED_LICENSES, LabelStatus, normalize_license_code

GBIF_OCCURRENCE_SEARCH_URL = "https://api.gbif.org/v1/occurrence/search"

# GBIF's image cache serves resized copies, so we never pull a 50 MB herbarium scan from a
# museum server. "500x" means 500 px wide, like iNaturalist's "medium" size, enough for a
# 224 px model input. The path ends in the md5 of the media identifier (GBIF's scheme).
GBIF_IMAGE_CACHE_URL = "https://api.gbif.org/v1/image/cache/500x/occurrence/{key}/media/{md5}"

# iNaturalist's research-grade dataset on GBIF; `inat.py` downloads it directly.
INATURALIST_DATASET_KEY = "50c9509d-22c7-4a22-a47d-8c48425ef4a7"

# "Pl@ntNet automatically identified occurrences": GBIF lists them as HUMAN_OBSERVATION, but
# the dataset description says the species was named by Pl@ntNet's classifier alone. A model's
# guess is not a verified label, so the dataset is skipped (checked on api.gbif.org 2026-10-23).
PLANTNET_AUTOMATIC_DATASET_KEY = "14d5676a-2c54-4f94-9023-1e8dcd822aa0"

DATASETS_SKIPPED: frozenset[str] = frozenset({INATURALIST_DATASET_KEY, PLANTNET_AUTOMATIC_DATASET_KEY})

# Citizen-science portals that publish to GBIF, named in the label source so their rows can
# be found (and dropped) later. Pl@ntNet's "observations" set holds species names its
# community or its review considers valid; observation.org records are checked by its
# volunteer validators. Keys checked on api.gbif.org 2026-10-23.
PORTAL_DATASET_NAMES: dict[str, str] = {
    "7a3679ef-5582-4aaa-81f0-8c2545cafc81": "Pl@ntNet observations",
    "8a863029-f435-446a-821e-275f4f641165": "observation.org",
}

# Record licences GBIF can filter on. GBIF only publishes these three; a record's photos
# may still carry their own, stricter licence, which `select_photos` checks per photo.
GBIF_RECORD_LICENSES: tuple[str, ...] = ("CC0_1_0", "CC_BY_4_0", "CC_BY_NC_4_0")

# Kinds of record whose identification was made by a person. Machine observations (camera
# traps, automated classifiers) and fossils are left out: a classifier's guess is not a
# verified label, and a fossil does not look like a living plant.
HUMAN_IDENTIFIED_BASES: tuple[str, ...] = (
    "HUMAN_OBSERVATION",
    "PRESERVED_SPECIMEN",
    "LIVING_SPECIMEN",
    "MATERIAL_SAMPLE",
)

# Largest page the occurrence search returns; it also refuses offsets past 100,000.
OCCURRENCES_PER_PAGE = 300
MAX_SEARCH_OFFSET = 100_000


def fetch_occurrences(
    taxon_key: int, max_occurrences: int, bases_of_record: tuple[str, ...] = HUMAN_IDENTIFIED_BASES
) -> Iterator[dict]:
    """Yields occurrences of a taxon that have a still image and an allowed record licence.

    Records from DATASETS_SKIPPED are dropped here, not in the query, because the search API
    has no "not this dataset" filter.
    """
    offset = 0
    yielded = 0
    while yielded < max_occurrences and offset < MAX_SEARCH_OFFSET:
        page = get_json(
            GBIF_OCCURRENCE_SEARCH_URL,
            {
                "taxonKey": taxon_key,
                "mediaType": "StillImage",
                "license": list(GBIF_RECORD_LICENSES),
                "basisOfRecord": list(bases_of_record),
                "limit": OCCURRENCES_PER_PAGE,
                "offset": offset,
            },
        )
        for occurrence in page["results"]:
            if occurrence.get("datasetKey") in DATASETS_SKIPPED:
                continue
            yield occurrence
            yielded += 1
            if yielded >= max_occurrences:
                return
        if page.get("endOfRecords", True):
            return
        offset += OCCURRENCES_PER_PAGE


def select_photos(
    occurrence: dict, class_name: str, max_photos_per_occurrence: int
) -> list[PhotoToDownload]:
    """Picks the still images of one occurrence whose own licence is allowed.

    A photo's licence is its media licence when it has one, else the record's. Media can be
    stricter than the record (observation.org publishes CC BY-NC records with CC BY-NC-ND
    photos), so a record licence alone is not enough. Photos are capped per occurrence so one
    well-photographed specimen does not outweigh many plants.
    """
    basis = occurrence.get("basisOfRecord")
    if basis not in HUMAN_IDENTIFIED_BASES or occurrence.get("datasetKey") in DATASETS_SKIPPED:
        return []
    record_license = occurrence.get("license") or ""
    selected = []
    for media in occurrence.get("media", []):
        if len(selected) >= max_photos_per_occurrence:
            break
        identifier = media.get("identifier")
        # Some publishers only link a tiled viewer ("references"), which is not an image file.
        if media.get("type") != "StillImage" or not identifier:
            continue
        license_code = normalize_license_code(media.get("license") or record_license)
        if license_code not in ALLOWED_LICENSES:
            continue
        identifier_md5 = hashlib.md5(identifier.encode(), usedforsecurity=False).hexdigest()
        occurrence_key = occurrence["key"]
        selected.append(
            PhotoToDownload(
                url=GBIF_IMAGE_CACHE_URL.format(key=occurrence_key, md5=identifier_md5),
                record_without_file={
                    "image_path": f"gbif/{occurrence_key}-{identifier_md5[:12]}.jpg",
                    "class_name": class_name,
                    "source": "gbif",
                    "source_id": f"{occurrence_key}-{identifier_md5[:12]}",
                    "group_id": f"gbif-{_group_name(occurrence)}",
                    "license": license_code,
                    "attribution": _attribution(media, occurrence, license_code),
                    "label_source": _label_source(occurrence, basis),
                    "label_status": LabelStatus.VERIFIED,
                    "labelled_on": _date_only(
                        occurrence.get("dateIdentified") or occurrence.get("eventDate")
                    ),
                },
            )
        )
    return selected


def _label_source(occurrence: dict, basis: str) -> str:
    dataset_key = occurrence.get("datasetKey", "unknown")
    portal = PORTAL_DATASET_NAMES.get(dataset_key)
    dataset = f"{portal}, dataset {dataset_key}" if portal else f"dataset {dataset_key}"
    return f"gbif {basis.lower()} occurrence {occurrence['key']} ({dataset})"


def _group_name(occurrence: dict) -> str:
    """The collector or observer, else the institution, else the dataset.

    The same person photographs the same field (or collects the same population), so their
    photos must not straddle train and test. The dataset is the last resort: coarse, but it
    never splits one source's look across splits.
    """
    recorded_by = (occurrence.get("recordedBy") or "").strip()
    if recorded_by:
        return f"recorded-by-{recorded_by.lower()}"
    institution = (occurrence.get("institutionCode") or "").strip()
    if institution:
        return f"institution-{institution.lower()}"
    return f"dataset-{occurrence.get('datasetKey', 'unknown')}"


def _attribution(media: dict, occurrence: dict, license_code: str) -> str:
    author = (
        media.get("creator")
        or media.get("rightsHolder")
        or occurrence.get("rightsHolder")
        or occurrence.get("recordedBy")
        or occurrence.get("institutionCode")
        or "unknown"
    )
    return f"(c) {author}, {license_code}, via GBIF occurrence {occurrence['key']}"


def _date_only(value: str | None) -> str:
    # GBIF dates may be "2023-04-14T00:00:00" or ranges like "2019-05-01/2019-06-30"; keep
    # the first date.
    return (value or "").split("/")[0][:10]
