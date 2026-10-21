import pytest

from conftest import make_record
from sorghum_model.manifest import merge_manifests, read_manifest, write_manifest


def test_rejects_non_commercial_licence():
    with pytest.raises(ValueError, match="cc-by-nc"):
        make_record(license="cc-by-nc")


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
