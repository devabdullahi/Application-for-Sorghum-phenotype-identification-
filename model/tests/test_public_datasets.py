"""Mendeley Data and Figshare: version pinning, licence checks, credit lines and layout."""

import hashlib
import zipfile

import pytest

from sorghum_model import figshare, mendeley
from sorghum_model.local_import import FolderSource, GroupBy, import_class_folders

CC_BY = {"short_name": "CC BY 4.0", "url": "http://creativecommons.org/licenses/by/4.0"}


def _mendeley_metadata(**overrides):
    metadata = {
        "id": "4gkcyxjyss",
        "version": 1,
        "name": "SorghumWeedDataset_Classification",
        "doi": {"id": "10.17632/4gkcyxjyss.1"},
        "contributors": [
            {"first_name": "Justina", "last_name": "Michael"},
            {"first_name": "Thenmozhi", "last_name": "M"},
        ],
        "data_licence": CC_BY,
        "files": [],
    }
    metadata.update(overrides)
    return metadata


def test_mendeley_licence_and_credit():
    metadata = _mendeley_metadata()
    assert mendeley.dataset_license_code(metadata) == "cc-by"
    assert mendeley.dataset_authors(metadata) == "Justina Michael, Thenmozhi M"
    assert mendeley.dataset_attribution(metadata) == (
        "Justina Michael, Thenmozhi M, SorghumWeedDataset_Classification, Mendeley Data, "
        "doi:10.17632/4gkcyxjyss.1, CC BY 4.0"
    )


def test_mendeley_refuses_a_no_derivatives_licence():
    metadata = _mendeley_metadata(data_licence={"short_name": "CC BY-NC-ND 4.0"})
    with pytest.raises(ValueError, match="not allowed"):
        mendeley.dataset_license_code(metadata)


def test_mendeley_refuses_an_unchecked_version(monkeypatch):
    monkeypatch.setattr(mendeley, "get_json", lambda url: _mendeley_metadata(version=2))
    with pytest.raises(ValueError, match="now version 2"):
        mendeley.fetch_dataset(mendeley.MENDELEY_DATASETS["sorghum-weed"])


def test_mendeley_loose_files_go_straight_to_their_group(tmp_path, monkeypatch):
    downloaded = []
    monkeypatch.setattr(
        mendeley, "download_file",
        lambda url, destination, expected_sha256: downloaded.append((url, destination, expected_sha256)),
    )
    metadata = _mendeley_metadata(
        files=[
            {"filename": "Rust21.jpg", "content_details": {"download_url": "u1", "sha256_hash": "h1"}},
            {"filename": "notes.txt", "content_details": {"download_url": "u2", "sha256_hash": "h2"}},
        ]
    )
    placed = mendeley.download_and_lay_out(
        mendeley.MENDELEY_DATASETS["sorghum-disease"], metadata, tmp_path, 20
    )
    assert placed == 1
    assert downloaded == [("u1", tmp_path / "images/sorghum_bicolor/rust-0001/Rust21.jpg", "h1")]


def _article(**overrides):
    article = {
        "id": 22988981,
        "version": 2,
        "title": "sorghum.zip",
        "doi": "10.6084/m9.figshare.22988981.v2",
        "license": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
        "authors": [{"full_name": "Lei Fan"}],
        "files": [],
    }
    article.update(overrides)
    return article


def test_figshare_licence_and_credit():
    article = _article()
    assert figshare.article_license_code(article) == "cc-by"
    assert figshare.article_attribution(article) == (
        "Lei Fan, GrainSet sorghum.zip, Figshare, doi:10.6084/m9.figshare.22988981.v2, CC BY 4.0"
    )


def test_figshare_refuses_an_unchecked_version(monkeypatch):
    monkeypatch.setattr(figshare, "get_json", lambda url: _article(version=3))
    with pytest.raises(ValueError, match="now version 3"):
        figshare.fetch_article(figshare.FIGSHARE_DATASETS["grainset-sorghum"])


def test_figshare_samples_kernels_and_imports_them(tmp_path, monkeypatch):
    names = [f"sorg/train/0_NOR/Grainset_sorg_2020-01-0{i}-00-00-00_1_p600s.png" for i in range(1, 5)]

    def fake_download(url, destination, expected_md5):
        assert expected_md5 == "abc"
        destination.parent.mkdir(parents=True)
        with zipfile.ZipFile(destination, "w") as archive:
            for name in names + ["sorg/mask/Grainset_sorg_2020-01-01-00-00-00_1_p600s.png"]:
                archive.writestr(name, hashlib.sha256(name.encode()).digest())

    monkeypatch.setattr(figshare, "download_file", fake_download)
    article = _article(files=[{"name": "sorghum.zip", "download_url": "u", "computed_md5": "abc"}])
    dataset_root = tmp_path / "grainset-sorghum"
    placed = figshare.download_and_lay_out(
        figshare.FIGSHARE_DATASETS["grainset-sorghum"], article, dataset_root, max_images=3
    )
    assert placed == 3

    source = FolderSource(
        class_name="", source="grainset-sorghum", license="cc-by", attribution="Lei Fan",
        annotator="Lei Fan", labelled_on="2023-05-01", group_by=GroupBy.SUBFOLDER,
    )
    records = import_class_folders(dataset_root / "images", tmp_path, source)
    assert len(records) == 3
    assert {r.class_name for r in records} == {"sorghum_bicolor"}
    assert all(r.group_id.startswith("grainset-sorghum-capture-2020-01-0") for r in records)


def test_figshare_needs_the_named_archive(tmp_path):
    with pytest.raises(ValueError, match="no file 'maize.zip'"):
        figshare.download_and_lay_out(
            figshare.FIGSHARE_DATASETS["grainset-maize"], _article(), tmp_path, 3
        )
