"""Command line for the species-head pipeline: download, import, split, train, export.

Each photo source has its own command and writes its own manifest
(`manifests/species-<source>.csv`), so several downloads can run at once without sharing a
file.

Run `uv run sorghum-model --help` from `model/`. See model/README.md for the full workflow.
"""

import argparse
import datetime
import http.client
import sys
from collections.abc import Iterable
from pathlib import Path

from sorghum_model.manifest import (
    ImageRecord,
    merge_manifests,
    read_manifest,
    sha256_of_file,
    write_manifest,
)
from sorghum_model.settings import (
    ExportSettings,
    PublicDatasetSettings,
    SplitSettings,
    TrainingSettings,
)
from sorghum_model.species_classes import SPECIES_CLASS_NAMES, SPECIES_CLASSES
from sorghum_model.splits import (
    count_per_class_and_split,
    read_split_manifest,
    split_records,
    write_split_manifest,
)

MODEL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = MODEL_DIR / "data"
DEFAULT_MANIFEST_DIR = MODEL_DIR / "manifests"
DEFAULT_INAT_MANIFEST = DEFAULT_MANIFEST_DIR / "species-inaturalist.csv"
DEFAULT_SPLIT_MANIFEST = MODEL_DIR / "splits" / "species-v1.csv"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sorghum-model", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    _add_inat_download(commands)
    _add_gbif_download(commands)
    _add_commons_download(commands)
    _add_flickr_download(commands)
    _add_mendeley_import(commands)
    _add_figshare_import(commands)
    _add_import_folder(commands)
    _add_split(commands)
    _add_train(commands)
    _add_export(commands)
    arguments = parser.parse_args(argv)
    try:
        arguments.run(arguments)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _add_inat_download(commands) -> None:
    command = commands.add_parser(
        "inat-download",
        help="Download research-grade iNaturalist photos (CC0, CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA).",
    )
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--manifest", type=Path, default=DEFAULT_INAT_MANIFEST)
    _add_class_filter(command)
    command.add_argument("--max-observations-per-taxon", type=int, default=3000)
    command.add_argument("--max-photos-per-observation", type=int, default=3)
    command.set_defaults(run=_run_inat_download)


def _run_inat_download(arguments) -> None:
    # Source modules are imported inside the commands so the other commands do not depend on
    # network code.
    from sorghum_model import inat

    for species in _selected_classes(arguments.class_names, lambda c: c.inat_taxon_ids):
        photos = (
            photo
            for taxon_id in species.inat_taxon_ids
            for observation in inat.fetch_observations(taxon_id, arguments.max_observations_per_taxon)
            for photo in inat.select_photos(
                observation, species.name, arguments.max_photos_per_observation
            )
        )
        _download_class(photos, species.name, arguments.data_root, arguments.manifest)


def _add_gbif_download(commands) -> None:
    command = commands.add_parser(
        "gbif-download",
        help="Download human-identified GBIF occurrence photos (iNaturalist's dataset excluded).",
    )
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_DIR / "species-gbif.csv")
    _add_class_filter(command)
    command.add_argument("--max-occurrences-per-taxon", type=int, default=2000)
    command.add_argument("--max-photos-per-occurrence", type=int, default=2)
    command.set_defaults(run=_run_gbif_download)


def _run_gbif_download(arguments) -> None:
    from sorghum_model import gbif

    for species in _selected_classes(arguments.class_names, lambda c: c.gbif_taxon_keys):
        photos = (
            photo
            for taxon_key in species.gbif_taxon_keys
            for occurrence in gbif.fetch_occurrences(taxon_key, arguments.max_occurrences_per_taxon)
            for photo in gbif.select_photos(
                occurrence, species.name, arguments.max_photos_per_occurrence
            )
        )
        _download_class(photos, species.name, arguments.data_root, arguments.manifest)


def _add_commons_download(commands) -> None:
    command = commands.add_parser(
        "commons-download", help="Download openly licensed Wikimedia Commons category photos."
    )
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument(
        "--manifest", type=Path, default=DEFAULT_MANIFEST_DIR / "species-commons.csv"
    )
    _add_class_filter(command)
    command.add_argument("--max-files-per-category", type=int, default=2000)
    command.set_defaults(run=_run_commons_download)


