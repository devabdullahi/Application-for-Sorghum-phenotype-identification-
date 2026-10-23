from sorghum_model import inat
from sorghum_model.inat import select_photos


def _observation(*photos):
    return {"id": 10, "user": {"id": 7}, "observed_on": "2025-08-01", "photos": list(photos)}


def _photo(photo_id, license_code):
    return {
        "id": photo_id,
        "license_code": license_code,
        "url": f"https://inaturalist-open-data.s3.amazonaws.com/photos/{photo_id}/square.jpg",
        "attribution": "(c) Someone",
    }


def test_keeps_allowed_licences_at_medium_size():
    observation = _observation(
        _photo(1, "cc-by-nc-nd"), _photo(2, "cc0"), _photo(3, "cc-by-nc"), _photo(4, None)
    )
    photos = select_photos(observation, "maize", 3)
    assert [p.record_without_file["source_id"] for p in photos] == ["2", "3"]
    assert photos[0].url.endswith("/2/medium.jpg")
    assert photos[1].record_without_file["license"] == "cc-by-nc"


def test_asks_the_api_for_every_allowed_licence(monkeypatch):
    requested = []

    def fake_get_json(url, params):
        requested.append(params)
        return {"results": []}

    monkeypatch.setattr(inat, "get_json", fake_get_json)
    assert list(inat.fetch_observations(58389, 10)) == []
    assert requested[0]["photo_license"] == "cc-by,cc-by-nc,cc-by-nc-sa,cc-by-sa,cc0"
    assert requested[0]["quality_grade"] == "research"


def test_pages_by_id_until_the_limit(monkeypatch):
    pages = iter([{"results": [{"id": 1}, {"id": 2}]}, {"results": [{"id": 3}]}])
    seen_ids_above = []

    def fake_get_json(url, params):
        seen_ids_above.append(params["id_above"])
        return next(pages)

    monkeypatch.setattr(inat, "get_json", fake_get_json)
    assert [o["id"] for o in inat.fetch_observations(1, 3)] == [1, 2, 3]
    assert seen_ids_above == [0, 2]


def test_groups_by_observer_and_records_provenance():
    record = select_photos(_observation(_photo(2, "cc-by")), "maize", 3)[0].record_without_file
    assert record["group_id"] == "inaturalist-user-7"
    assert record["label_source"] == "inaturalist research-grade observation 10"
    assert record["image_path"] == "inaturalist/2.jpg"


def test_caps_photos_per_observation():
    observation = _observation(*[_photo(i, "cc-by") for i in range(5)])
    assert len(select_photos(observation, "maize", 2)) == 2
