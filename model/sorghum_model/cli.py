"""Command line for the species-head pipeline: download, import, split, train, export.

Each photo source has its own command and writes its own manifest
(`manifests/species-<source>.csv`), so several sources can download at once without sharing
a file. Run one process per source: a lock file next to the manifest refuses a second one.

Run `uv run sorghum-model --help` from `model/`. See model/README.md for the full workflow.
"""

import argparse
import http.client
import json
import signal
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sorghum_model.manifest import (
    ImageRecord,
    LabelStatus,
    manifest_lock,
    merge_manifests,
    read_manifest,
    sha256_of_file,
    verified_records,
    write_manifest,
)
from sorghum_model.settings import (
    CoreShortlistSettings,
    DownloadSettings,
    ExportSettings,
    GrinDescriptorSettings,
    LabelReviewSettings,
    MfwdEvaluationSettings,
    PublicDatasetSettings,
    RaceCrosswalkSettings,
    RaceGateSettings,
    RaceRuleSearchSettings,
    RaceTrainingSettings,
    SpeciesDecisionSettings,
    SplitSettings,
    TrainingSettings,
    TraitGateSettings,
    TraitLabelSettings,
    TraitTrainingSettings,
)
from sorghum_model.species_classes import SPECIES_CLASS_NAMES, SPECIES_CLASSES
from sorghum_model.splits import (
    Split,
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
DEFAULT_CULTIVAR_DATA_ROOT = DEFAULT_DATA_ROOT / "cultivar"
DEFAULT_GRIN_MANIFEST = DEFAULT_MANIFEST_DIR / "cultivar-grin.csv"
DEFAULT_GRIN_DESCRIPTORS = DEFAULT_MANIFEST_DIR / "cultivar-grin-descriptors.csv"
# GRIN pages saved by grin-descriptors; cultivar-split reads the image study pages from here.
DEFAULT_GRIN_PAGE_CACHE = DEFAULT_CULTIVAR_DATA_ROOT / "grin-descriptor-pages"
DEFAULT_CULTIVAR_SPLIT = MODEL_DIR / "splits" / "cultivar-grin-v1.csv"
# Race crosswalk (race_crosswalk.py): GRIN search and detail pages are cached apart from the
# study pages, and the Frontiers workbook is downloaded next to them.
DEFAULT_GRIN_ACCESSION_PAGE_CACHE = DEFAULT_CULTIVAR_DATA_ROOT / "grin-accession-pages"
DEFAULT_FRONTIERS_TABLE = DEFAULT_CULTIVAR_DATA_ROOT / "frontiers-2023" / "tables.xlsx"
DEFAULT_RACE_CROSSWALK = DEFAULT_MANIFEST_DIR / "race-crosswalk-frontiers.csv"
DEFAULT_CORE_SHORTLIST = DEFAULT_MANIFEST_DIR / "core-accession-shortlist.csv"
# Names the cultivar split scheme; see SplitSettings.salt.
CULTIVAR_SPLIT_SALT = "cultivar-grin-v1"
# Same cadence as the species downloaders: losing at most this many rows on a crash is cheap,
# because the files stay on disk and the next run re-adds their rows without fetching them.
GRIN_MANIFEST_SAVE_EVERY = 200


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
    _add_grin_download(commands)
    _add_cultivar_split(commands)
    _add_grin_descriptors(commands)
    _add_race_crosswalk(commands)
    _add_core_shortlist(commands)
    _add_review_labels(commands)
    _add_split(commands)
    _add_train(commands)
    _add_export(commands)
    _add_mfwd_predict(commands)
    _add_mfwd_report(commands)
    _add_race_train(commands)
    _add_race_export(commands)
    _add_bundle_heads(commands)
    _add_trait_labels(commands)
    _add_trait_train(commands)
    _add_trait_export(commands)
    _add_trait_ranking(commands)
    arguments = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, exit_on_terminate)
    try:
        arguments.run(arguments)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        # Disk full, drive unplugged, network down after every retry: say what failed
        # instead of a traceback. Manifests are saved as they go, so a re-run resumes.
        print(f"error: {type(error).__name__}: {error}. Fix it and run the command again; "
              "finished work is kept.", file=sys.stderr)
        return 1
    return 0


# Exit status a shell reports for a process ended by SIGTERM (128 + 15).
TERMINATED_EXIT_CODE = 143