def _run_commons_download(arguments) -> None:
    from sorghum_model import commons

    for species in _selected_classes(arguments.class_names, lambda c: c.commons_categories):
        photos = (
            photo
            for category in species.commons_categories
            for page in commons.fetch_category_files(category, arguments.max_files_per_category)
            if (photo := commons.select_photo(page, species.name, category)) is not None
        )
        _download_class(photos, species.name, arguments.data_root, arguments.manifest)


def _add_flickr_download(commands) -> None:
    command = commands.add_parser(
        "flickr-download",
        help="Download openly licensed Flickr photos for no_plant (needs FLICKR_API_KEY).",
    )
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_DIR / "species-flickr.csv")
    command.add_argument("--max-photos-per-search", type=int, default=500)
    command.set_defaults(run=_run_flickr_download)


def _run_flickr_download(arguments) -> None:
    from sorghum_model import flickr

    api_key = flickr.api_key_from_environment()
    for class_name, searches in flickr.FLICKR_SEARCHES.items():
        photos = (
            photo
            for text in searches
            for result in flickr.search_photos(api_key, text, arguments.max_photos_per_search)
            if (photo := flickr.select_photo(result, class_name, text)) is not None
        )
        _download_class(photos, class_name, arguments.data_root, arguments.manifest)


def _add_mendeley_import(commands) -> None:
    from sorghum_model.mendeley import MENDELEY_DATASETS

    command = commands.add_parser(
        "mendeley-import", help="Download a public Mendeley Data dataset and import its photos."
    )
    command.add_argument("dataset", choices=sorted(MENDELEY_DATASETS))
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--manifest", type=Path, help="Default: manifests/species-<source>.csv.")
    command.set_defaults(run=_run_mendeley_import)


def _run_mendeley_import(arguments) -> None:
    from sorghum_model import mendeley

    dataset = mendeley.MENDELEY_DATASETS[arguments.dataset]
    metadata = mendeley.fetch_dataset(dataset)
    # Checked before downloading anything, so a relicensed dataset never reaches the disk.
    license_code = mendeley.dataset_license_code(metadata)
    dataset_root = arguments.data_root / dataset.source
    placed = mendeley.download_and_lay_out(
        dataset, metadata, dataset_root, PublicDatasetSettings().images_per_sequence_group
    )
    print(f"{dataset.source}: {placed} photos laid out in {dataset_root / 'images'}")
    _import_laid_out_dataset(
        dataset_root / "images",
        arguments,
        source=dataset.source,
        license_code=license_code,
        attribution=mendeley.dataset_attribution(metadata),
        annotator=mendeley.dataset_authors(metadata),
        labelled_on=(metadata.get("publish_date") or "")[:10],
    )


def _add_figshare_import(commands) -> None:
    from sorghum_model.figshare import FIGSHARE_DATASETS

    command = commands.add_parser(
        "figshare-import", help="Download a GrainSet archive from Figshare and import a sample."
    )
    command.add_argument("dataset", choices=sorted(FIGSHARE_DATASETS))
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--manifest", type=Path, help="Default: manifests/species-<source>.csv.")
    command.set_defaults(run=_run_figshare_import)


def _run_figshare_import(arguments) -> None:
    from sorghum_model import figshare

    dataset = figshare.FIGSHARE_DATASETS[arguments.dataset]
    article = figshare.fetch_article(dataset)
    license_code = figshare.article_license_code(article)
    dataset_root = arguments.data_root / dataset.source
    placed = figshare.download_and_lay_out(
        dataset, article, dataset_root, PublicDatasetSettings().grain_images_per_class
    )
    print(f"{dataset.source}: {placed} photos laid out in {dataset_root / 'images'}")
    _import_laid_out_dataset(
        dataset_root / "images",
        arguments,
        source=dataset.source,
        license_code=license_code,
        attribution=figshare.article_attribution(article),
        annotator=figshare.article_authors(article),
        labelled_on=(article.get("published_date") or "")[:10],
    )


