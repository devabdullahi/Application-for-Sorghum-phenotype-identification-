import hashlib

from sorghum_model import gbif
from sorghum_model.gbif import INATURALIST_DATASET_KEY, select_photos

IMAGE_URL = "https://media.example.org/sheet-1.jpg"


def _occurrence(*media, **fields):
    occurrence = {
        "key": 42,
        "datasetKey": "herbarium-dataset",
        "basisOfRecord": "PRESERVED_SPECIMEN",
        "license": "http://creativecommons.org/licenses/by/4.0/legalcode",
        "recordedBy": "Silva, R.M.",
        "institutionCode": "HJ",
        "eventDate": "2023-04-14T00:00:00",
        "media": list(media),
    }
    occurrence.update(fields)
    return occurrence


def _media(identifier=IMAGE_URL, license=None, **fields):
    media = {"type": "StillImage", "identifier": identifier, "creator": "R. Silva", **fields}
    if license is not None:
        media["license"] = license
    return media


def test_uses_the_gbif_image_cache_and_records_provenance():
    record = select_photos(_occurrence(_media()), "pearl_millet", 2)[0]
    md5 = hashlib.md5(IMAGE_URL.encode()).hexdigest()
    assert record.url == f"https://api.gbif.org/v1/image/cache/500x/occurrence/42/media/{md5}"
    fields = record.record_without_file
    assert fields["license"] == "cc-by"
    assert fields["group_id"] == "gbif-recorded-by-silva, r.m."
    assert fields["label_source"] == "gbif preserved_specimen occurrence 42 (dataset herbarium-dataset)"
    assert fields["labelled_on"] == "2023-04-14"
    assert fields["source_id"] == f"42-{md5[:12]}"


def test_media_licence_overrides_a_looser_record_licence():
    # observation.org publishes CC BY-NC records whose photos are CC BY-NC-ND.
    occurrence = _occurrence(
        _media(license="http://creativecommons.org/licenses/by-nc-nd/4.0/"),
        _media(identifier="https://media.example.org/2.jpg",
               license="http://creativecommons.org/licenses/by-nc/4.0/"),
        license="http://creativecommons.org/licenses/by-nc/4.0/legalcode",
    )
    photos = select_photos(occurrence, "sorghum_bicolor", 3)
    assert [p.record_without_file["license"] for p in photos] == ["cc-by-nc"]


def test_skips_viewer_links_without_an_image_file():
    viewer_only = {"type": "StillImage", "references": "http://viewer.example/x.dzi"}
    assert select_photos(_occurrence(viewer_only), "pearl_millet", 2) == []


def test_skips_machine_and_fossil_records():
    for basis in ("MACHINE_OBSERVATION", "FOSSIL_SPECIMEN"):
        assert select_photos(_occurrence(_media(), basisOfRecord=basis), "maize", 2) == []


def test_groups_by_institution_then_dataset_when_no_recorder():
    by_institution = select_photos(_occurrence(_media(), recordedBy=None), "maize", 1)[0]
    by_dataset = select_photos(
        _occurrence(_media(), recordedBy="", institutionCode=None), "maize", 1
    )[0]
    assert by_institution.record_without_file["group_id"] == "gbif-institution-hj"
    assert by_dataset.record_without_file["group_id"] == "gbif-dataset-herbarium-dataset"


def test_caps_photos_per_occurrence():
    media = [_media(identifier=f"https://media.example.org/{i}.jpg") for i in range(4)]
    assert len(select_photos(_occurrence(*media), "maize", 2)) == 2


def test_fetch_skips_inaturalist_and_pages_until_end(monkeypatch):
    pages = iter(
        [
            {"results": [{"key": 1, "datasetKey": INATURALIST_DATASET_KEY}, {"key": 2}],
             "endOfRecords": False},
            {"results": [{"key": 3}], "endOfRecords": True},
        ]
    )
    requests = []

    def fake_get_json(url, params):
        requests.append(params)
        return next(pages)

    monkeypatch.setattr(gbif, "get_json", fake_get_json)
    assert [o["key"] for o in gbif.fetch_occurrences(2705181, 10)] == [2, 3]
    assert [r["offset"] for r in requests] == [0, 300]
    assert requests[0]["mediaType"] == "StillImage"
    assert requests[0]["license"] == ["CC0_1_0", "CC_BY_4_0", "CC_BY_NC_4_0"]
    assert "FOSSIL_SPECIMEN" not in requests[0]["basisOfRecord"]
    assert "MACHINE_OBSERVATION" not in requests[0]["basisOfRecord"]


def test_skips_plantnet_machine_identified_records():
    occurrence = _occurrence(
        _media(), basisOfRecord="HUMAN_OBSERVATION", datasetKey=gbif.PLANTNET_AUTOMATIC_DATASET_KEY
    )
    assert select_photos(occurrence, "sorghum_bicolor", 2) == []


def test_names_citizen_science_portals_in_the_label_source():
    occurrence = _occurrence(
        _media(), basisOfRecord="HUMAN_OBSERVATION", datasetKey="8a863029-f435-446a-821e-275f4f641165"
    )
    fields = select_photos(occurrence, "sorghum_bicolor", 2)[0].record_without_file
    assert fields["label_source"] == (
        "gbif human_observation occurrence 42 "
        "(observation.org, dataset 8a863029-f435-446a-821e-275f4f641165)"
    )
    assert fields["label_status"] == "verified"