def exit_on_terminate(signal_number, frame) -> None:
    """Turns `kill <pid>` into a normal exit, so `finally` blocks save the manifest rows and
    remove the lock. Python's default SIGTERM ends the process without running them."""
    raise SystemExit(TERMINATED_EXIT_CODE)


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

    with manifest_lock(arguments.manifest):
        for species in _selected_classes(arguments.class_names, lambda c: c.inat_taxon_ids):
            photos = (
                photo
                for taxon_id in species.inat_taxon_ids
                for observation in inat.fetch_observations(
                    taxon_id, arguments.max_observations_per_taxon
                )
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

    with manifest_lock(arguments.manifest):
        for species in _selected_classes(arguments.class_names, lambda c: c.gbif_taxon_keys):
            photos = (
                photo
                for taxon_key in species.gbif_taxon_keys
                for occurrence in gbif.fetch_occurrences(
                    taxon_key, arguments.max_occurrences_per_taxon
                )
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

    with manifest_lock(arguments.manifest):
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
    with manifest_lock(arguments.manifest):
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
    manifest = arguments.manifest or DEFAULT_MANIFEST_DIR / f"species-{dataset.source}.csv"
    with manifest_lock(manifest):
        _import_mendeley_dataset(dataset, manifest, arguments.data_root)


def _import_mendeley_dataset(dataset, manifest: Path, data_root: Path) -> None:
    from sorghum_model import mendeley

    metadata = mendeley.fetch_dataset(dataset)
    # Checked before downloading anything, so a relicensed dataset never reaches the disk.
    license_code = mendeley.dataset_license_code(metadata)
    dataset_root = data_root / dataset.source
    placed = mendeley.download_and_lay_out(
        dataset, metadata, dataset_root, PublicDatasetSettings().images_per_sequence_group
    )
    print(f"{dataset.source}: {placed} photos laid out in {dataset_root / 'images'}")
    _import_laid_out_dataset(
        dataset_root / "images",
        data_root,
        manifest,
        source=dataset.source,
        license_code=license_code,
        attribution=mendeley.dataset_attribution(metadata),
        annotator=mendeley.dataset_authors(metadata),
        # The dataset's publication date, the last date its authors stood by the labels.
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
    manifest = arguments.manifest or DEFAULT_MANIFEST_DIR / f"species-{dataset.source}.csv"
    with manifest_lock(manifest):
        _import_figshare_dataset(dataset, manifest, arguments.data_root)


def _import_figshare_dataset(dataset, manifest: Path, data_root: Path) -> None:
    from sorghum_model import figshare

    article = figshare.fetch_article(dataset)
    license_code = figshare.article_license_code(article)
    dataset_root = data_root / dataset.source
    placed = figshare.download_and_lay_out(
        dataset, article, dataset_root, PublicDatasetSettings().grain_images_per_class
    )
    print(f"{dataset.source}: {placed} photos laid out in {dataset_root / 'images'}")
    _import_laid_out_dataset(
        dataset_root / "images",
        data_root,
        manifest,
        source=dataset.source,
        license_code=license_code,
        attribution=figshare.article_attribution(article),
        annotator=figshare.article_authors(article),
        labelled_on=(article.get("published_date") or "")[:10],
    )


def _import_laid_out_dataset(
    images_root: Path,
    data_root: Path,
    manifest: Path,
    *,
    source: str,
    license_code: str,
    attribution: str,
    annotator: str,
    labelled_on: str,
) -> None:
    """Imports a `<class>/<group>/<file>` folder and replaces the source's manifest.

    `labelled_on` stays empty when the source publishes no date; a made-up date (today)
    would claim a labelling that never happened then.
    """
    from sorghum_model.local_import import FolderSource, GroupBy, import_class_folders

    folder_source = FolderSource(
        class_name="",  # set per class folder by import_class_folders
        source=source,
        license=license_code,
        attribution=attribution,
        annotator=annotator,
        labelled_on=labelled_on,
        group_by=GroupBy.SUBFOLDER,
    )
    records = import_class_folders(images_root, data_root, folder_source)
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


@dataclass(frozen=True)
class ClassDownloadSummary:
    """What one class's download did, as printed after it."""

    photos: int
    failed_downloads: int
    is_listing_complete: bool


def _download_class(
    photos: Iterable,
    class_name: str,
    data_root: Path,
    manifest: Path,
    settings: DownloadSettings = DownloadSettings(),
) -> ClassDownloadSummary:
    """Downloads one class's photos and saves that class's rows in the source's manifest.

    Rows are saved every `settings.checkpoint_every_photos` photos and once more however the
    loop ends (finished, an API error while paging, Ctrl-C), so an interrupted run loses no
    rows; files already on disk are not downloaded again. A dead photo link is counted and
    skipped. An API error while listing (paging) ends this class early, is counted as one
    failure, and the run goes on with the next class; because the listing is incomplete, the
    class's earlier rows are kept rather than replaced. A photo listed twice (one Commons
    file in two categories) is kept once.

    Caller holds the manifest lock.
    """
    from sorghum_model.downloads import download_photo

    existing = read_manifest(manifest) if manifest.exists() else []
    records: dict[str, ImageRecord] = {}
    failures = 0
    is_listing_complete = False
    try:
        for photo in photos:
            image_path = photo.record_without_file["image_path"]
            if image_path in records:
                continue
            try:
                records[image_path] = download_photo(photo, data_root)
            except (OSError, http.client.HTTPException, ValueError) as error:
                # One dead link must not stop a run of thousands; the count is reported below.
                failures += 1
                print(f"warning: skipped {photo.url}: {error}", file=sys.stderr)
                continue
            if len(records) % settings.checkpoint_every_photos == 0:
                _save_class_rows(existing, records.values(), class_name, manifest, is_complete=False)
        is_listing_complete = True
    except (OSError, http.client.HTTPException, ValueError) as error:
        failures += 1
        print(
            f"warning: {class_name}: listing stopped after {len(records)} photos: {error}",
            file=sys.stderr,
        )
    finally:
        _save_class_rows(
            existing, records.values(), class_name, manifest, is_complete=is_listing_complete
        )
    print(
        f"{class_name}: {len(records)} photos, {failures} failed "
        f"{'' if is_listing_complete else '(listing incomplete) '}-> {manifest}",
        flush=True,
    )
    return ClassDownloadSummary(len(records), failures, is_listing_complete)


def _save_class_rows(
    existing: list[ImageRecord],
    downloaded: Iterable[ImageRecord],
    class_name: str,
    manifest: Path,
    *,
    is_complete: bool,
) -> None:
    write_manifest(merge_class_rows(existing, list(downloaded), class_name, is_complete), manifest)


def merge_class_rows(
    existing: list[ImageRecord],
    downloaded: list[ImageRecord],
    class_name: str,
    is_complete: bool,
) -> list[ImageRecord]:
    """The manifest after downloading `class_name`: other classes untouched.

    After a complete listing the class's rows are exactly the downloaded ones, so photos
    removed upstream leave the manifest. After an incomplete one, earlier rows not reached
    this time are kept. A photo whose earlier row was verified by `review-labels` keeps that
    verdict when the file has not changed, since a fresh download row is always unreviewed.
    """
    previous = {r.image_path: r for r in existing if r.class_name == class_name}
    rows = {}
    for record in downloaded:
        earlier = previous.get(record.image_path)
        was_reviewed = (
            earlier is not None
            and earlier.sha256 == record.sha256
            and earlier.label_status is LabelStatus.VERIFIED
            and record.label_status is LabelStatus.UNREVIEWED
        )
        rows[record.image_path] = earlier if was_reviewed else record
    if not is_complete:
        for image_path, earlier in previous.items():
            rows.setdefault(image_path, earlier)
    others = [r for r in existing if r.class_name != class_name]
    return others + list(rows.values())


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
    with manifest_lock(manifest):
        existing = read_manifest(manifest) if manifest.exists() else []
        kept = [r for r in existing if (r.source, r.class_name) != (source.source, source.class_name)]
        write_manifest(kept + records, manifest)
    print(f"{source.class_name}: {len(records)} photos from {arguments.folder} -> {manifest}")


def _add_review_labels(commands) -> None:
    command = commands.add_parser(
        "review-labels",
        help="Verify unreviewed Commons/Flickr labels with BioCLIP 2 (needs the review extra).",
    )
    command.add_argument(
        "--manifest", dest="manifests", type=Path, action="append",
        help="Default: manifests/species-commons.csv and species-flickr.csv, where present.",
    )
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.set_defaults(run=_run_review_labels)


def _run_review_labels(arguments) -> None:
    from sorghum_model.label_review import review_records

    manifests = arguments.manifests or [
        path
        for path in (DEFAULT_MANIFEST_DIR / "species-commons.csv", DEFAULT_MANIFEST_DIR / "species-flickr.csv")
        if path.exists()
    ]
    if not manifests:
        raise ValueError("no Commons or Flickr manifest to review")
    from sorghum_model.bioclip_classifier import BioclipClassifier

    classify = BioclipClassifier()
    settings = LabelReviewSettings()
    for manifest in manifests:
        with manifest_lock(manifest):
            records = review_records(
                read_manifest(manifest),
                arguments.data_root,
                classify,
                settings,
                on_checkpoint=lambda rows, path=manifest: write_manifest(rows, path),
            )
            write_manifest(records, manifest)
        for class_name in SPECIES_CLASS_NAMES:
            in_class = [r for r in records if r.class_name == class_name]
            if in_class:
                verified = sum(r.label_status is LabelStatus.VERIFIED for r in in_class)
                print(f"{manifest.name} {class_name:15} {verified}/{len(in_class)} verified")


def _add_grin_download(commands) -> None:
    command = commands.add_parser(
        "grin-download", help="Download GRIN-Global's accession-labelled sorghum seed/panicle images."
    )
    command.add_argument("--data-root", type=Path, default=DEFAULT_CULTIVAR_DATA_ROOT)
    command.add_argument("--manifest", type=Path, default=DEFAULT_GRIN_MANIFEST)
    command.add_argument(
        "--page-cache",
        type=Path,
        default=DEFAULT_GRIN_PAGE_CACHE,
        help="Study pages are read from here (shared with grin-descriptors) and fetched only when missing.",
    )
    command.set_defaults(run=_run_grin_download)


def _run_grin_download(arguments) -> None:
    from sorghum_model import grin, grin_descriptors
    from sorghum_model.cultivar_manifest import read_cultivar_manifest, write_cultivar_manifest
    from sorghum_model.downloads import RequestPacer, get_text

    def report_failure(image, error: Exception) -> None:
        print(f"  failed: {image.accession_number} {image.image_path}: {error}", file=sys.stderr)

    settings = GrinDescriptorSettings()
    fetch_page = grin_descriptors.CachedPageFetcher(
        arguments.page_cache,
        lambda url: get_text(url, timeout_seconds=settings.study_page_timeout_seconds),
        RequestPacer(settings.seconds_between_requests),
    )
    records = []
    with manifest_lock(arguments.manifest):
        # The last run's files are kept only where they came from the URL this run wants.
        previous_source_urls = {}
        if arguments.manifest.exists():
            previous_source_urls = {
                record.image_path: record.source_url for record in read_cultivar_manifest(arguments.manifest)
            }
        for study in grin.SORGHUM_IMAGE_STUDIES:
            in_study = 0
            page_html = fetch_page(study.page_url)
            for record in grin.download_study(
                study, page_html, arguments.data_root, report_failure, previous_source_urls
            ):
                records.append(record)
                in_study += 1
                # Saved regularly, so an interrupted run keeps the rows of what it has.
                if len(records) % GRIN_MANIFEST_SAVE_EVERY == 0:
                    write_cultivar_manifest(records, arguments.manifest)
            write_cultivar_manifest(records, arguments.manifest)
            print(f"{study.name}: {in_study} images", flush=True)
    print(f"grin: {len(records)} images of {len({r.cultivar_label for r in records})} accessions")


def _add_grin_descriptors(commands) -> None:
    command = commands.add_parser(
        "grin-descriptors",
        help="Fetch GRIN race and trait observations for the accessions in the GRIN image studies.",
    )
    command.add_argument("--out", type=Path, default=DEFAULT_GRIN_DESCRIPTORS)
    command.add_argument(
        "--page-cache",
        type=Path,
        default=DEFAULT_GRIN_PAGE_CACHE,
        help="Fetched GRIN pages are kept here, so a rerun skips them.",
    )
    command.add_argument(
        "--image-manifest",
        type=Path,
        default=DEFAULT_GRIN_MANIFEST,
        help="Coverage is reported for the accessions whose images are in this manifest.",
    )
    command.set_defaults(run=_run_grin_descriptors)


def _run_grin_descriptors(arguments) -> None:
    from sorghum_model import grin, grin_descriptors
    from sorghum_model.cultivar_manifest import read_cultivar_manifest
    from sorghum_model.downloads import RequestPacer, get_text

    settings = GrinDescriptorSettings()
    fetch_page = grin_descriptors.CachedPageFetcher(
        arguments.page_cache,
        lambda url: get_text(url, timeout_seconds=settings.study_page_timeout_seconds),
        RequestPacer(settings.seconds_between_requests),
    )
    # Every photographed accession, not only those downloaded so far, so the file is complete
    # once the image download finishes.
    accessions: set[str] = set()
    for study in grin.SORGHUM_IMAGE_STUDIES:
        accessions.update(image.accession_number for image in grin.parse_study_page(fetch_page(study.page_url)))
    print(f"{len(accessions)} photographed accessions", flush=True)

    observations = list(grin_descriptors.fetch_observations(accessions, fetch_page))
    observations += grin_descriptors.combine_panicle_observations(observations)
    grin_descriptors.write_observations(observations, arguments.out)
    print(f"{len(observations)} observations written to {arguments.out}")

    downloaded = {record.cultivar_label for record in read_cultivar_manifest(arguments.image_manifest)}
    for line in grin_descriptors.coverage_report(observations, accessions, downloaded):
        print(line)


def _add_race_crosswalk(commands) -> None:
    command = commands.add_parser(
        "race-crosswalk",
        help="Match the Frontiers 2023 race panel to GRIN accessions and report race agreement.",
    )
    command.add_argument(
        "--frontiers-table",
        type=Path,
        default=DEFAULT_FRONTIERS_TABLE,
        help="The article's table workbook; downloaded from figshare when missing.",
    )
    command.add_argument(
        "--page-cache",
        type=Path,
        default=DEFAULT_GRIN_PAGE_CACHE,
        help="GRIN race study pages (from grin-descriptors); fetched only when missing.",
    )
    command.add_argument(
        "--accession-page-cache",
        type=Path,
        default=DEFAULT_GRIN_ACCESSION_PAGE_CACHE,
        help="GRIN search and accession detail pages are kept here, so a rerun fetches nothing.",
    )
    command.add_argument("--split", type=Path, default=DEFAULT_CULTIVAR_SPLIT)
    command.add_argument("--out", type=Path, default=DEFAULT_RACE_CROSSWALK)
    command.set_defaults(run=_run_race_crosswalk)


def _run_race_crosswalk(arguments) -> None:
    from collections import Counter

    from sorghum_model import grin_descriptors, race_crosswalk
    from sorghum_model.cultivar_manifest import read_cultivar_split
    from sorghum_model.cultivar_races import race_labels
    from sorghum_model.downloads import RequestPacer, download_file, get_text
    from sorghum_model.frontiers_races import FRONTIERS_TABLE_MD5, FRONTIERS_TABLE_URL, read_frontiers_table

    download_file(FRONTIERS_TABLE_URL, arguments.frontiers_table, expected_md5=FRONTIERS_TABLE_MD5)
    samples = read_frontiers_table(arguments.frontiers_table)
    print(f"{len(samples)} Frontiers samples, {sum(bool(s.genebank_number) for s in samples)} with a genebank number")

    settings = RaceCrosswalkSettings()
    pacer = RequestPacer(settings.seconds_between_requests)
    fetch_accession_page = grin_descriptors.CachedPageFetcher(
        arguments.accession_page_cache,
        lambda url: get_text(url, timeout_seconds=settings.page_timeout_seconds),
        pacer,
    )
    identities = {}
    for number in sorted({sample.genebank_number for sample in samples}):
        identities[number] = race_crosswalk.resolve_genebank_number(
            number, fetch_accession_page, settings.max_candidates_per_search
        )
        print(f"  {number or '(sample name)'}: {identities[number].status.value}", flush=True)

    matched = {i.detail.accession for i in identities.values() if i.detail is not None}
    study_settings = GrinDescriptorSettings()
    fetch_study_page = grin_descriptors.CachedPageFetcher(
        arguments.page_cache,
        lambda url: get_text(url, timeout_seconds=study_settings.study_page_timeout_seconds),
        pacer,
    )
    observations = list(grin_descriptors.fetch_observations(matched, fetch_study_page, [grin_descriptors.RACE]))
    races = race_labels(matched, observations)
    race_studies = Counter(accession for accession, _ in {(o.accession, o.study) for o in observations})
    split_of = {row["cultivar_label"]: row["accession_split"] for row in read_cultivar_split(arguments.split)}

    rows = []
    for sample in samples:
        identity = identities[sample.genebank_number]
        accession = identity.detail.accession if identity.detail else ""
        rows.append(
            race_crosswalk.crosswalk_row(
                sample, identity, races.get(accession), race_studies[accession], split_of.get(accession, "")
            )
        )
    race_crosswalk.write_crosswalk(rows, arguments.out)
    lines = race_crosswalk.crosswalk_report(rows)
    summary = arguments.out.with_name(f"{arguments.out.stem}-summary.txt")
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"{len(rows)} rows written to {arguments.out}; summary in {summary}")


def _add_core_shortlist(commands) -> None:
    command = commands.add_parser(
        "core-shortlist",
        help="Rank GRIN accessions per basic race to request as seed for the type evaluation.",
    )
    command.add_argument(
        "--page-cache",
        type=Path,
        default=DEFAULT_GRIN_PAGE_CACHE,
        help="GRIN descriptor and study pages (from grin-descriptors); fetched only when missing.",
    )
    command.add_argument("--crosswalk", type=Path, default=DEFAULT_RACE_CROSSWALK)
    command.add_argument("--split", type=Path, default=DEFAULT_CULTIVAR_SPLIT)
    command.add_argument("--out", type=Path, default=DEFAULT_CORE_SHORTLIST)
    command.set_defaults(run=_run_core_shortlist)


def _run_core_shortlist(arguments) -> None:
    from collections import Counter, defaultdict

    from sorghum_model import core_shortlist, grin_descriptors
    from sorghum_model.cultivar_manifest import read_cultivar_split
    from sorghum_model.cultivar_races import race_labels
    from sorghum_model.downloads import RequestPacer, get_text
    from sorghum_model.grin_accessions import parse_study_roster
    from sorghum_model.race_crosswalk import basic_parents, read_crosswalk

    study_settings = GrinDescriptorSettings()
    fetch_page = grin_descriptors.CachedPageFetcher(
        arguments.page_cache,
        lambda url: get_text(url, timeout_seconds=study_settings.study_page_timeout_seconds),
        RequestPacer(study_settings.seconds_between_requests),
    )
    race = grin_descriptors.RACE
    roster_rows, race_observations = [], []
    race_page = f"{grin_descriptors.GRIN_BASE_URL}descriptordetail.aspx?id={race.descriptor_id}"
    for study, study_url in grin_descriptors.parse_descriptor_studies(fetch_page(race_page), race.descriptor_id):
        page = fetch_page(study_url)
        rows_of_study = parse_study_roster(page)
        roster_rows += rows_of_study
        accessions = {row.accession for row in rows_of_study}
        race_observations += grin_descriptors.parse_observations(page, race, study, study_url, accessions)
    first_roster = {}
    for row in roster_rows:
        first_roster.setdefault(row.accession, row)
    races = race_labels(first_roster, race_observations)
    race_studies = Counter(accession for accession, _ in {(o.accession, o.study) for o in race_observations})
    basic = {accession for accession, label in races.items() if len(basic_parents(label.race)) == 1}
    print(f"{len(first_roster)} accessions on GRIN race study pages, {len(basic)} labelled one basic race", flush=True)

    trait_descriptors = [d for d in grin_descriptors.DESCRIPTORS if d is not race]
    observations = list(grin_descriptors.fetch_observations(basic, fetch_page, trait_descriptors))
    observations += grin_descriptors.combine_panicle_observations(observations)
    traits_of = defaultdict(set)
    for observation in observations:
        if observation.ibpgr_state and observation.trait_id:
            traits_of[observation.accession].add(observation.trait_id)

    orderable = core_shortlist.accession_availability(roster_rows)
    frontiers = core_shortlist.frontiers_by_accession(read_crosswalk(arguments.crosswalk))
    split_of = {row["cultivar_label"]: row["accession_split"] for row in read_cultivar_split(arguments.split)}
    passports = [
        core_shortlist.AccessionPassport(
            roster=first_roster[accession],
            orderable=orderable[accession],
            race=races[accession],
            race_studies=race_studies[accession],
            traits_with_states=frozenset(traits_of[accession]),
            frontiers=frontiers.get(accession),
            grin_accession_split=split_of.get(accession, ""),
        )
        for accession in sorted(basic)
    ]
    rows, lines = core_shortlist.shortlist(passports, CoreShortlistSettings())
    core_shortlist.write_shortlist(rows, arguments.out)
    summary = arguments.out.with_name(f"{arguments.out.stem}-summary.txt")
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"{len(rows)} rows written to {arguments.out}; summary in {summary}")


def _add_cultivar_split(commands) -> None:
    command = commands.add_parser(
        "cultivar-split",
        help="Split a cultivar manifest by accession and by planting, with race labels and a summary.",
    )
    command.add_argument("--manifest", type=Path, default=DEFAULT_GRIN_MANIFEST)
    command.add_argument("--descriptors", type=Path, default=DEFAULT_GRIN_DESCRIPTORS)
    command.add_argument(
        "--page-cache",
        type=Path,
        default=DEFAULT_GRIN_PAGE_CACHE,
        help="Cached GRIN study pages (from grin-descriptors), to count the images GRIN lists.",
    )
    command.add_argument("--out", type=Path, default=DEFAULT_CULTIVAR_SPLIT)
    command.set_defaults(run=_run_cultivar_split)


def _run_cultivar_split(arguments) -> None:
    from sorghum_model import grin
    from sorghum_model.cultivar_manifest import (
        drop_repeated_rows,
        find_accession_split_leaks,
        read_cultivar_manifest,
        read_cultivar_split,
        write_cultivar_split,
    )
    from sorghum_model.cultivar_races import race_labels
    from sorghum_model.cultivar_reconciliation import ListedImage, reconciliation_report
    from sorghum_model.grin_descriptors import cache_file_name, read_observations

    settings = SplitSettings(salt=CULTIVAR_SPLIT_SALT)
    records, repeated_rows_dropped = drop_repeated_rows(read_cultivar_manifest(arguments.manifest))
    observations = read_observations(arguments.descriptors)
    races = race_labels({record.cultivar_label for record in records}, observations)
    write_cultivar_split(
        records, races, arguments.out, settings.validation_fraction, settings.test_fraction, settings.salt
    )
    rows = read_cultivar_split(arguments.out)
    leaks = find_accession_split_leaks(rows)
    if leaks:
        raise SystemExit("accession split leaks:\n" + "\n".join(leaks))

    listed_images = []
    for study in grin.SORGHUM_IMAGE_STUDIES:
        page = arguments.page_cache / cache_file_name(study.page_url)
        listed_images += [
            ListedImage(f"{study.name}/{image.photo_id}", image.accession_number)
            for image in grin.parse_study_page(page.read_text(encoding="utf-8"))
        ]
    lines = reconciliation_report(rows, listed_images, observations, races, repeated_rows_dropped)
    summary = arguments.out.with_name(f"{arguments.out.stem}-summary.txt")
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"{len(rows)} rows written to {arguments.out}; summary in {summary}")


