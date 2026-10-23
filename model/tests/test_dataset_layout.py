import zipfile

import pytest

from sorghum_model.dataset_layout import (
    extract_zip,
    grainset_path,
    sequence_block,
    sorghum_disease_path,
    sorghum_weed_path,
)


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("Rust1", "rust-0000"),
        ("Rust20", "rust-0000"),  # last file of the first block of 20
        ("Rust21", "rust-0001"),  # first file of the next block
        ("SorghumTrain (12)", "sorghumtrain-0000"),
        ("Cereal Grain molds (White Fungi)t45", "cereal-grain-molds-white-fungi-t-0002"),
        ("cover", "cover"),
    ],
)
def test_sequence_block_groups_consecutive_numbers(stem, expected):
    assert sequence_block(stem, 20) == expected


def test_sorghum_weed_maps_class_folders():
    entry = "SorghumWeedDataset_Classification/Train/Class1_Grass/GrassTrain (3).jpeg"
    assert sorghum_weed_path(entry, 20) == "other_grass/train-class1-grass-grasstrain-0000/GrassTrain (3).jpeg"


def test_sorghum_weed_skips_unknown_folders_and_metadata():
    assert sorghum_weed_path("SorghumWeedDataset_Classification/ReadMe.txt", 20) is None
    assert sorghum_weed_path("X/Train/Class9_Other/a (1).jpeg", 20) is None
    assert sorghum_weed_path("__MACOSX/X/Train/Class0_Sorghum/._a (1).jpeg", 20) is None


def test_sorghum_disease_keeps_diseases_apart():
    assert sorghum_disease_path("Rust5.jpg", 20) == "sorghum_bicolor/rust-0000/Rust5.jpg"
    assert sorghum_disease_path("loose smut (black)5.jpg", 20) == (
        "sorghum_bicolor/loose-smut-black-0000/loose smut (black)5.jpg"
    )


def test_grainset_groups_by_capture_and_skips_masks():
    image = "sorg/train/0_NOR/Grainset_sorg_2021-11-21-23-34-36_20_p600s.png"
    assert grainset_path(image, "sorghum_bicolor") == (
        "sorghum_bicolor/capture-2021-11-21-23-34-36/Grainset_sorg_2021-11-21-23-34-36_20_p600s.png"
    )
    assert grainset_path("sorg/mask/Grainset_sorg_2021-11-21-23-34-36_20_p600s.png", "sorghum_bicolor") is None


def _zip(path, names):
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, name.encode())


def test_extract_zip_rebuilds_paths_and_resumes(tmp_path):
    archive = tmp_path / "a.zip"
    _zip(archive, ["d/Train/Class0_Sorghum/s (1).jpeg", "d/ReadMe.txt"])
    images = tmp_path / "images"
    assert extract_zip(archive, images, lambda name: sorghum_weed_path(name, 20)) == 1
    extracted = images / "sorghum_bicolor/train-class0-sorghum-s-0000/s (1).jpeg"
    assert extracted.read_bytes() == b"d/Train/Class0_Sorghum/s (1).jpeg"
    extracted.write_bytes(b"kept")
    extract_zip(archive, images, lambda name: sorghum_weed_path(name, 20))
    assert extracted.read_bytes() == b"kept"


def test_extract_zip_sample_is_stable_and_grows(tmp_path):
    archive = tmp_path / "grain.zip"
    names = [f"sorg/train/0_NOR/Grainset_sorg_2020-01-01-00-00-{i:02d}_1_p600s.png" for i in range(10)]
    _zip(archive, names)

    def sample(count):
        root = tmp_path / f"sample-{count}"
        extract_zip(archive, root, lambda n: grainset_path(n, "sorghum_bicolor"), max_images=count)
        return {p.name for p in root.rglob("*.png")}

    assert len(sample(3)) == 3
    assert sample(3) <= sample(6)