def _import_laid_out_dataset(
    images_root: Path,
    arguments,
    *,
    source: str,
    license_code: str,
    attribution: str,
    annotator: str,
    labelled_on: str,
) -> None:
    """Imports a `<class>/<group>/<file>` folder and replaces the source's manifest."""
    from sorghum_model.local_import import FolderSource, GroupBy, import_class_folders

    folder_source = FolderSource(
        class_name="",  # set per class folder by import_class_folders
        source=source,
        license=license_code,
        attribution=attribution,
        annotator=annotator,
        labelled_on=labelled_on or datetime.date.today().isoformat(),
        group_by=GroupBy.SUBFOLDER,
    )
    records = import_class_folders(images_root, arguments.data_root, folder_source)
    manifest = arguments.manifest or DEFAULT_MANIFEST_DIR / f"species-{source}.csv"
    write_manifest(records, manifest)
    counts = {name: sum(r.class_name == name for r in records) for name in SPECIES_CLASS_NAMES}
    per_class = ", ".join(f"{name} {count}" for name, count in counts.items() if count)
    print(f"{source}: {len(records)} photos -> {manifest} ({per_class})")


def _add_class_filter(command) -> None:
    command.add_argument(
        "--class", dest="class_names", action="append", choices=SPECIES_CLASS_NAMES,
        help="Only these classes (repeatable). Default: every class this source covers.",
    )


def _selected_classes(class_names: list[str] | None, source_ids) -> list:
    """Classes the source covers (non-empty `source_ids(c)`), limited to `class_names` if given."""
    return [
        c for c in SPECIES_CLASSES
        if source_ids(c) and (not class_names or c.name in class_names)
    ]


def _download_class(
    photos: Iterable, class_name: str, data_root: Path, manifest: Path
) -> None:
    """Downloads one class's photos and replaces that class's rows in the source's manifest.

    The manifest is saved after each class, so an interrupted run keeps the classes already
    finished; files already on disk are not downloaded again. A photo listed twice (one
    Commons file in two categories) is kept once.
    """
    from sorghum_model.downloads import download_photo

    records: dict[str, ImageRecord] = {}
    failures = 0
    for photo in photos:
        image_path = photo.record_without_file["image_path"]
        if image_path in records:
            continue
        try:
            records[image_path] = download_photo(photo, data_root)
        except (OSError, http.client.HTTPException) as error:
            # One dead link must not stop a run of thousands; the count is reported below.
            failures += 1
            print(f"warning: skipped {photo.url}: {error}", file=sys.stderr)
    existing = read_manifest(manifest) if manifest.exists() else []
    kept = [r for r in existing if r.class_name != class_name]
    write_manifest(kept + list(records.values()), manifest)
    print(
        f"{class_name}: {len(records)} photos, {failures} failed downloads -> {manifest}",
        flush=True,
    )


def _add_import_folder(commands) -> None:
    command = commands.add_parser(
        "import-folder", help="Add a folder of labelled photos (public dataset or our own)."
    )
    command.add_argument("folder", type=Path)
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--class", dest="class_name", required=True, choices=SPECIES_CLASS_NAMES)
    command.add_argument("--source", required=True, help="Short dataset name, e.g. sorghum-weed-2023.")
    command.add_argument(
        "--license", required=True, help="cc0, cc-by, cc-by-sa, cc-by-nc or cc-by-nc-sa."
    )
    command.add_argument("--attribution", required=True)
    command.add_argument("--annotator", required=True, help="Who verified the labels.")
    command.add_argument("--labelled-on", required=True, help="ISO date of the labelling.")
    command.add_argument("--group-by", choices=["subfolder", "file"], default="subfolder")
    command.add_argument(
        "--manifest", type=Path,
        help="Default: manifests/species-<source>.csv. Rows for this source and class are replaced.",
    )
    command.set_defaults(run=_run_import_folder)


def _run_import_folder(arguments) -> None:
    from sorghum_model.local_import import FolderSource, GroupBy, import_folder

    manifest = arguments.manifest or DEFAULT_MANIFEST_DIR / f"species-{arguments.source}.csv"
    source = FolderSource(
        class_name=arguments.class_name,
        source=arguments.source,
        license=arguments.license,
        attribution=arguments.attribution,
        annotator=arguments.annotator,
        labelled_on=arguments.labelled_on,
        group_by=GroupBy(arguments.group_by),
    )
    records = import_folder(arguments.folder, arguments.data_root, source)
    existing = read_manifest(manifest) if manifest.exists() else []
    kept = [r for r in existing if (r.source, r.class_name) != (source.source, source.class_name)]
    write_manifest(kept + records, manifest)
    print(f"{source.class_name}: {len(records)} photos from {arguments.folder} -> {manifest}")


