"""Downloads GrainSet kernel archives from Figshare and lays out a sample for `import_folder`.

GrainSet (Fan et al. 2023, CC BY 4.0) is the largest open source of sorghum grain images,
and its maize set gives the matching look-alike. Each crop is one multi-gigabyte zip of
single-kernel images plus masks. The whole zip is downloaded (resumable, md5-checked against
Figshare's published checksum) and a fixed sample of kernels is extracted
(`PublicDatasetSettings.grain_images_per_class`). No API key is needed.

API: https://api.figshare.com/v2/articles/<id> returns the licence, authors and files.
"""

from dataclasses import dataclass
from pathlib import Path

from sorghum_model.dataset_layout import extract_zip, grainset_path
from sorghum_model.downloads import download_file, get_json
from sorghum_model.manifest import ALLOWED_LICENSES, normalize_license_code

FIGSHARE_ARTICLE_URL = "https://api.figshare.com/v2/articles/{article_id}"


@dataclass(frozen=True)
class FigshareDataset:
    """One Figshare archive we import, pinned to the article version we checked.

    Attributes:
        source: manifest source name; also the folder below the data root.
        article_id: Figshare article id (the number in its DOI, 10.6084/m9.figshare.<id>).
        version: article version whose layout `grainset_path` understands.
        file_name: the archive to download from the article.
        class_name: species class of every image in the archive.
    """

    source: str
    article_id: int
    version: int
    file_name: str
    class_name: str


# Article ids are from the GrainSet paper's data availability section (PMC10632488).
FIGSHARE_DATASETS: dict[str, FigshareDataset] = {
    "grainset-sorghum": FigshareDataset(
        "grainset-sorghum", 22988981, 2, "sorghum.zip", "sorghum_bicolor"
    ),
    "grainset-maize": FigshareDataset("grainset-maize", 22987562, 2, "maize.zip", "maize"),
}


def fetch_article(dataset: FigshareDataset) -> dict:
    """Returns the article's metadata, refusing a version other than the pinned one."""
    article = get_json(FIGSHARE_ARTICLE_URL.format(article_id=dataset.article_id))
    if article.get("version") != dataset.version:
        raise ValueError(
            f"Figshare {dataset.article_id} is now version {article.get('version')}, not "
            f"{dataset.version}; check its layout and licence, then update FIGSHARE_DATASETS"
        )
    return article


def article_license_code(article: dict) -> str:
    """Returns the article's licence code, or raises ValueError if training may not use it."""
    licence = article.get("license") or {}
    code = normalize_license_code(licence.get("name") or licence.get("url") or "")
    if code not in ALLOWED_LICENSES:
        raise ValueError(
            f"Figshare {article.get('id')}: licence {licence.get('name')!r} is not allowed"
        )
    return code


def article_authors(article: dict) -> str:
    """The article's authors, who are the annotators of its labels."""
    names = [a["full_name"] for a in article.get("authors", []) if a.get("full_name")]
    return ", ".join(names) or "dataset authors"


def article_attribution(article: dict) -> str:
    """The credit line CC BY asks for: authors, title, DOI and licence."""
    licence = (article.get("license") or {}).get("name", "")
    return (
        f"{article_authors(article)}, GrainSet {article.get('title', '')}, Figshare, "
        f"doi:{article.get('doi', '')}, {licence}"
    )


def download_and_lay_out(
    dataset: FigshareDataset, article: dict, dataset_root: Path, max_images: int
) -> int:
    """Downloads the archive and extracts a fixed sample below `dataset_root/images`.

    Returns the number of photos in place. The archive is kept, so a larger sample later
    needs no new download.
    """
    files = [f for f in article.get("files", []) if f.get("name") == dataset.file_name]
    if not files:
        raise ValueError(f"Figshare {dataset.article_id} has no file {dataset.file_name!r}")
    file = files[0]
    archive = dataset_root / "archives" / dataset.file_name
    # The download URL redirects to a storage link that expires after seconds, so each
    # (resumed) request starts again from the stable Figshare URL.
    download_file(file["download_url"], archive, expected_md5=file.get("computed_md5"))
    return extract_zip(
        archive,
        dataset_root / "images",
        lambda name: grainset_path(name, dataset.class_name),
        max_images=max_images,
    )
