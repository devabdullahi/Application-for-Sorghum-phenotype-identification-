import hashlib
import io
import urllib.error

import pytest

from sorghum_model import downloads
import email.utils
import os
from pathlib import Path

from sorghum_model.downloads import RequestPacer, download_file, get_json, partial_path, retry_after_seconds


class _Response(io.BytesIO):
    """Stands in for an HTTP response: readable bytes, a status, headers and a context manager.

    Content-Length defaults to the body's length, as a real server sends it.
    """

    def __init__(self, body: bytes, status: int = 200, content_length: int | None = None):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Length": str(len(body) if content_length is None else content_length)}


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


def test_short_body_is_resumed_instead_of_accepted(tmp_path, monkeypatch):
    # urllib returns a short body silently when the connection drops; the length check must
    # turn that into a retry that resumes from the bytes already saved.
    destination = tmp_path / "a.zip"
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.get_header("Range"))
        if len(calls) == 1:
            return _Response(b"hel", content_length=11)
        return _Response(b"lo world", status=206)

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fake_urlopen)
    download_file("https://files.example/a.zip", destination)
    assert calls == [None, "bytes=3-"]
    assert destination.read_bytes() == b"hello world"


def test_partial_file_name_carries_the_process_id(tmp_path, monkeypatch):
    seen = []

    def fake_urlopen(request, timeout):
        return _Response(b"data")

    original_rename = Path.rename

    def recording_rename(self, target):
        seen.append(self.name)
        return original_rename(self, target)

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(Path, "rename", recording_rename)
    download_file("https://files.example/a.jpg", tmp_path / "a.jpg")
    assert seen == [f"a.jpg.{os.getpid()}.part"]


def test_adopts_the_part_of_a_process_that_ended(tmp_path, monkeypatch):
    destination = tmp_path / "big.zip"
    dead_pid = 2_000_000_000  # above any real pid
    (tmp_path / f"big.zip.{dead_pid}.part").write_bytes(b"first-")
    ranges = []

    def fake_urlopen(request, timeout):
        ranges.append(request.get_header("Range"))
        return _Response(b"second", status=206)

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fake_urlopen)
    download_file("https://files.example/big.zip", destination)
    assert ranges == ["bytes=6-"]
    assert destination.read_bytes() == b"first-second"


def test_leaves_the_part_of_a_running_process_alone(tmp_path, monkeypatch):
    destination = tmp_path / "big.zip"
    running = tmp_path / f"big.zip.{os.getppid()}.part"  # our parent is alive
    running.write_bytes(b"theirs")
    monkeypatch.setattr(
        downloads.urllib.request, "urlopen", lambda request, timeout: _Response(b"mine")
    )
    download_file("https://files.example/big.zip", destination)
    assert destination.read_bytes() == b"mine"
    assert running.read_bytes() == b"theirs"
    assert not partial_path(destination).exists()


def test_rate_limit_waits_as_long_as_retry_after_asks(monkeypatch):
    slept = []
    monkeypatch.setattr(downloads.time, "sleep", slept.append)
    responses = iter(
        [urllib.error.HTTPError("u", 429, "slow down", {"Retry-After": "120"}, None),
         _Response(b"{}")]
    )

    def fake_urlopen(request, timeout):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fake_urlopen)
    get_json("https://api.example")
    assert slept == [120.0]  # longer than the first default wait of 10 s


def test_gives_up_when_retry_after_is_unreasonably_long(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError("u", 429, "come back tomorrow", {"Retry-After": "86400"}, None)

    monkeypatch.setattr(downloads.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        get_json("https://api.example")


def test_parses_retry_after_seconds_and_dates():
    assert retry_after_seconds("30") == 30.0
    assert retry_after_seconds(email.utils.formatdate(1_000_090, usegmt=True), now=1_000_000) == 90.0
    assert retry_after_seconds("soon") is None
    assert retry_after_seconds(None) is None
