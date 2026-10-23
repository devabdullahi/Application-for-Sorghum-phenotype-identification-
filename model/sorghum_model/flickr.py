"""Downloads openly licensed Flickr photos for the `no_plant` class (needs an API key).

`no_plant` (bare soil, an empty board, a hand) has no naturalist source at all, and Wikimedia
Commons holds only a few hundred such photos. Flickr's search fills that gap. Plant classes
are not searched here: Flickr tags are free text, and a photo tagged "sorghum" is as likely
to be a bowl of porridge as a plant.

Labels come from a text search, so they are unreviewed and the label source says so; review
them (or filter with BioCLIP 2) before training. The key is read from the FLICKR_API_KEY
environment variable (free at https://www.flickr.com/services/apps/create/). API reference:
https://www.flickr.com/services/api/flickr.photos.search.html
"""

import os
from collections.abc import Iterator

from sorghum_model.downloads import PhotoToDownload, get_json

FLICKR_API_URL = "https://api.flickr.com/services/rest/"
FLICKR_API_KEY_VARIABLE = "FLICKR_API_KEY"

# Flickr licence ids we may train on (flickr.photos.licenses.getInfo, checked 2026-10-23).
# ND licences (3, 6, 13, 16), all rights reserved (0) and public-domain marks (7, 8, 10) are
# left out, matching ALLOWED_LICENSES.
FLICKR_LICENSES: dict[str, str] = {
    "1": "cc-by-nc-sa",  # CC BY-NC-SA 2.0
    "2": "cc-by-nc",  # CC BY-NC 2.0
    "4": "cc-by",  # CC BY 2.0
    "5": "cc-by-sa",  # CC BY-SA 2.0
    "9": "cc0",  # CC0
    "11": "cc-by",  # CC BY 4.0
    "12": "cc-by-sa",  # CC BY-SA 4.0
    "14": "cc-by-nc",  # CC BY-NC 4.0
    "15": "cc-by-nc-sa",  # CC BY-NC-SA 4.0
}

# Searches per class. Each describes what the camera sees when the sample is missing.
FLICKR_SEARCHES: dict[str, tuple[str, ...]] = {
    "no_plant": (
        "bare soil",
        "dry soil texture",
        "plywood board",
        "wooden board texture",
        "open hand palm",
    ),
}

# Largest page flickr.photos.search returns.
PHOTOS_PER_PAGE = 250


def api_key_from_environment() -> str:
    """Returns the Flickr key, or raises ValueError explaining how to set it."""
    key = os.environ.get(FLICKR_API_KEY_VARIABLE, "").strip()
    if not key:
        raise ValueError(
            f"{FLICKR_API_KEY_VARIABLE} is not set. Create a free key at "
            "https://www.flickr.com/services/apps/create/ and export it before running "
            "flickr-download (see model/README.md)."
        )
    return key


def search_photos(api_key: str, text: str, max_photos: int) -> Iterator[dict]:
    """Yields photos matching `text` whose licence is in FLICKR_LICENSES."""
    page_number = 1
    yielded = 0
    while yielded < max_photos:
        response = get_json(
            FLICKR_API_URL,
            {
                "method": "flickr.photos.search",
                "api_key": api_key,
                "text": text,
                "license": ",".join(FLICKR_LICENSES),
                "content_types": "0",  # photos only, no screenshots or drawings
                "media": "photos",
                "extras": "license,owner_name,date_taken,url_m",
                "per_page": PHOTOS_PER_PAGE,
                "page": page_number,
                "format": "json",
                "nojsoncallback": "1",
            },
        )
        if response.get("stat") != "ok":
            raise ValueError(f"Flickr search {text!r} failed: {response.get('message')}")
        photos = response["photos"]
        for photo in photos["photo"]:
            yield photo
            yielded += 1
            if yielded >= max_photos:
                return
        if page_number >= int(photos.get("pages", 0)):
            return
        page_number += 1


def select_photo(photo: dict, class_name: str, search_text: str) -> PhotoToDownload | None:
    """Returns the download for one search result, or None if it cannot be used."""
    license_code = FLICKR_LICENSES.get(str(photo.get("license")))
    # "url_m" is the 500 px size, like iNaturalist's "medium"; it is missing for photos whose
    # owner disabled downloads.
    if license_code is None or not photo.get("url_m"):
        return None
    photo_id = str(photo["id"])
    owner = photo.get("ownername") or photo.get("owner", "unknown")
    return PhotoToDownload(
        url=photo["url_m"],
        record_without_file={
            "image_path": f"flickr/{photo_id}.jpg",
            "class_name": class_name,
            "source": "flickr",
            "source_id": photo_id,
            # One owner's photos are one person's surroundings and camera.
            "group_id": f"flickr-owner-{photo.get('owner', 'unknown')}",
            "license": license_code,
            "attribution": f"(c) {owner}, {license_code}, flickr.com/photos/{photo.get('owner')}/{photo_id}",
            "label_source": f"flickr search '{search_text}' (unreviewed)",
            "labelled_on": (photo.get("datetaken") or "")[:10],
        },
    )
