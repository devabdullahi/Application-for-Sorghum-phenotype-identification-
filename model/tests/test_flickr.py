import pytest

from sorghum_model import flickr
from sorghum_model.flickr import api_key_from_environment, select_photo


def _photo(license="11", url_m="https://live.staticflickr.com/1/2_m.jpg"):
    return {
        "id": "2", "owner": "99@N01", "ownername": "Kim", "license": license,
        "datetaken": "2021-03-04 05:06:07", "url_m": url_m,
    }


def test_missing_key_fails_with_instructions(monkeypatch):
    monkeypatch.delenv("FLICKR_API_KEY", raising=False)
    with pytest.raises(ValueError, match="FLICKR_API_KEY is not set"):
        api_key_from_environment()


def test_reads_key_from_environment(monkeypatch):
    monkeypatch.setenv("FLICKR_API_KEY", " abc ")
    assert api_key_from_environment() == "abc"


def test_builds_unreviewed_record_grouped_by_owner():
    fields = select_photo(_photo(), "no_plant", "bare soil").record_without_file
    assert fields["license"] == "cc-by"
    assert fields["group_id"] == "flickr-owner-99@N01"
    assert fields["label_source"] == "flickr search 'bare soil' (unreviewed)"
    assert fields["labelled_on"] == "2021-03-04"


@pytest.mark.parametrize("license", ["0", "3", "6", "10", "16"])
def test_skips_disallowed_licences(license):
    assert select_photo(_photo(license=license), "no_plant", "bare soil") is None


def test_skips_photos_without_a_download_size():
    assert select_photo(_photo(url_m=None), "no_plant", "bare soil") is None


def test_search_raises_on_api_error(monkeypatch):
    monkeypatch.setattr(
        flickr, "get_json", lambda url, params: {"stat": "fail", "message": "Invalid API Key"}
    )
    with pytest.raises(ValueError, match="Invalid API Key"):
        list(flickr.search_photos("bad", "bare soil", 10))


def test_search_stops_at_last_page(monkeypatch):
    pages = iter([{"stat": "ok", "photos": {"pages": 1, "photo": [{"id": "1"}, {"id": "2"}]}}])
    monkeypatch.setattr(flickr, "get_json", lambda url, params: next(pages))
    assert [p["id"] for p in flickr.search_photos("key", "bare soil", 10)] == ["1", "2"]