def _add_split(commands) -> None:
    command = commands.add_parser("split", help="Assign every photo to train/validation/test by group.")
    command.add_argument("--manifest", dest="manifests", type=Path, action="append")
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--out", type=Path, default=DEFAULT_SPLIT_MANIFEST)
    command.set_defaults(run=_run_split)


def _run_split(arguments) -> None:
    from sorghum_model.near_duplicates import load_hashes, resolve_near_duplicates

    settings = SplitSettings()
    loaded = _load_manifests(arguments.manifests)
    result = resolve_near_duplicates(
        loaded,
        load_hashes(loaded, arguments.data_root),
        settings.near_duplicate_max_distance,
        settings.near_duplicate_exempt_sources,
    )
    records = result.records
    print(
        f"near-duplicates: {result.merged_groups} groups merged, {len(result.dropped)} photos "
        "dropped (conflicting labels or unreadable)"
    )
    splits = split_records(records, settings.validation_fraction, settings.test_fraction, settings.salt)
    write_split_manifest(records, splits, arguments.out, excluded=result.dropped)
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
    command.add_argument(
        "--resume", action="store_true",
        help="Continue the run in --run-dir after its last finished epoch (same data and settings).",
    )
    command.set_defaults(run=_run_train)


def _run_train(arguments) -> None:
    from sorghum_model.train import train_species_model

    records, splits = _load_records_and_splits(arguments.manifests, arguments.splits)
    train_species_model(
        records, splits, arguments.data_root, arguments.run_dir, TrainingSettings(),
        resume=arguments.resume,
    )
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
    command.add_argument(
        "--allow-below-bar", action="store_true",
        help="Export even if the ship bar (ExportSettings) is missed. Diagnostic exports only; "
        "the metadata then says belowBar: true.",
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
        allow_below_bar=arguments.allow_below_bar,
    )
    print(f"exported {metadata_path}")


