"""
Exercises GoogleDriveStorage.upload()'s resumable/chunked transfer logic
(Section 2) directly, against a fake googleapiclient-shaped `request`
object - without any real network call to Google Drive. FakeStorageService
(used everywhere else in the suite) deliberately doesn't reimplement
Drive's resumable chunk protocol, so this is the one place that logic
gets exercised.
"""

import io
import threading

import pytest

from app.config.settings import Settings
from app.services import google_drive_service as gd_module
from app.services.storage_service import StorageTimeoutError


class _FakeProgress:
    def __init__(self, resumable_progress):
        self.resumable_progress = resumable_progress


class _ScriptedRequest:
    """
    Simulates googleapiclient's HttpRequest.next_chunk(): each call either
    returns (status, None) for an in-progress chunk, (None, response) for
    the final chunk, or raises to simulate a transient failure.
    """

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.http_clients = []

    def next_chunk(self, http=None):
        self.calls += 1
        # Record the HTTP client each chunk was routed through, so tests
        # can assert the per-upload client isolation that makes concurrent
        # uploads safe (httplib2.Http is not thread-safe when shared).
        self.http_clients.append(http)
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class _FakeFilesResource:
    def __init__(self, request):
        self._request = request

    def create(self, body, media_body, fields):
        return self._request


class _FakeService:
    def __init__(self, request):
        self._request = request

    def files(self):
        return _FakeFilesResource(self._request)


def _build_storage(monkeypatch, request, **settings_overrides):
    monkeypatch.setattr(gd_module, "build", lambda *a, **k: _FakeService(request))
    settings = Settings(
        google_drive_refresh_token="fake-refresh-token",
        google_drive_client_id="fake-client-id",
        google_drive_client_secret="fake-secret",
        **settings_overrides,
    )
    return gd_module.GoogleDriveStorage(settings)


def test_upload_walks_through_multiple_chunks_and_reports_progress(monkeypatch):
    final = {"id": "abc123", "name": "video.mp4", "size": "300", "mimeType": "video/mp4"}
    script = [
        (_FakeProgress(100), None),
        (_FakeProgress(200), None),
        (_FakeProgress(300), None),
        (None, final),
    ]
    request = _ScriptedRequest(script)
    storage = _build_storage(monkeypatch, request)

    progress_calls = []
    result = storage.upload(
        io.BytesIO(b"x" * 300),
        "video.mp4",
        "video/mp4",
        "parent-folder-id",
        progress_callback=lambda uploaded, total: progress_calls.append((uploaded, total)),
        upload_id="chunked-upload-id",
    )

    assert result.provider_file_id == "abc123"
    assert request.calls == 4
    # Never reports the final size before the loop actually finished.
    assert progress_calls[-1] == (300, 300)
    assert all(uploaded <= 300 for uploaded, _ in progress_calls)


def test_upload_retries_a_transient_chunk_failure_then_continues(monkeypatch):
    from googleapiclient.errors import HttpError

    class _FakeResp:
        status = 503
        reason = "Service Unavailable"

    transient_error = HttpError(_FakeResp(), b"service unavailable")
    final = {"id": "abc123", "name": "a.jpg", "size": "10", "mimeType": "image/jpeg"}
    script = [transient_error, (None, final)]
    request = _ScriptedRequest(script)
    storage = _build_storage(monkeypatch, request, upload_initial_backoff_seconds=0.01, upload_max_backoff_seconds=0.02)

    result = storage.upload(io.BytesIO(b"x" * 10), "a.jpg", "image/jpeg", "parent-folder-id")

    assert result.provider_file_id == "abc123"
    assert request.calls == 2  # first failed transiently, second succeeded


def test_upload_does_not_retry_permanent_auth_failure(monkeypatch):
    from googleapiclient.errors import HttpError

    from app.services.storage_service import StorageError

    class _FakeResp:
        status = 401
        reason = "Unauthorized"

    permanent_error = HttpError(_FakeResp(), b"invalid credentials")
    request = _ScriptedRequest([permanent_error])
    storage = _build_storage(monkeypatch, request)

    with pytest.raises(StorageError):
        storage.upload(io.BytesIO(b"x" * 10), "a.jpg", "image/jpeg", "parent-folder-id")

    assert request.calls == 1  # never retried


def test_upload_session_timeout_raises_storage_timeout_error(monkeypatch):
    request = _ScriptedRequest([(_FakeProgress(0), None)] * 100000)
    storage = _build_storage(monkeypatch, request, upload_session_timeout=0)

    with pytest.raises(StorageTimeoutError):
        storage.upload(io.BytesIO(b"x" * 10), "a.jpg", "image/jpeg", "parent-folder-id")


def test_concurrent_uploads_do_not_share_an_http_client(monkeypatch):
    # Each upload() creates its own authorized httplib2 client (build()'s
    # shared client is not thread-safe - concurrent resumable uploads on it
    # cross byte-streams and produce Drive 400 "size mismatch" errors).
    # This asserts two simultaneous uploads are routed through distinct
    # clients, so they can never borrow each other's sockets.
    requests = [_ScriptedRequest([(None, {"id": f"file{i}", "name": f"f{i}", "size": "1", "mimeType": "image/png"})]) for i in range(2)]

    # Reuse the fake-service scaffolding but give each upload a different
    # request; simplest via a factory that hands out requests round-robin.
    class _RoundRobinService:
        def __init__(self, reqs):
            self._reqs = iter(reqs)

        def files(self):
            req = next(self._reqs)
            return _FakeFilesResource(req)

    monkeypatch.setattr(gd_module, "build", lambda *a, **k: _RoundRobinService(requests))
    settings = Settings(
        google_drive_refresh_token="fake-refresh-token",
        google_drive_client_id="fake-client-id",
        google_drive_client_secret="fake-secret",
    )
    storage = gd_module.GoogleDriveStorage(settings)

    results = []
    barrier = threading.Barrier(2)

    def _upload(i, payload):
        barrier.wait()
        results.append(
            storage.upload(io.BytesIO(payload), f"f{i}.png", "image/png", "parent-folder-id")
        )

    threads = [
        threading.Thread(target=_upload, args=(0, b"a" * 10)),
        threading.Thread(target=_upload, args=(1, b"b" * 10)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert {r.provider_file_id for r in results} == {"file0", "file1"}
    client0, client1 = requests[0].http_clients[0], requests[1].http_clients[0]
    assert client0 is not None and client1 is not None
    assert client0 is not client1


def test_chunk_size_setting_is_aligned_to_256kb_multiple():
    settings = Settings(
        google_drive_refresh_token="t",
        upload_chunk_size_mb=1,  # 1 MB is already aligned
    )
    assert settings.upload_chunk_size_bytes == 1024 * 1024

    settings2 = Settings(google_drive_refresh_token="t", upload_chunk_size_mb=0.3)
    # Rounded DOWN to the nearest 256 KiB multiple, never zero.
    assert settings2.upload_chunk_size_bytes % (256 * 1024) == 0
    assert settings2.upload_chunk_size_bytes > 0
