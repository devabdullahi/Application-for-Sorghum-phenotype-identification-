"""Downloads public Mendeley Data datasets and lays them out for `import_folder`.

Two CC BY 4.0 sets from the research notes add sorghum photos that iNaturalist lacks:
SorghumWeedDataset_Classification (young sorghum next to grass and broadleaf weeds) and the
Sorghum Disease Image Dataset (diseased leaves, panicles and grain). Both are public and need
no API key. The licence is read from the dataset's own metadata before anything is imported,
and every file is checked against the sha256 Mendeley publishes for it.

API: https://data.mendeley.com/public-api/datasets/<id> returns the latest version's
metadata, licence and file list.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sorghum_model.dataset_layout import extract_zip, sorghum_disease_path, sorghum_weed_path
from sorghum_model.downloads import download_file, get_json
from sorghum_model.manifest import ALLOWED_LICENSES, normalize_license_code

MENDELEY_DATASET_URL = "https://data.mendeley.com/public-api/datasets/{dataset_id}"


class DatasetLayout(Enum):
    """How a dataset's files become `<class>/<group>/<file>` photos."""

    ZIP = "zip"
    """One archive; its entries are mapped and extracted."""

    FILES = "files"
    """Loose photos; each is downloaded straight to its mapped path."""


@dataclass(frozen=True)
class MendeleyDataset:
    """A Mendeley dataset we import, pinned to the version we checked.

    Attributes:
        source: manifest source name; also the folder below the data root.
        dataset_id: Mendeley's id, as in data.mendeley.com/datasets/<id>.
        version: the version whose layout `path_for_file` understands. A newer version on the
            server stops the import, because its layout or labels may have changed.
        layout: whether the photos come as one archive or as loose files.
        path_for_file: maps an archive entry or file name to `<class>/<group>/<file>`, given
            the images-per-group setting, or None to skip it.
    """

    source: str
    dataset_id: str
    version: int
    layout: DatasetLayout
    path_for_file: Callable[[str, int], str | None]


MENDELEY_DATASETS: dict[str, MendeleyDataset] = {
    "sorghum-weed": MendeleyDataset(
        source="sorghum-weed-2023",
        dataset_id="4gkcyxjyss",
        version=1,
        layout=DatasetLayout.ZIP,
        path_for_file=sorghum_weed_path,
    ),
    "sorghum-disease": MendeleyDataset(
        source="sorghum-disease-2024",
        dataset_id="fgb3cmfrg2",
        version=1,
        layout=DatasetLayout.FILES,
        path_for_file=sorghum_disease_path,
    ),
}


def fetch_dataset(dataset: MendeleyDataset) -> dict:
    """Returns the dataset's metadata, refusing a version other than the pinned one."""
    metadata = get_json(MENDELEY_DATASET_URL.format(dataset_id=dataset.dataset_id))
    if metadata.get("version") != dataset.version:
        raise ValueError(
            f"Mendeley {dataset.dataset_id} is now version {metadata.get('version')}, not "
            f"{dataset.version}; check its layout and licence, then update MENDELEY_DATASETS"
        )
    return metadata


def dataset_license_code(metadata: dict) -> str:
    """Returns the dataset's licence code, or raises ValueError if training may not use it."""
    licence = metadata.get("data_licence") or {}
    code = normalize_license_code(licence.get("short_name") or licence.get("url") or "")
    if code not in ALLOWED_LICENSES:
        raise ValueError(
            f"Mendeley {metadata.get('id')}: licence {licence.get('short_name')!r} is not allowed"
        )
    return code


def dataset_attribution(metadata: dict) -> str:
    """The credit line CC BY asks for: authors, title, DOI and licence."""
    authors = dataset_authors(metadata)
    doi = (metadata.get("doi") or {}).get("id", "")
    licence = (metadata.get("data_licence") or {}).get("short_name", "")
    return f"{authors}, {metadata.get('name', '')}, Mendeley Data, doi:{doi}, {licence}"


def dataset_authors(metadata: dict) -> str:
    """The dataset's authors, who are the annotators of its labels."""
    names = [
        f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
        for c in metadata.get("contributors", [])
    ]
    return ", ".join(name for name in names if name) or "dataset authors"


def download_and_lay_out(
    dataset: MendeleyDataset, metadata: dict, dataset_root: Path, images_per_group: int
) -> int:
    """Downloads the dataset's files and places its photos below `dataset_root/images`.

    Returns the number of photos in place. Finished files are skipped, so a re-run resumes.
    """
    images_root = dataset_root / "images"
    files = metadata.get("files", [])
    if dataset.layout is DatasetLayout.ZIP:
        placed = 0
        for file in files:
            if not file["filename"].lower().endswith(".zip"):
                continue
            archive = dataset_root / "archives" / file["filename"]
            download_file(
                file["content_details"]["download_url"],
                archive,
                expected_sha256=file["content_details"].get("sha256_hash"),
            )
            placed += extract_zip(
                archive, images_root, lambda name: dataset.path_for_file(name, images_per_group)
            )
        return placed

    placed = 0
    for file in files:
        relative = dataset.path_for_file(file["filename"], images_per_group)
        if relative is None:
            continue
        download_file(
            file["content_details"]["download_url"],
            images_root / relative,
            expected_sha256=file["content_details"].get("sha256_hash"),
        )
        placed += 1
    return placed