def _add_race_photo_arguments(command) -> None:
    command.add_argument("--manifest", type=Path, default=DEFAULT_GRIN_MANIFEST)
    command.add_argument("--splits", type=Path, default=DEFAULT_CULTIVAR_SPLIT)
    command.add_argument("--data-root", type=Path, default=DEFAULT_CULTIVAR_DATA_ROOT)
    command.add_argument("--run-dir", type=Path, required=True)
    command.add_argument(
        "--basic-races-only", action="store_true",
        help="The basic-race output (T14, #37): train and score on the five basic races only; "
        "intermediates are reported apart (race_photos.split_basic_and_intermediate).",
    )


def _add_race_train(commands) -> None:
    command = commands.add_parser(
        "race-train", help="Train the race head on a species run's backbone (needs the train extra)."
    )
    _add_race_photo_arguments(command)
    command.add_argument(
        "--starting-model", type=Path, required=True,
        help="species.keras of the run whose backbone the race head starts from (traits-v2: run v2-3).",
    )
    command.add_argument(
        "--resume", action="store_true",
        help="Continue the run in --run-dir after its last finished epoch (same data and settings).",
    )
    command.set_defaults(run=_run_race_train)


def _run_race_train(arguments) -> None:
    from sorghum_model.race_photos import read_race_photos, split_basic_and_intermediate
    from sorghum_model.race_training import train_race_model

    photos = read_race_photos(arguments.manifest, arguments.splits)
    if arguments.basic_races_only:
        photos, _ = split_basic_and_intermediate(photos)
    train_race_model(
        photos, arguments.data_root, arguments.starting_model, arguments.run_dir, RaceTrainingSettings(),
        resume=arguments.resume,
    )
    print(f"trained race model in {arguments.run_dir}")


