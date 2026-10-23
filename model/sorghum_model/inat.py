"""Downloads research-grade, openly licensed photos from iNaturalist.

Research grade means at least two thirds of identifiers agree on the species, which is the
label verification we rely on for iNaturalist photos. This is a developer tool that runs on a
workstation; nothing here ships in the app.
"""

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sorghum_model.manifest import ALLOWED_LICENSES, ImageRecord, sha256_of_file

INAT_OBSERVATIONS_URL = "https://api.inaturalist.org/v1/observations"

# iNaturalist asks API clients to stay at or below about one request per second.
SECONDS_BETWEEN_API_REQUESTS = 1.0

# Largest page the observations endpoint returns.
OBSERVATIONS_PER_PAGE = 200

USER_AGENT = "sorghum-model-training/0.1 (offline sorghum identification research)"


@dataclass(frozen=True)
class PhotoToDownload:
    """A photo selected from an observation, before its file exists locally."""

    url: str
    record_without_file: dict[str, str]


def fetch_observations(taxon_id: int, max_observations: int) -> Iterator[dict]:
    """Yields research-grade observations of a taxon that have a photo with an allowed licence.

    Pages by ascending observation id (`id_above`), which the API supports past the 10,000
    result limit of page numbers.
    """
    last_id = 0
    yielded = 0
    while yielded < max_observations:
        query = urllib.parse.urlencode(
            {
                "taxon_id": taxon_id,
                "quality_grade": "research",
                "photo_license": ",".join(sorted(ALLOWED_LICENSES)),
                "order_by": "id",
                "order": "asc",
                "id_above": last_id,
                "per_page": OBSERVATIONS_PER_PAGE,
            }
        )
        page = _get_json(f"{INAT_OBSERVATIONS_URL}?{query}")
        observations = page["results"]
        if not observations:
            return
        for observation in observations:
            yield observation
            yielded += 1
            if yielded >= max_observations:
                return
        last_id = observations[-1]["id"]
        time.sleep(SECONDS_BETWEEN_API_REQUESTS)


def select_photos(
    observation: dict, class_name: str, max_photos_per_observation: int
) -> list[PhotoToDownload]:
    """Picks the photos of one observation whose licence is in ALLOWED_LICENSES.

    The observation filter matches when any photo has an allowed licence, so each photo is
    checked again here. Photos are capped per observation so one well-photographed plant does
    not outweigh many plants.
    """
    selected = []
    for photo in observation.get("photos", []):
        if len(selected) >= max_photos_per_observation:
            break
        license_code = photo.get("license_code")
        if license_code not in ALLOWED_LICENSES:
            continue
        photo_id = str(photo["id"])
        # The API returns the "square" thumbnail URL; "medium" is 500 px on the long side,
        # enough for a 224 px model input.
        url = photo["url"].replace("/square.", "/medium.")
        extension = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
        selected.append(
            PhotoToDownload(
                url=url,
                record_without_file={
                    "image_path": f"inaturalist/{photo_id}{extension}",
                    "class_name": class_name,
                    "source": "inaturalist",
                    "source_id": photo_id,
                    "group_id": f"inaturalist-user-{observation['user']['id']}",
                    "license": license_code,
                    "attribution": photo.get("attribution", ""),
                    "label_source": f"inaturalist research-grade observation {observation['id']}",
                    "labelled_on": observation.get("observed_on") or "",
                },
            )
        )
    return selected


def download_photo(photo: PhotoToDownload, data_root: Path) -> ImageRecord:
    """Downloads a photo unless it is already on disk, and returns its manifest row."""
    destination = data_root / photo.record_without_file["image_path"]
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        request = urllib.request.Request(photo.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            partial.write_bytes(response.read())
        # Rename only after a complete download, so an interrupted run never leaves a
        # truncated image that a later run would mistake for a finished one.
        partial.rename(destination)
    return ImageRecord(**photo.record_without_file, sha256=sha256_of_file(destination))


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)
