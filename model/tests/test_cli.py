"""The CLI's download loop, split and the unreviewed-label exclusion, with the network mocked."""

import http.client
import urllib.error

from PIL import Image

from conftest import make_record
from sorghum_model import cli, downloads
from sorghum_model.downloads import PhotoToDownload
from sorghum_model.manifest import LabelStatus, read_manifest, write_manifest
from sorghum_model.settings import DownloadSettings
from sorghum_model.splits import EXCLUDED


def _photo(number: int, class_name: str = "sorghum_bicolor") -> PhotoToDownload:
    return PhotoToDownload(
        url=f"https://photos.example/{number}.jpg",
        record_without_file={
            "image_path": f"inaturalist/{number}.jpg",
            "class_name": class_name,
            "source": "inaturalist",
            "source_id": str(number),
            "group_id": f"inaturalist-user-{number}",
            "license": "cc-by",
            "attribution": "(c) Someone",
            "label_source": f"inaturalist research-grade observation {number}",
            "label_status": LabelStatus.VERIFIED,
            "labelled_on": "2025-01-01",
        },
    )


def _fake_download(failing_numbers=()):
    def download_photo(photo, data_root):
        number = int(photo.record_without_file["source_id"])
        if number in failing_numbers:
            raise urllib.error.HTTPError(photo.url, 404, "gone", {}, None)
        return make_record(**photo.record_without_file, sha256=f"{number:064d}")

    return download_photo


def test_counts_dead_links_and_keeps_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads, "download_photo", _fake_download(failing_numbers={2}))
    manifest = tmp_path / "species-inaturalist.csv"
    summary = cli._download_class(
        [_photo(1), _photo(2), _photo(3)], "sorghum_bicolor", tmp_path, manifest
    )
    assert (summary.photos, summary.failed_downloads, summary.is_listing_complete) == (2, 1, True)
    assert sorted(r.source_id for r in read_manifest(manifest)) == ["1", "3"]


def test_paging_error_counts_as_failure_and_keeps_earlier_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads, "download_photo", _fake_download())
    manifest = tmp_path / "species-inaturalist.csv"
    # A previous run had photo 9, which this run's listing does not reach.
    write_manifest([make_record(source_id="9", image_path="inaturalist/9.jpg", sha256="9" * 64)], manifest)

    def listing():
        yield _photo(1)
        raise http.client.RemoteDisconnected("API went away while paging")

    summary = cli._download_class(listing(), "sorghum_bicolor", tmp_path, manifest)
    assert (summary.photos, summary.failed_downloads, summary.is_listing_complete) == (1, 1, False)
    assert sorted(r.source_id for r in read_manifest(manifest)) == ["1", "9"]


def test_complete_listing_replaces_the_class_rows_only(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads, "download_photo", _fake_download())
    manifest = tmp_path / "species-inaturalist.csv"
    write_manifest(
        [
            make_record(source_id="9", image_path="inaturalist/9.jpg", sha256="9" * 64),
            make_record(source_id="8", image_path="inaturalist/8.jpg", sha256="8" * 64, class_name="maize"),
        ],
        manifest,
    )
    cli._download_class([_photo(1)], "sorghum_bicolor", tmp_path, manifest)
    assert sorted((r.class_name, r.source_id) for r in read_manifest(manifest)) == [
        ("maize", "8"), ("sorghum_bicolor", "1"),
    ]


def test_checkpoints_while_downloading(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads, "download_photo", _fake_download())
    manifest = tmp_path / "species-inaturalist.csv"
    seen_on_disk = []

    def listing():
        for number in range(1, 6):
            if number == 4:
                seen_on_disk.append(len(read_manifest(manifest)))
            yield _photo(number)

    cli._download_class(listing(), "sorghum_bicolor", tmp_path, manifest, DownloadSettings(checkpoint_every_photos=3))
    assert seen_on_disk == [3]


def test_a_new_download_keeps_an_earlier_review_verdict(tmp_path, monkeypatch):
    reviewed = make_record(
        source="commons", source_id="1", image_path="inaturalist/1.jpg", sha256=f"{1:064d}",
        label_source="commons category; bioclip-2 agreement p=0.90",
    )
    manifest = tmp_path / "species-commons.csv"
    write_manifest([reviewed], manifest)
    photo = _photo(1)
    photo.record_without_file["label_status"] = LabelStatus.UNREVIEWED
    monkeypatch.setattr(downloads, "download_photo", _fake_download())
    cli._download_class([photo], "sorghum_bicolor", tmp_path, manifest)
    assert read_manifest(manifest) == [reviewed]


def _image(path, colour):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (32, 32), colour)
    # A left-to-right gradient gives a distinctive dHash per colour.
    for x in range(32):
        for y in range(32):
            image.putpixel((x, y), tuple(min(255, c + x * (i + 1) * 3) for i, c in enumerate(colour)))
    image.save(path)


def test_split_leaves_out_unreviewed_labels(tmp_path, capsys):
    data_root = tmp_path / "data"
    _image(data_root / "a.png", (10, 20, 30))
    _image(data_root / "b.png", (200, 10, 90))
    manifest = tmp_path / "species-x.csv"
    write_manifest(
        [
            make_record(source_id="a", image_path="a.png", sha256="a" * 64),
            make_record(source="commons", source_id="b", image_path="b.png", sha256="b" * 64,
                        label_status="unreviewed"),
        ],
        manifest,
    )
    out = tmp_path / "splits.csv"
    assert cli.main(["split", "--manifest", str(manifest), "--data-root", str(data_root), "--out", str(out)]) == 0
    assert "left out 1 photos with unreviewed labels" in capsys.readouterr().out
    rows = out.read_text().splitlines()
    assert len(rows) == 2 and "a" * 64 in rows[1]


def test_split_merges_groups_of_near_duplicates(tmp_path):
    data_root = tmp_path / "data"
    _image(data_root / "a.png", (10, 20, 30))
    # The same picture, resized: a near-duplicate under another photographer's group.
    Image.open(data_root / "a.png").resize((24, 24)).save(data_root / "a-small.png")
    manifest = tmp_path / "species-x.csv"
    write_manifest(
        [
            make_record(source_id="a", image_path="a.png", sha256="a" * 64, group_id="user-1"),
            make_record(source="gbif", source_id="a2", image_path="a-small.png", sha256="c" * 64,
                        group_id="user-2"),
        ],
        manifest,
    )
    out = tmp_path / "splits.csv"
    cli.main(["split", "--manifest", str(manifest), "--data-root", str(data_root), "--out", str(out)])
    groups = {line.split(",")[3] for line in out.read_text().splitlines()[1:]}
    assert groups == {"user-1"}
    assert EXCLUDED not in out.read_text()


def test_lock_held_by_another_process_is_a_clear_error(tmp_path, capsys):
    import os

    manifest = tmp_path / "species-inaturalist.csv"
    (tmp_path / "species-inaturalist.csv.lock").write_text(str(os.getppid()))
    code = cli.main(["inat-download", "--manifest", str(manifest), "--data-root", str(tmp_path), "--class", "maize"])
    assert code == 1
    assert "one process per source" in capsys.readouterr().err


def test_os_errors_end_with_a_message_not_a_traceback(monkeypatch, capsys):
    def broken(arguments):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cli, "_run_split", broken)
    assert cli.main(["split"]) == 1
    assert "No space left on device" in capsys.readouterr().err
