import pytest
from PIL import Image

from sorghum_model.local_import import FolderSource, GroupBy, import_class_folders, import_folder


def _source(group_by=GroupBy.SUBFOLDER, annotator="A. Annotator"):
    return FolderSource(
        class_name="pearl_millet", source="team-photos", license="cc-by",
        attribution="Sorghum project team", annotator=annotator,
        labelled_on="2026-10-01", group_by=group_by,
    )


def _image(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4)).save(path)


def test_groups_by_subfolder(tmp_path):
    _image(tmp_path / "millet" / "plot-3" / "a.jpg")
    _image(tmp_path / "millet" / "plot-3" / "b.png")
    (tmp_path / "millet" / "plot-3" / "notes.txt").write_text("x")
    records = import_folder(tmp_path / "millet", tmp_path, _source())
    assert [r.group_id for r in records] == ["team-photos-plot-3"] * 2
    assert records[0].image_path == "millet/plot-3/a.jpg"
    assert records[0].label_source == "team-photos; annotator A. Annotator"


def test_subfolder_grouping_needs_subfolders(tmp_path):
    _image(tmp_path / "millet" / "a.jpg")
    with pytest.raises(ValueError, match="subfolder"):
        import_folder(tmp_path / "millet", tmp_path, _source())


def test_requires_annotator(tmp_path):
    with pytest.raises(ValueError, match="annotator"):
        import_folder(tmp_path, tmp_path, _source(annotator=""))


def test_folder_must_be_inside_data_root(tmp_path):
    with pytest.raises(ValueError, match="data root"):
        import_folder(tmp_path, tmp_path / "data", _source(GroupBy.FILE))


def test_skips_hidden_files(tmp_path):
    # macOS writes "._<name>" metadata files next to every file on exFAT drives; they keep
    # the image suffix but are not images.
    _image(tmp_path / "millet" / "plot-3" / "a.jpg")
    (tmp_path / "millet" / "plot-3" / "._a.jpg").write_bytes(b"\x00\x05\x16\x07")
    _image(tmp_path / "millet" / ".thumbnails" / "b.jpg")
    records = import_folder(tmp_path / "millet", tmp_path, _source())
    assert [record.source_id for record in records] == ["plot-3/a.jpg"]


def test_imports_each_class_folder_with_its_own_class(tmp_path):
    images = tmp_path / "sorghum-weed-2023" / "images"
    _image(images / "sorghum_bicolor" / "train-0000" / "a.jpeg")
    _image(images / "other_grass" / "train-0000" / "b.jpeg")
    records = import_class_folders(images, tmp_path, _source())
    assert sorted((r.class_name, r.group_id) for r in records) == [
        ("other_grass", "team-photos-train-0000"),
        ("sorghum_bicolor", "team-photos-train-0000"),
    ]
