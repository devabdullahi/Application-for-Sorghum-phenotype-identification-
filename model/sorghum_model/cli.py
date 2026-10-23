"""Command line for the species-head pipeline: download, import, split, train, export.

Run `uv run sorghum-model --help` from `model/`. See model/README.md for the full workflow.
"""

import argparse
import sys
import urllib.error
from pathlib import Path

from sorghum_model.manifest import (
    ImageRecord,
    merge_manifests,
    read_manifest,
    sha256_of_file,
    write_manifest,
)
from sorghum_model.settings import ExportSettings, SplitSettings, TrainingSettings
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
        "inat-download", help="Download research-grade CC0/CC BY/CC BY-SA/CC BY-NC/CC BY-NC-SA iNaturalist photos."
    )
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--manifest", type=Path, default=DEFAULT_INAT_MANIFEST)
    command.add_argument(
        "--class", dest="class_names", action="append", choices=SPECIES_CLASS_NAMES,
        help="Only these classes (repeatable). Default: every class with iNaturalist taxa.",
    )
    command.add_argument("--max-observations-per-taxon", type=int, default=3000)
    command.add_argument("--max-photos-per-observation", type=int, default=3)
    command.set_defaults(run=_run_inat_download)


def _run_inat_download(arguments) -> None:
    # Imported here so the other commands do not depend on network code.
    from sorghum_model import downloads, inat

    selected = [
        c for c in SPECIES_CLASSES
        if c.inat_taxon_ids and (not arguments.class_names or c.name in arguments.class_names)
    ]
    existing = read_manifest(arguments.manifest) if arguments.manifest.exists() else []
    for species in selected:
        records: list[ImageRecord] = []
        failures = 0
        for taxon_id in species.inat_taxon_ids:
            for observation in inat.fetch_observations(taxon_id, arguments.max_observations_per_taxon):
                for photo in inat.select_photos(
                    observation, species.name, arguments.max_photos_per_observation
                ):
                    try:
                        records.append(downloads.download_photo(photo, arguments.data_root))
                    except (urllib.error.URLError, TimeoutError) as error:
                        failures += 1
                        print(f"warning: skipped {photo.url}: {error}", file=sys.stderr)
        # Replace this class's rows and save after each class, so an interrupted run keeps
        # the classes already finished.
        existing = [r for r in existing if r.class_name != species.name] + records
        write_manifest(existing, arguments.manifest)
        print(f"{species.name}: {len(records)} photos, {failures} failed downloads")


def _add_import_folder(commands) -> None:
    command = commands.add_parser(
        "import-folder", help="Add a folder of labelled photos (public dataset or our own)."
    )
    command.add_argument("folder", type=Path)
    command.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    command.add_argument("--class", dest="class_name", required=True, choices=SPECIES_CLASS_NAMES)
    command.add_argument("--source", required=True, help="Short dataset name, e.g. sorghum-weed-2023.")
    command.add_argument("--license", required=True, help="cc0, cc-by, cc-by-sa, cc-by-nc or cc-by-nc-sa.")
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
