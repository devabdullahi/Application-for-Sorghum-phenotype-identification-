"""Joining race photos from the cultivar manifest and split, the head's race order and weights."""

import csv

import pytest

from sorghum_model.cultivar_manifest import write_cultivar_manifest
from sorghum_model.race_photos import (
    RacePhoto,
    balanced_race_weights,
    race_class_names,
    read_race_photos,
    undersized_races,
)
from sorghum_model.splits import Split
from tests.test_cultivar_data import make_cultivar_record

SPLIT_COLUMNS = ["sha256", "source", "source_id", "cultivar_label", "planting_id", "accession_split",
                 "planting_split", "race", "race_exclusion"]


def write_split(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SPLIT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def split_row(record, accession_split, race, exclusion=""):
    return {
        "sha256": record.sha256, "source": record.source, "source_id": record.source_id,
        "cultivar_label": record.cultivar_label, "planting_id": record.planting_id,
        "accession_split": accession_split, "planting_split": "train", "race": race, "race_exclusion": exclusion,
    }


def test_reads_only_photos_with_a_scored_race(tmp_path):
    durra, mixed = make_cultivar_record("PI 1", "A"), make_cultivar_record("PI 2", "A")
    write_cultivar_manifest([durra, mixed], tmp_path / "manifest.csv")
    write_split(tmp_path / "split.csv", [split_row(durra, "test", "Durra"), split_row(mixed, "train", "", "not-a-race")])

    photos = read_race_photos(tmp_path / "manifest.csv", tmp_path / "split.csv")

    assert photos == [RacePhoto(durra.image_path, durra.sha256, "PI 1", "A", Split.TEST, "Durra")]


def test_refuses_a_split_row_missing_from_the_manifest(tmp_path):
    durra = make_cultivar_record("PI 1", "A")
    write_cultivar_manifest([], tmp_path / "manifest.csv")
    write_split(tmp_path / "split.csv", [split_row(durra, "train", "Durra")])
    with pytest.raises(ValueError, match="not in"):
        read_race_photos(tmp_path / "manifest.csv", tmp_path / "split.csv")


def test_refuses_an_accession_in_two_splits(tmp_path):
    first, second = make_cultivar_record("PI 1", "A"), make_cultivar_record("PI 1", "B")
    write_cultivar_manifest([first, second], tmp_path / "manifest.csv")
    write_split(tmp_path / "split.csv", [split_row(first, "train", "Durra"), split_row(second, "test", "Durra")])
    with pytest.raises(ValueError, match="leaks"):
        read_race_photos(tmp_path / "manifest.csv", tmp_path / "split.csv")


def photo(race, split=Split.TRAIN):
    return RacePhoto("x.jpg", "0" * 64, "PI 1", "A", split, race)


def test_race_order_is_alphabetical_over_training_races_only():
    photos = [photo("Kafir"), photo("Durra"), photo("Kafir"), photo("Guinea", Split.TEST)]
    assert race_class_names(photos) == ("Durra", "Kafir")


def test_balanced_weights_give_each_race_the_same_total_weight():
    train = [photo("Durra")] * 3 + [photo("Kafir")]
    weights = balanced_race_weights(train, ("Durra", "Kafir"))
    assert weights == {0: pytest.approx(4 / 6), 1: pytest.approx(2.0)}
    assert 3 * weights[0] == pytest.approx(1 * weights[1])


def test_balanced_weights_refuse_a_race_without_training_photos():
    with pytest.raises(ValueError, match="without training photos"):
        balanced_race_weights([photo("Durra")], ("Durra", "Kafir"))


def test_undersized_races_checks_each_split_at_its_minimum():
    photos = [photo("Durra")] * 3 + [photo("Durra", Split.VALIDATION)] * 2 + [photo("Durra", Split.TEST)] * 2
    assert undersized_races(photos, ("Durra",), 3, 2) == []  # at both minimums
    assert undersized_races(photos, ("Durra",), 4, 2) == ["Durra: 3 train photos (minimum 4)"]
    assert undersized_races(photos, ("Durra",), 3, 3) == [
        "Durra: 2 validation photos (minimum 3)",
        "Durra: 2 test photos (minimum 3)",
    ]
    assert undersized_races(photos, ("Durra",), 2, 1) == []  # below both