def _add_race_export(commands) -> None:
    command = commands.add_parser(
        "race-export",
        help="Quantize a race run to INT8, choose its answer rules on validation and score it once "
        "on test against the T9 gate (needs the export extra).",
    )
    _add_race_photo_arguments(command)
    command.add_argument("--version", type=int, required=True, help="Race model version N.")
    command.add_argument("--out-dir", type=Path, required=True)
    command.set_defaults(run=_run_race_export)


def _run_race_export(arguments) -> None:
    from sorghum_model.race_export import BASIC_RACE_RULE_SEARCH, export_race_model
    from sorghum_model.race_photos import read_race_photos, split_basic_and_intermediate

    photos = read_race_photos(arguments.manifest, arguments.splits)
    intermediates = []
    model_name, search = "race", RaceRuleSearchSettings()
    if arguments.basic_races_only:
        photos, intermediates = split_basic_and_intermediate(photos)
        model_name, search = "basic-race", BASIC_RACE_RULE_SEARCH
    provenance = {
        "splitManifestSha256": sha256_of_file(arguments.splits),
        "imageManifestSha256": sha256_of_file(arguments.manifest),
        "runDir": str(arguments.run_dir),
    }
    document = export_race_model(
        arguments.run_dir, photos, arguments.data_root, arguments.version, arguments.out_dir,
        ExportSettings(), search, RaceGateSettings(), provenance,
        model_name=model_name, intermediate_photos=intermediates,
    )
    gate = document["gate"]
    print(f"exported {model_name}-v{arguments.version} to {arguments.out_dir}; gate "
          + ("passed" if gate["passed"] else "missed: " + "; ".join(gate["problems"])))

