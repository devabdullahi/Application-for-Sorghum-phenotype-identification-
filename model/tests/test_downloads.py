import hashlib
import io
import urllib.error

import pytest

from sorghum_model import downloads
from sorghum_model.downloads import RequestPacer, download_file, get_json


class _Response(io.BytesIO):
    """Stands in for an HTTP response: readable bytes, a status and a context manager."""

    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    # Tests must not sleep through the real one-second pacing or retry waits.
    monkeypatch.setattr(downloads, "PACER", RequestPacer(0))
    monkeypatch.setattr(downloads.time, "sleep", lambda seconds: None)


def test_pacer_waits_out_the_rest_of_the_interval():
    now = [100.0]
    slept = []
    pacer = RequestPacer(1.0, clock=lambda: now[0], sleep=slept.append)
    pacer.wait()
    now[0] = 100.25
    pacer.wait()
    assert slept == [0.75]


def test_pacer_does_not_wait_after_a_long_gap():
    now = [0.0]
    slept = []
    pacer = RequestPacer(1.0, clock=lambda: now[0], sleep=slept.append)
    pacer.wait()
    now[0] = 5.0
    pacer.wait()
    assert slept == []


def test_get_json_sends_user_agent_and_repeated_params(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append(request)
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fake_urlopen)
    assert get_json("https://api.example/search", {"license": ["A", "B"], "limit": 3}) == {"ok": True}
    assert sent[0].full_url == "https://api.example/search?license=A&license=B&limit=3"
    assert "sorghum-model-training" in sent[0].get_header("User-agent")


def test_get_json_retries_server_errors(monkeypatch):
    responses = iter(
        [urllib.error.HTTPError("u", 503, "busy", {}, None), _Response(b'{"page": 1}')]
    )

    def fake_urlopen(request, timeout):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fake_urlopen)
    assert get_json("https://api.example") == {"page": 1}


def test_get_json_does_not_retry_client_errors(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError("u", 400, "bad", {}, None)

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        get_json("https://api.example")
    assert len(calls) == 1


def test_download_resumes_a_partial_file(tmp_path, monkeypatch):
    destination = tmp_path / "archive.zip"
    (tmp_path / "archive.zip.part").write_bytes(b"hello ")
    ranges = []

    def fake_urlopen(request, timeout):
        ranges.append(request.get_header("Range"))
        return _Response(b"world", status=206)

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fake_urlopen)
    download_file("https://files.example/a.zip", destination,
                  expected_md5=hashlib.md5(b"hello world").hexdigest())
    assert ranges == ["bytes=6-"]
    assert destination.read_bytes() == b"hello world"
    assert not (tmp_path / "archive.zip.part").exists()


def test_download_restarts_when_the_server_ignores_range(tmp_path, monkeypatch):
    destination = tmp_path / "a.jpg"
    (tmp_path / "a.jpg.part").write_bytes(b"stale")
    monkeypatch.setattr(
        downloads.urllib.request, "urlopen", lambda request, timeout: _Response(b"full", status=200)
    )
    download_file("https://files.example/a.jpg", destination)
    assert destination.read_bytes() == b"full"


def test_download_rejects_a_checksum_mismatch(tmp_path, monkeypatch):
    destination = tmp_path / "a.zip"
    monkeypatch.setattr(
        downloads.urllib.request, "urlopen", lambda request, timeout: _Response(b"corrupt")
    )
    with pytest.raises(ValueError, match="sha256"):
        download_file("https://files.example/a.zip", destination, expected_sha256="0" * 64)
    # Neither a finished file nor a corrupt .part is left for the next run to trust.
    assert not destination.exists()
    assert not (tmp_path / "a.zip.part").exists()


def test_download_skips_existing_files(tmp_path, monkeypatch):
    destination = tmp_path / "a.jpg"
    destination.write_bytes(b"done")

    def fail(request, timeout):
        raise AssertionError("must not download again")

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fail)
    download_file("https://files.example/a.jpg", destination)


def test_download_retry_continues_after_a_dropped_connection(tmp_path, monkeypatch):
    destination = tmp_path / "big.zip"
    calls = []

    class _DroppingResponse(_Response):
        def read(self, size=-1):
            chunk = super().read(size)
            if not chunk:
                raise ConnectionResetError("dropped")
            return chunk

    def fake_urlopen(request, timeout):
        calls.append(request.get_header("Range"))
        if len(calls) == 1:
            return _DroppingResponse(b"first-")
        return _Response(b"second", status=206)

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fake_urlopen)
    download_file("https://files.example/big.zip", destination)
    assert calls == [None, "bytes=6-"]
    assert destination.read_bytes() == b"first-second"