def _add_split(commands) -> None:
    command = commands.add_parser("split", help="Assign every photo to train/validation/test by group.")
    command.add_argument("--manifest", dest="manifests", type=Path, action="append")
    command.add_argument("--out", type=Path, default=DEFAULT_SPLIT_MANIFEST)
    command.set_defaults(run=_run_split)


def _run_split(arguments) -> None:
    records = _load_manifests(arguments.manifests)
    settings = SplitSettings()
    splits = split_records(records, settings.validation_fraction, settings.test_fraction, settings.salt)
    write_split_manifest(records, splits, arguments.out)
    for (class_name, split), count in sorted(
        count_per_class_and_split(records, splits).items(), key=lambda i: (i[0][0], i[0][1].value)
    ):
        print(f"{class_name:15} {split.value:10} {count}")


def _add_train(commands) -> None:
    command = commands.add_parser("train", help="Train the species head (needs the train extra).")
    command.add_argument("--manifest", dest="manifests", type=Path, action="append")
    command.add_argument("--splits", type=Path, default=DEFAULT_SPLIT_MANIFEST)
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--run-dir", type=Path, required=True)
    command.set_defaults(run=_run_train)


def _run_train(arguments) -> None:
    from sorghum_model.train import train_species_model

    records, splits = _load_records_and_splits(arguments.manifests, arguments.splits)
    train_species_model(records, splits, arguments.data_root, arguments.run_dir, TrainingSettings())
    print(f"trained model in {arguments.run_dir}")


def _add_export(commands) -> None:
    command = commands.add_parser(
        "export", help="Write traits-vN.tflite/.json and parity fixtures from a trained run."
    )
    command.add_argument("--manifest", dest="manifests", type=Path, action="append")
    command.add_argument("--splits", type=Path, default=DEFAULT_SPLIT_MANIFEST)
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--run-dir", type=Path, required=True)
    command.add_argument("--version", type=int, required=True, help="Model version N.")
    command.add_argument("--out-dir", type=Path, required=True)
    command.add_argument(
        "--fixtures-dir", type=Path, required=True,
        help="Normally ../shared/src/commonTest/resources/species (parity tests read it).",
    )
    command.set_defaults(run=_run_export)


def _run_export(arguments) -> None:
    from sorghum_model.export import export_model

    records, splits = _load_records_and_splits(arguments.manifests, arguments.splits)
    provenance = {
        "splitManifestSha256": sha256_of_file(arguments.splits),
        "imageManifests": {
            path.name: sha256_of_file(path) for path in _manifest_paths(arguments.manifests)
        },
        "splitSalt": SplitSettings().salt,
    }
    metadata_path = export_model(
        arguments.run_dir, records, splits, arguments.data_root, arguments.version,
        arguments.out_dir, arguments.fixtures_dir, ExportSettings(), provenance,
    )
    print(f"exported {metadata_path}")


def _manifest_paths(manifests: list[Path] | None) -> list[Path]:
    """Explicit manifests, or every committed `manifests/species-*.csv`."""
    paths = manifests or sorted(DEFAULT_MANIFEST_DIR.glob("species-*.csv"))
    if not paths:
        raise ValueError(f"no manifests given and none found in {DEFAULT_MANIFEST_DIR}")
    return paths


def _load_manifests(manifests: list[Path] | None) -> list[ImageRecord]:
    return merge_manifests([read_manifest(path) for path in _manifest_paths(manifests)])


def _load_records_and_splits(manifests, split_manifest: Path):
    records = _load_manifests(manifests)
    splits = read_split_manifest(split_manifest)
    unsplit = [r for r in records if r.sha256 not in splits]
    if unsplit:
        raise ValueError(
            f"{len(unsplit)} photos are not in {split_manifest}; run `sorghum-model split` again"
        )
    return records, splits


if __name__ == "__main__":
    sys.exit(main())