def _add_bundle_heads(commands) -> None:
    command = commands.add_parser(
        "bundle-heads",
        help="Pack the species export and the basic-race export into one traits-vN model with both "
        "outputs, metadata and parity fixtures; nothing is retrained (ADR-0012, needs the export extra).",
    )
    command.add_argument("--species-export-dir", type=Path, required=True, help="Holds traits-vM.{tflite,json}.")
    command.add_argument("--species-fixtures-dir", type=Path, required=True, help="The species export's fixtures.")
    command.add_argument("--basic-race-export-dir", type=Path, required=True, help="Holds basic-race-vK.{tflite,json}.")
    command.add_argument("--manifest", type=Path, default=DEFAULT_GRIN_MANIFEST)
    command.add_argument("--splits", type=Path, default=DEFAULT_CULTIVAR_SPLIT)
    command.add_argument("--data-root", type=Path, default=DEFAULT_CULTIVAR_DATA_ROOT)
    command.add_argument("--version", type=int, required=True, help="Bundle version N (traits-vN).")
    command.add_argument("--out-dir", type=Path, required=True)
    command.add_argument(
        "--fixtures-root", type=Path, required=True,
        help="Gets species/ and basic-race/ fixture folders (shared/src/commonTest/resources).",
    )
    command.add_argument("--race-fixtures-per-race", type=int, default=2)
    command.set_defaults(run=_run_bundle_heads)


