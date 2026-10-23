from sorghum_model import commons
from sorghum_model.commons import select_photo


def _page(license="cc-by-sa-4.0", mime="image/jpeg", **metadata):
    extmetadata = {
        "License": {"value": license},
        "LicenseShortName": {"value": "CC BY-SA 4.0"},
        "Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:Ann">Ann &amp; Bo</a>'},
        "DateTimeOriginal": {"value": "2019-08-02 10:11:12"},
    }
    extmetadata.update({key: {"value": value} for key, value in metadata.items()})
    return {
        "pageid": 123,
        "title": "File:Sorghum field.jpg",
        "imageinfo": [
            {
                "mime": mime,
                "thumburl": "https://upload.wikimedia.org/thumb/500px-Sorghum.jpg",
                "user": "Ann",
                "timestamp": "2020-01-05T00:00:00Z",
                "extmetadata": extmetadata,
            }
        ],
    }


def test_builds_record_with_plain_text_credit():
    photo = select_photo(_page(), "sorghum_bicolor", "Sorghum bicolor")
    fields = photo.record_without_file
    assert photo.url.endswith("500px-Sorghum.jpg")
    assert fields["license"] == "cc-by-sa"
    assert fields["group_id"] == "commons-user-ann"
    assert fields["attribution"].startswith("(c) Ann & Bo, cc-by-sa-4.0, File:Sorghum field.jpg")
    assert fields["label_source"] == (
        "wikimedia commons category 'Sorghum bicolor' (editor-assigned)"
    )
    assert fields["labelled_on"] == "2019-08-02"


def test_falls_back_to_upload_date_when_taken_date_is_free_text():
    page = _page(DateTimeOriginal="summer 2019")
    assert select_photo(page, "maize", "Zea mays").record_without_file["labelled_on"] == "2020-01-05"


def test_skips_disallowed_licences_and_non_photos():
    assert select_photo(_page(license="cc-by-nd-4.0"), "maize", "Zea mays") is None
    assert select_photo(_page(license="pd", LicenseShortName="Public domain"), "maize", "Zea mays") is None
    assert select_photo(_page(mime="image/svg+xml"), "maize", "Zea mays") is None
    assert select_photo({"pageid": 1, "title": "File:x"}, "maize", "Zea mays") is None


def test_uses_short_name_when_machine_licence_is_missing():
    page = _page(license="", LicenseShortName="CC BY 4.0")
    assert select_photo(page, "maize", "Zea mays").record_without_file["license"] == "cc-by"


def test_follows_continuation_without_subcategories(monkeypatch):
    responses = iter(
        [
            {"query": {"pages": [{"pageid": 1}]}, "continue": {"gcmcontinue": "next", "continue": "gcmcontinue||"}},
            {"query": {"pages": [{"pageid": 2}]}},
        ]
    )
    requests = []

    def fake_get_json(url, params):
        requests.append(params)
        return next(responses)

    monkeypatch.setattr(commons, "get_json", fake_get_json)
    assert [p["pageid"] for p in commons.fetch_category_files("Zea mays", 10)] == [1, 2]
    assert requests[0]["gcmtitle"] == "Category:Zea mays"
    assert requests[0]["gcmtype"] == "file"
    assert requests[1]["gcmcontinue"] == "next"


def test_skips_files_imported_from_inaturalist_or_flickr():
    from_inat = _page(Credit='<a href="https://www.inaturalist.org/photos/123">iNaturalist</a>')
    assert select_photo(from_inat, "sorghum_bicolor", "Sorghum bicolor") is None
    from_flickr = _page(Artist='<a href="https://www.flickr.com/people/ann">Ann</a>')
    assert select_photo(from_flickr, "sorghum_bicolor", "Sorghum bicolor") is None
    by_bot = _page()
    by_bot["imageinfo"][0]["user"] = "Flickr upload bot"
    assert select_photo(by_bot, "sorghum_bicolor", "Sorghum bicolor") is None


def test_own_uploads_are_kept_and_unreviewed():
    fields = select_photo(_page(Credit="Own work"), "sorghum_bicolor", "Sorghum bicolor").record_without_file
    assert fields["label_status"] == "unreviewed"
