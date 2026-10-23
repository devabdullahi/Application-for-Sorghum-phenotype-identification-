from conftest import make_record
from sorghum_model.near_duplicates import load_hashes, resolve_near_duplicates


def _records(*specs):
    return [
        make_record(source_id=str(i), sha256=f"{i:064d}", group_id=group, class_name=name)
        for i, (group, name) in enumerate(specs)
    ]


def test_same_class_near_duplicates_share_the_whole_group():
    records = _records(("user-b", "maize"), ("user-a", "maize"), ("user-b", "maize"))
    # Photos 0 and 1 differ in 3 bits; photo 2 is another photo of user-b.
    hashes = {records[0].sha256: 0b1011, records[1].sha256: 0b0100, records[2].sha256: 1 << 60}
    result = resolve_near_duplicates(records, hashes, max_distance=4)
    assert [r.group_id for r in result.records] == ["user-a", "user-a", "user-a"]
    assert result.merged_groups == 1 and result.dropped == []


def test_distance_just_above_the_limit_is_not_a_duplicate():
    records = _records(("user-a", "maize"), ("user-b", "maize"))
    hashes = {records[0].sha256: 0, records[1].sha256: 0b11111}  # 5 bits apart
    result = resolve_near_duplicates(records, hashes, max_distance=4)
    assert [r.group_id for r in result.records] == ["user-a", "user-b"]


def test_conflicting_labels_drop_both_copies():
    records = _records(("user-a", "maize"), ("user-b", "sorghum_bicolor"), ("user-c", "maize"))
    hashes = {records[0].sha256: 7, records[1].sha256: 7, records[2].sha256: 0xFFFF << 40}
    result = resolve_near_duplicates(records, hashes, max_distance=4)
    assert [r.source_id for r in result.records] == ["2"]
    assert sorted(r.source_id for r in result.dropped) == ["0", "1"]


def test_unreadable_images_are_dropped():
    records = _records(("user-a", "maize"))
    result = resolve_near_duplicates(records, {records[0].sha256: None}, max_distance=4)
    assert result.records == [] and result.dropped == records


def test_hashes_are_cached_by_checksum(tmp_path):
    records = _records(("user-a", "maize"))
    calls = []

    def fake_hash(path):
        calls.append(path)
        return 42

    assert load_hashes(records, tmp_path, fake_hash) == {records[0].sha256: 42}
    assert load_hashes(records, tmp_path, fake_hash) == {records[0].sha256: 42}
    assert len(calls) == 1


def test_exempt_sources_are_kept_and_never_compared():
    records = [
        make_record(source="grainset-sorghum", source_id="1", sha256="1" * 64, group_id="s"),
        make_record(source="grainset-maize", source_id="2", sha256="2" * 64, group_id="m", class_name="maize"),
        make_record(source="inaturalist", source_id="3", sha256="3" * 64, group_id="i", class_name="maize"),
    ]
    hashes = {r.sha256: 5 for r in records}  # identical hashes
    result = resolve_near_duplicates(records, hashes, 4, exempt_sources=("grainset-sorghum", "grainset-maize"))
    assert sorted(r.source_id for r in result.records) == ["1", "2", "3"]
    assert result.dropped == [] and result.merged_groups == 0