def _run_bundle_heads(arguments) -> None:
    from sorghum_model.bundle_export import bundle_species_and_basic_race, read_source_export
    from sorghum_model.cultivar_manifest import read_cultivar_manifest
    from sorghum_model.race_photos import photos_in, read_race_photos, split_basic_and_intermediate

    species = _single_export(arguments.species_export_dir, "traits-v")
    basic_race = _single_export(arguments.basic_race_export_dir, "basic-race-v")
    species_metadata = json.loads(species[1].read_text(encoding="utf-8"))
    race_metadata = json.loads(basic_race[1].read_text(encoding="utf-8"))
    photos, _ = split_basic_and_intermediate(read_race_photos(arguments.manifest, arguments.splits))
    provenance = race_metadata["provenance"]
    if (provenance["splitManifestSha256"], provenance["imageManifestSha256"]) != (
        sha256_of_file(arguments.splits), sha256_of_file(arguments.manifest)
    ):
        raise ValueError("the basic-race export was made from another split or manifest than --splits and --manifest")
    validation, test = photos_in(photos, Split.VALIDATION), photos_in(photos, Split.TEST)
    metadata = bundle_species_and_basic_race(
        species=read_source_export(*species, species_metadata["trainingData"]["modelFileSha256"]),
        species_fixtures_dir=arguments.species_fixtures_dir,
        basic_race=read_source_export(*basic_race, race_metadata["provenance"]["modelFileSha256"]),
        race_test_photos=test,
        race_verification_photos=validation + test,
        image_records={record.image_path: record for record in read_cultivar_manifest(arguments.manifest)},
        data_root=arguments.data_root,
        version=arguments.version,
        out_dir=arguments.out_dir,
        fixtures_root=arguments.fixtures_root,
        race_fixture_count_per_race=arguments.race_fixtures_per_race,
    )
    print(f"bundled {metadata['modelFile']} with heads {metadata['headOrder']} into {arguments.out_dir}")


def _single_export(directory: Path, prefix: str) -> tuple[Path, Path]:
    """The one `<prefix>N.tflite` and its `.json` in `directory` ("._" files are exFAT metadata)."""
    models = [p for p in directory.glob(f"{prefix}*.tflite") if not p.name.startswith("._")]
    if len(models) != 1:
        raise ValueError(f"expected one {prefix}N.tflite in {directory}, found {len(models)}")
    metadata = models[0].with_suffix(".json")
    if not metadata.exists():
        raise ValueError(f"{metadata} is missing")
    return models[0], metadata


# The catalogue traits a GRIN panicle-and-grain photo shows and GRIN labels (`cultivar_traits`).
# Seed weight is a candidate for the probe only: the catalogue reads it as a measured trait.
DEFAULT_HEAD_TRAITS = ("glumeColour", "grainColour", "panicleCompactnessAndShape")
# Must equal shared TraitNoiseSettings.minStateProbability (TraitEstimate.kt); copied by hand.
APP_TRAIT_NOISE_FLOOR = 0.01


def _add_trait_photo_arguments(command) -> None:
    command.add_argument("--manifest", type=Path, default=DEFAULT_GRIN_MANIFEST)
    command.add_argument("--splits", type=Path, default=DEFAULT_CULTIVAR_SPLIT)
    command.add_argument("--descriptors", type=Path, default=DEFAULT_GRIN_DESCRIPTORS)


def _add_trait_labels(commands) -> None:
    command = commands.add_parser(
        "trait-labels",
        help="Per-accession trait labels from GRIN descriptors: exclusions, coverage and state support per split.",
    )
    _add_trait_photo_arguments(command)
    command.add_argument(
        "--out", type=Path, default=None,
        help="Summary file (default: next to --splits, named <split>-trait-summary.txt).",
    )
    command.set_defaults(run=_run_trait_labels)


def _run_trait_labels(arguments) -> None:
    from sorghum_model.cultivar_traits import read_labelled_trait_photos, trait_label_report

    photos, labels = read_labelled_trait_photos(arguments.manifest, arguments.splits, arguments.descriptors)
    lines = trait_label_report(photos, labels, TraitLabelSettings().min_train_accessions_per_state)
    out = arguments.out or arguments.splits.with_name(f"{arguments.splits.stem}-trait-summary.txt")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"wrote {out}")


def _trait_photos_and_heads(arguments):
    from sorghum_model.cultivar_traits import candidate_trait, head_states, read_labelled_trait_photos

    photos, _ = read_labelled_trait_photos(arguments.manifest, arguments.splits, arguments.descriptors)
    minimum = TraitLabelSettings().min_train_accessions_per_state
    heads = {trait_id: head_states(photos, candidate_trait(trait_id), minimum) for trait_id in arguments.traits}
    return photos, heads


def _add_trait_train(commands) -> None:
    command = commands.add_parser(
        "trait-train", help="Train learned trait heads on a species run's backbone (needs the train extra)."
    )
    _add_trait_photo_arguments(command)
    command.add_argument("--data-root", type=Path, default=DEFAULT_CULTIVAR_DATA_ROOT)
    command.add_argument("--run-dir", type=Path, required=True)
    command.add_argument("--traits", nargs="+", default=list(DEFAULT_HEAD_TRAITS))
    command.add_argument(
        "--starting-model", type=Path, required=True,
        help="species.keras of the run whose backbone the heads start from (traits-v2: run v2-3).",
    )
    command.add_argument(
        "--fine-tune-epochs", type=int, default=TraitTrainingSettings().fine_tune_epochs,
        help="0 (default) keeps the traits-v2 backbone frozen.",
    )
    command.add_argument("--resume", action="store_true")
    command.set_defaults(run=_run_trait_train)


def _run_trait_train(arguments) -> None:
    from sorghum_model.trait_training import train_trait_model

    photos, heads = _trait_photos_and_heads(arguments)
    settings = TraitTrainingSettings(fine_tune_epochs=arguments.fine_tune_epochs)
    train_trait_model(
        photos, heads, arguments.data_root, arguments.starting_model, arguments.run_dir, settings,
        resume=arguments.resume,
    )
    print(f"trained trait heads {heads} in {arguments.run_dir}")


