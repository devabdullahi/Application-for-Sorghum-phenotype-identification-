"""Downloads openly licensed photos from Wikimedia Commons categories.

Commons fills two gaps: crop photos from regions iNaturalist covers thinly (sorghum and
millet fields in Africa and India) and `no_plant` scenes (soil, boards, hands) that no
naturalist site holds. Each class lists its categories in `species_classes.py`.

Labels are weaker than iNaturalist research grade: a category is assigned by the uploader or
an editor, not confirmed by independent identifiers. The label source says so, so a later
cleaning pass (BioCLIP 2 or a person) can find these rows. Licences come from each file's
`extmetadata`. API reference: https://www.mediawiki.org/wiki/API:Categorymembers and
https://www.mediawiki.org/wiki/Extension:CommonsMetadata
"""

import html
import re
from collections.abc import Iterator

from sorghum_model.downloads import PhotoToDownload, get_json
from sorghum_model.manifest import ALLOWED_LICENSES, LabelStatus, normalize_license_code

COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"

# Thumbnail width requested from Commons, like iNaturalist's "medium" size: enough for a
# 224 px model input, and far smaller than the originals (often 20+ megapixels).
THUMBNAIL_WIDTH_PX = 500

# Largest page of category members the API returns to a client without bot rights.
FILES_PER_PAGE = 50

# Commons holds many bulk imports from iNaturalist and Flickr. Those photos are downloaded
# from their own source already (or may be), and the same photo under two sources would leak
# across splits, so a file is skipped when its uploader, credit or author names either site.
# The import tools (iNaturalist2Commons, the Flickr upload bot, Flickr2Commons) all write the
# original's URL into "Credit" or "Artist".
REUPLOADED_FROM_MARKERS: tuple[str, ...] = ("inaturalist", "flickr")

# Photo formats only. Commons categories also hold SVG drawings, PDFs, TIFF scans and videos.
PHOTO_MIME_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/png"})


def fetch_category_files(category: str, max_files: int) -> Iterator[dict]:
    """Yields the file pages directly in a category, with their image info and licence.

    Subcategories are not followed (see `SpeciesClass.commons_categories`).
    """
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "categorymembers",
        "gcmtitle": f"Category:{category}",
        "gcmtype": "file",
        "gcmlimit": FILES_PER_PAGE,
        "prop": "imageinfo",
        "iiprop": "url|mime|user|timestamp|extmetadata",
        "iiurlwidth": THUMBNAIL_WIDTH_PX,
        "iiextmetadatafilter": "License|LicenseShortName|Artist|Credit|DateTimeOriginal",
    }
    yielded = 0
    while yielded < max_files:
        response = get_json(COMMONS_API_URL, params)
        for page in response.get("query", {}).get("pages", []):
            yield page
            yielded += 1
            if yielded >= max_files:
                return
        if "continue" not in response:
            return
        # MediaWiki continuation: send back every key of "continue" with the next request.
        params = params | response["continue"]


def select_photo(page: dict, class_name: str, category: str) -> PhotoToDownload | None:
    """Returns the download for one file page, or None if it is not an allowed photo."""
    infos = page.get("imageinfo") or []
    if not infos:
        return None
    info = infos[0]
    if info.get("mime") not in PHOTO_MIME_TYPES or not info.get("thumburl"):
        return None
    metadata = info.get("extmetadata", {})
    # "License" is a machine code ("cc-by-sa-4.0"); "LicenseShortName" ("CC BY-SA 4.0") is
    # the fallback for files whose template does not set it.
    license_text = _metadata_value(metadata, "License") or _metadata_value(metadata, "LicenseShortName")
    license_code = normalize_license_code(license_text)
    if license_code not in ALLOWED_LICENSES or is_reupload(info, metadata):
        return None

    page_id = str(page["pageid"])
    uploader = info.get("user") or "unknown"
    author = _plain_text(_metadata_value(metadata, "Artist")) or uploader
    # Prefer the date the photo was taken; it is free text, so fall back to the upload date
    # when it is not an ISO date.
    labelled_on = _metadata_value(metadata, "DateTimeOriginal")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", labelled_on):
        labelled_on = info.get("timestamp", "")[:10]
    return PhotoToDownload(
        url=info["thumburl"],
        record_without_file={
            "image_path": f"commons/{page_id}{_suffix(info['mime'])}",
            "class_name": class_name,
            "source": "commons",
            "source_id": page_id,
            # The uploader stands in for the photographer: one person's uploads are usually
            # one trip or one field, so they must stay in one split.
            "group_id": f"commons-user-{uploader.lower()}",
            "license": license_code,
            "attribution": f"(c) {author}, {license_text}, {page.get('title', '')} on Wikimedia Commons",
            "label_source": f"wikimedia commons category '{category}' (editor-assigned)",
            "label_status": LabelStatus.UNREVIEWED,
            "labelled_on": labelled_on,
        },
    )


def is_reupload(info: dict, metadata: dict) -> bool:
    """Whether a Commons file is a copy of an iNaturalist or Flickr photo."""
    provenance = " ".join(
        (info.get("user") or "", _metadata_value(metadata, "Credit"), _metadata_value(metadata, "Artist"))
    ).lower()
    return any(marker in provenance for marker in REUPLOADED_FROM_MARKERS)


def _metadata_value(metadata: dict, key: str) -> str:
    return str(metadata.get(key, {}).get("value", "")).strip()


def _plain_text(value: str) -> str:
    # "Artist" is HTML, usually a link to the user page; the credit line needs plain text.
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def _suffix(mime: str) -> str:
    return ".png" if mime == "image/png" else ".jpg"
