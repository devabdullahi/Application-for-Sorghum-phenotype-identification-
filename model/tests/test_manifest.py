import os

import pytest

from conftest import make_record
from sorghum_model.manifest import (
    MANIFEST_COLUMNS,
    LabelStatus,
    ManifestLockedError,
    license_summary,
    manifest_lock,
    verified_records,
    merge_manifests,
    normalize_license_code,
    read_manifest,
    write_manifest,
)


@pytest.mark.parametrize("code", ["cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa"])
def test_accepts_open_and_non_commercial_licences(code):
    assert make_record(license=code).license == code


@pytest.mark.parametrize("code", ["cc-by-nd", "cc-by-nc-nd", "all-rights-reserved", ""])
def test_rejects_no_derivatives_and_unlicensed(code):
    with pytest.raises(ValueError, match="not allowed"):
        make_record(license=code)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("CC_BY_NC_4_0", "cc-by-nc"),  # GBIF enum
        ("CC0_1_0", "cc0"),
        ("http://creativecommons.org/licenses/by-nc-nd/4.0/", "cc-by-nc-nd"),  # GBIF media
        ("http://creativecommons.org/licenses/by/4.0/legalcode", "cc-by"),
        ("https://creativecommons.org/publicdomain/zero/1.0/", "cc0"),
        ("cc-by-sa-3.0-de", "cc-by-sa"),  # Commons, with a jurisdiction port
        ("CC BY-SA 4.0", "cc-by-sa"),  # Commons short name, Mendeley, Figshare
        ("CC BY 4.0", "cc-by"),
        ("cc-by-nc-sa", "cc-by-nc-sa"),  # iNaturalist
        ("pd", None),
        ("GFDL", None),
        ("https://creativecommons.org/publicdomain/mark/1.0/", None),
    ],
)
def test_normalizes_licences_from_every_source(text, expected):
    assert normalize_license_code(text) == expected


def test_licence_summary_flags_non_commercial_data():
    records = [make_record(license="cc-by-sa"), make_record(license="cc-by-nc"), make_record()]
    assert license_summary(records) == {
        "licenses": ["cc-by", "cc-by-nc", "cc-by-sa"],
        "nonCommercial": True,
    }


def test_licence_summary_without_non_commercial_data():
    assert license_summary([make_record(license="cc0")]) == {
        "licenses": ["cc0"],
        "nonCommercial": False,
    }


def test_rejects_unknown_class():
    with pytest.raises(ValueError, match="unknown class"):
        make_record(class_name="rice")


def test_rejects_missing_group():
    with pytest.raises(ValueError, match="group_id is empty"):
        make_record(group_id="")


def test_round_trips_sorted_by_source_and_id(tmp_path):
    path = tmp_path / "manifest.csv"
    second = make_record(source_id="2", sha256="b" * 64)
    first = make_record(source_id="1", sha256="a" * 64)
    write_manifest([second, first], path)
    assert read_manifest(path) == [first, second]


def test_merge_keeps_one_copy_of_same_photo_with_same_label():
    record = make_record()
    duplicate = make_record(source="other", source_id="x")
    assert merge_manifests([[record], [duplicate]]) == [record]


def test_merge_drops_photo_with_conflicting_labels():
    sorghum = make_record()
    maize = make_record(source="other", class_name="maize")
    unrelated = make_record(sha256="c" * 64)
    assert merge_manifests([[sorghum, unrelated], [maize]]) == [unrelated]


def _write_legacy_manifest(path, rows):
    # A manifest as written before the label_status column existed.
    import csv

    columns = [c for c in MANIFEST_COLUMNS if c != "label_status"]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row[c] for c in columns})


def test_legacy_rows_get_label_status_from_their_source(tmp_path):
    from dataclasses import asdict

    path = tmp_path / "old.csv"
    rows = [
        asdict(make_record(source="commons", source_id="1", sha256="1" * 64)),
        asdict(make_record(source="flickr", source_id="2", sha256="2" * 64)),
        asdict(make_record(source="gbif", source_id="3", sha256="3" * 64)),
    ]
    _write_legacy_manifest(path, rows)
    statuses = {r.source: r.label_status for r in read_manifest(path)}
    assert statuses == {
        "commons": LabelStatus.UNREVIEWED,
        "flickr": LabelStatus.UNREVIEWED,
        "gbif": LabelStatus.VERIFIED,
    }


def test_label_status_round_trips_and_filters(tmp_path):
    path = tmp_path / "m.csv"
    verified = make_record(source_id="1", sha256="1" * 64)
    unreviewed = make_record(source_id="2", sha256="2" * 64, label_status="unreviewed")
    write_manifest([verified, unreviewed], path)
    loaded = read_manifest(path)
    assert [r.label_status for r in loaded] == [LabelStatus.VERIFIED, LabelStatus.UNREVIEWED]
    assert verified_records(loaded) == [verified]


def test_rejects_an_unknown_label_status():
    with pytest.raises(ValueError, match="label_status"):
        make_record(label_status="maybe")


def test_write_leaves_no_temporary_file(tmp_path):
    path = tmp_path / "m.csv"
    write_manifest([make_record()], path)
    assert [p.name for p in tmp_path.iterdir()] == ["m.csv"]


def test_lock_refuses_a_second_live_process(tmp_path):
    manifest = tmp_path / "species-gbif.csv"
    (tmp_path / "species-gbif.csv.lock").write_text(str(os.getppid()))  # our parent is alive
    with pytest.raises(ManifestLockedError, match="one process per source"):
        with manifest_lock(manifest):
            pass


def test_lock_takes_over_a_stale_lock_and_releases_it(tmp_path):
    manifest = tmp_path / "species-gbif.csv"
    lock = tmp_path / "species-gbif.csv.lock"
    lock.write_text("2000000000")  # no such process
    with manifest_lock(manifest):
        assert lock.read_text() == str(os.getpid())
    assert not lock.exists()