def _add_trait_export(commands) -> None:
    command = commands.add_parser(
        "trait-export",
        help="Quantize a trait-head run to INT8, fit a temperature per head on validation and score "
        "every head once on test against the R6 gate (needs the export extra).",
    )
    _add_trait_photo_arguments(command)
    command.add_argument("--data-root", type=Path, default=DEFAULT_CULTIVAR_DATA_ROOT)
    command.add_argument("--run-dir", type=Path, required=True)
    command.add_argument("--traits", nargs="+", default=list(DEFAULT_HEAD_TRAITS))
    command.add_argument("--version", type=int, required=True, help="Trait-head model version N.")
    command.add_argument("--out-dir", type=Path, required=True)
    command.set_defaults(run=_run_trait_export)


def _run_trait_export(arguments) -> None:
    from sorghum_model.trait_export import export_trait_model

    photos, heads = _trait_photos_and_heads(arguments)
    provenance = {
        "splitManifestSha256": sha256_of_file(arguments.splits),
        "imageManifestSha256": sha256_of_file(arguments.manifest),
        "descriptorManifestSha256": sha256_of_file(arguments.descriptors),
        "runDir": str(arguments.run_dir),
    }
    document = export_trait_model(
        arguments.run_dir, photos, heads, arguments.data_root, arguments.version, arguments.out_dir,
        ExportSettings(), TraitGateSettings(), provenance,
    )
    print(f"exported trait-heads-v{arguments.version} to {arguments.out_dir}; heads passing R6: "
          + (", ".join(document["passedHeads"]) or "none"))


def _add_trait_ranking(commands) -> None:
    command = commands.add_parser(
        "trait-ranking",
        help="Offline trait-first check: trait-head outputs through naive Bayes to race and accession rankings.",
    )
    _add_trait_photo_arguments(command)
    command.add_argument("--traits", nargs="+", default=list(DEFAULT_HEAD_TRAITS))
    command.add_argument("--outputs", type=Path, required=True, help="trait-heads-vN-outputs.npz from trait-export.")
    command.add_argument("--out", type=Path, required=True, help="JSON file for the results.")
    command.set_defaults(run=_run_trait_ranking)


def _run_trait_ranking(arguments) -> None:
    import json

    import numpy as np

    from sorghum_model.race_evaluation import GATE_COVERAGE
    from sorghum_model.trait_ranking import ranking_check

    photos, heads = _trait_photos_and_heads(arguments)
    with np.load(arguments.outputs) as saved:
        outputs = {key: saved[key] for key in saved.files}
    # The app's floor (shared TraitNoiseSettings.minStateProbability), so the check reasons as the app does.
    result = ranking_check(photos, heads, outputs, APP_TRAIT_NOISE_FLOOR, GATE_COVERAGE, RaceRuleSearchSettings())
    arguments.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


def _manifest_paths(manifests: list[Path] | None) -> list[Path]:
    """Explicit manifests, or every committed `manifests/species-*.csv`."""
    paths = manifests or sorted(DEFAULT_MANIFEST_DIR.glob("species-*.csv"))
    if not paths:
        raise ValueError(f"no manifests given and none found in {DEFAULT_MANIFEST_DIR}")
    return paths


def _load_manifests(manifests: list[Path] | None) -> list[ImageRecord]:
    """Every verified photo of the manifests; unreviewed labels never reach split, train or export."""
    records = merge_manifests([read_manifest(path) for path in _manifest_paths(manifests)])
    verified = verified_records(records)
    if len(verified) < len(records):
        print(f"left out {len(records) - len(verified)} photos with unreviewed labels")
    return verified


def _load_records_and_splits(manifests, split_manifest: Path):
    splits, excluded = read_split_manifest(split_manifest)
    records = [r for r in _load_manifests(manifests) if r.sha256 not in excluded]
    unsplit = [r for r in records if r.sha256 not in splits]
    if unsplit:
        raise ValueError(
            f"{len(unsplit)} photos are not in {split_manifest}; run `sorghum-model split` again"
        )
    return records, splits


def _add_mfwd_predict(commands) -> None:
    command = commands.add_parser(
        "mfwd-predict",
        help="External check: run the species model on MFWD plant crops (needs TensorFlow).",
    )
    command.add_argument("--ground-truth", type=Path, required=True, help="MFWD gt.csv.")
    command.add_argument(
        "--jpegs-dir", type=Path, required=True,
        help="MFWD jpegs/ folder (<EPPO>/<tray>.zip); trays not downloaded are skipped.",
    )
    command.add_argument("--model-dir", type=Path, required=True, help="Holds traits-vN.{tflite,json}.")
    command.add_argument("--version", type=int, required=True, help="Model version N.")
    command.add_argument("--out", type=Path, required=True, help="Predictions CSV to write.")
    command.add_argument(
        "--threads", type=int, default=2,
        help="Interpreter threads; keep low when other jobs share the machine.",
    )
    command.set_defaults(run=_run_mfwd_predict)


def _run_mfwd_predict(arguments) -> None:
    from sorghum_model.mfwd import predict_trays

    count = predict_trays(
        arguments.ground_truth, arguments.jpegs_dir, arguments.model_dir, arguments.version,
        arguments.out, MfwdEvaluationSettings(), SpeciesDecisionSettings(), arguments.threads,
    )
    print(f"wrote {count} crop predictions to {arguments.out}")


def _add_mfwd_report(commands) -> None:
    command = commands.add_parser(
        "mfwd-report", help="Score MFWD crop predictions per photo, plant, stage and EPPO code."
    )
    command.add_argument("--predictions", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True, help="Report JSON to write.")
    command.set_defaults(run=_run_mfwd_report)


def _run_mfwd_report(arguments) -> None:
    import json

    from sorghum_model.mfwd import evaluation_report, format_report, read_predictions

    report = evaluation_report(read_predictions(arguments.predictions), MfwdEvaluationSettings())
    arguments.out.write_text(json.dumps(report, indent=2) + "\n")
    print(format_report(report))


if __name__ == "__main__":
    sys.exit(main())
