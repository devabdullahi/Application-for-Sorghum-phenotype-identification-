from collections import Counter

import pytest

from conftest import make_record
from sorghum_model.splits import (
    Split,
    assign_split,
    find_undersized_classes,
    read_split_manifest,
    split_records,
    write_split_manifest,
)


def test_same_group_always_same_split():
    records = [make_record(source_id=str(i), sha256=f"{i:064x}") for i in range(20)]
    splits = split_records(records, 0.15, 0.15, "salt")
    assert len(set(splits.values())) == 1


def test_assignment_is_deterministic_and_salted():
    groups = [f"group-{i}" for i in range(200)]
    first = [assign_split(g, 0.15, 0.15, "a") for g in groups]
    assert first == [assign_split(g, 0.15, 0.15, "a") for g in groups]
    assert first != [assign_split(g, 0.15, 0.15, "b") for g in groups]


def test_fractions_are_roughly_respected():
    counts = Counter(assign_split(f"g{i}", 0.15, 0.15, "s") for i in range(10_000))
    assert counts[Split.TEST] == pytest.approx(1500, abs=150)
    assert counts[Split.VALIDATION] == pytest.approx(1500, abs=150)


@pytest.mark.parametrize("validation, test", [(0, 0.1), (0.1, 1), (0.5, 0.5)])
def test_rejects_invalid_fractions(validation, test):
    with pytest.raises(ValueError):
        assign_split("g", validation, test, "s")


def test_undersized_classes_at_and_below_minimum():
    counts = Counter(
        {("maize", Split.TRAIN): 50, ("maize", Split.VALIDATION): 10, ("maize", Split.TEST): 9}
    )
    assert find_undersized_classes(counts, ("maize",), 50, 10) == [
        "maize: 9 test photos, need 10"
    ]


def test_split_manifest_round_trips(tmp_path):
    records = [make_record(), make_record(source_id="2", sha256="b" * 64, group_id="other")]
    splits = split_records(records, 0.15, 0.15, "s")
    path = tmp_path / "splits.csv"
    write_split_manifest(records, splits, path)
    assert read_split_manifest(path) == splits
