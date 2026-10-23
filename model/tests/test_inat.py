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
    photos = select_photos(_observation(_photo(1, "cc-by-nc-nd"), _photo(2, "cc0")), "maize", 3)
    assert [p.record_without_file["source_id"] for p in photos] == ["2"]
    assert photos[0].url.endswith("/2/medium.jpg")


def test_groups_by_observer_and_records_provenance():
    record = select_photos(_observation(_photo(2, "cc-by")), "maize", 3)[0].record_without_file
    assert record["group_id"] == "inaturalist-user-7"
    assert record["label_source"] == "inaturalist research-grade observation 10"
    assert record["image_path"] == "inaturalist/2.jpg"


def test_caps_photos_per_observation():
    observation = _observation(*[_photo(i, "cc-by") for i in range(5)])
    assert len(select_photos(observation, "maize", 2)) == 2
