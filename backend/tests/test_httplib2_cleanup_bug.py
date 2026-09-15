"""
Tests for the httplib2/CPython double-close bug detection and retry logic.

The bug: after a TLS failure mid-transfer, http.client.HTTPResponse._close_conn()
sets self.fp = None then calls fp.close() — raising AttributeError: 'NoneType'
object has no attribute 'close'. This must be treated as a transient, retryable
transport error and translated to StorageError when retries are exhausted.
"""

import http.client
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config.settings import Settings
from app.services import google_drive_service as gd_module
from app.services.google_drive_service import (
    _is_httplib2_cleanup_bug,
    _is_retryable_google_error,
)
from app.services.storage_service import StorageError

CLEANUP_MSG = "'NoneType' object has no attribute 'close'"
UNRELATED_MSG = "'dict' object has no attribute 'items'"


class _ScriptedRequest:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def next_chunk(self, http=None):
        self.calls += 1
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class _FakeFilesResource:
    def __init__(self, request):
        self._request = request

    def create(self, body, media_body, fields):
        return self._request

    def get_media(self, fileId):
        return self._request

    def get(self, fileId, fields):
        return self._request


class _FakeService:
    def __init__(self, request):
        self._request = request

    def files(self):
        return _FakeFilesResource(self._request)


def _build_storage(monkeypatch, request, **overrides):
    monkeypatch.setattr(gd_module, "build", lambda *a, **k: _FakeService(request))
    settings = Settings(
        google_drive_refresh_token="fake-refresh-token",
        google_drive_client_id="fake-client-id",
        google_drive_client_secret="fake-secret",
        **overrides,
    )
    return gd_module.GoogleDriveStorage(settings)


# ---------------------------------------------------------------------------
# _is_httplib2_cleanup_bug detection
# ---------------------------------------------------------------------------


class TestHttplib2CleanupBugDetection:
    def test_matches_exact_cleanup_error(self):
        exc = AttributeError(CLEANUP_MSG)
        assert _is_httplib2_cleanup_bug(exc) is True

    def test_matches_with_prefix_text(self):
        exc = AttributeError("got: " + CLEANUP_MSG)
        assert _is_httplib2_cleanup_bug(exc) is True

    def test_rejects_unrelated_attribute_error(self):
        exc = AttributeError(UNRELATED_MSG)
        assert _is_httplib2_cleanup_bug(exc) is False

    def test_rejects_non_attribute_error(self):
        assert _is_httplib2_cleanup_bug(ValueError("close")) is False

    def test_rejects_empty_args(self):
        exc = AttributeError()
        assert _is_httplib2_cleanup_bug(exc) is False

    def test_rejects_non_string_arg(self):
        exc = AttributeError(42)
        assert _is_httplib2_cleanup_bug(exc) is False


# ---------------------------------------------------------------------------
# _is_retryable_google_error includes the cleanup bug
# ---------------------------------------------------------------------------


class TestRetryableIncludesCleanupBug:
    def test_cleanup_bug_is_retryable(self):
        exc = AttributeError(CLEANUP_MSG)
        assert _is_retryable_google_error(exc) is True

    def test_unrelated_attribute_error_not_retryable(self):
        exc = AttributeError(UNRELATED_MSG)
        assert _is_retryable_google_error(exc) is False


# ---------------------------------------------------------------------------
# Integration: download() retries the cleanup bug and translates to StorageError
# ---------------------------------------------------------------------------


class _FakeDownload:
    """Replaces MediaIoBaseDownload with a scripted next_chunk()."""

    _chunk_payloads = {
        10: b"first-chunk",
        20: b"second-chunk",
    }

    def __init__(self, fd, request, chunksize):
        self._scripted = request
        self._fd = fd

    def next_chunk(self, num_retries=0):
        result = self._scripted.next_chunk()
        progress = result[0]
        if progress is not None:
            self._fd.write(self._chunk_payloads.get(progress.resumable_progress, b"x"))
        return result


class TestDownloadRetriesCleanupBug:
    def test_download_retries_then_succeeds(self, monkeypatch):
        """Simulates: first next_chunk hits the cleanup bug, second succeeds."""
        cleanup_err = AttributeError(CLEANUP_MSG)
        # Script: error → progress (not done) → final chunk (done=True)
        request = _ScriptedRequest([cleanup_err, (_FakeProgress(10), None), (_FakeProgress(20), True)])

        monkeypatch.setattr(gd_module, "build", lambda *a, **k: _FakeService(request))
        monkeypatch.setattr(gd_module, "MediaIoBaseDownload", _FakeDownload)
        settings = Settings(
            google_drive_refresh_token="x",
            google_drive_client_id="x",
            google_drive_client_secret="x",
            upload_initial_backoff_seconds=0.01,
            upload_max_backoff_seconds=0.02,
        )
        storage = gd_module.GoogleDriveStorage(settings)

        chunks = list(storage.download("file-id"))
        assert len(chunks) >= 1
        assert request.calls >= 2

    def test_download_exhausted_retries_raises_storage_error(self, monkeypatch):
        """After max retries, cleanup bug should surface as StorageError."""
        cleanup_err = AttributeError(CLEANUP_MSG)
        request = _ScriptedRequest([cleanup_err] * 10)

        monkeypatch.setattr(gd_module, "build", lambda *a, **k: _FakeService(request))
        monkeypatch.setattr(gd_module, "MediaIoBaseDownload", _FakeDownload)
        settings = Settings(
            google_drive_refresh_token="x",
            google_drive_client_id="x",
            google_drive_client_secret="x",
            upload_max_retries=2,
            upload_initial_backoff_seconds=0.01,
            upload_max_backoff_seconds=0.02,
        )
        storage = gd_module.GoogleDriveStorage(settings)

        with pytest.raises(StorageError, match="Network error communicating"):
            list(storage.download("file-id"))

    def test_unrelated_attribute_error_not_translated(self, monkeypatch):
        """A non-cleanup AttributeError should NOT be translated — it's a bug."""
        unrelated_err = AttributeError(UNRELATED_MSG)
        request = _ScriptedRequest([unrelated_err] * 10)

        monkeypatch.setattr(gd_module, "build", lambda *a, **k: _FakeService(request))
        monkeypatch.setattr(gd_module, "MediaIoBaseDownload", _FakeDownload)
        settings = Settings(
            google_drive_refresh_token="x",
            google_drive_client_id="x",
            google_drive_client_secret="x",
            upload_max_retries=2,
            upload_initial_backoff_seconds=0.01,
            upload_max_backoff_seconds=0.02,
        )
        storage = gd_module.GoogleDriveStorage(settings)

        with pytest.raises(AttributeError):
            list(storage.download("file-id"))


class TestTruncatedResponseIsRetryable:
    """http.client.HTTPException transport failures are retryable.

    IncompleteRead / BadStatusLine are what the stdlib raises when a peer
    resets a connection mid-response (antivirus/proxy SSL inspection or a
    flaky hop). They were previously unclassified - not an OSError, an
    HttpLib2Error, or a ConnectionError - so a truncated drive download
    escaped raw out of download()'s generator, aborting the committed
    StreamingResponse (the thumbnail ECONNRESET). They must be retryable.
    """

    def test_incomplete_read_is_retryable(self):
        exc = http.client.IncompleteRead(b"partial", 100)
        assert _is_retryable_google_error(exc) is True

    def test_bad_status_line_is_retryable(self):
        exc = http.client.BadStatusLine("HTTP/1.0 200 ")
        assert _is_retryable_google_error(exc) is True

    def test_line_too_long_is_retryable(self):
        exc = http.client.LineTooLong("line too long")
        assert _is_retryable_google_error(exc) is True


class TestDownloadRetriesTruncatedResponse:
    def test_download_retries_incomplete_read_then_succeeds(self, monkeypatch):
        """First next_chunk hits an IncompleteRead, retry then succeeds.

        Exactly the "inspect_media_thumbnail, has_thumbnail check passed,
        read begins, connection reset" case a gallery grid of thumbnails
        hits when a middlebox kills one drive connection: download() must
        retry and finish cleanly rather than abort the streaming response.
        """
        truncated = http.client.IncompleteRead(b"partial", 100)
        request = _ScriptedRequest(
            [truncated, (_FakeProgress(10), None), (_FakeProgress(20), True)]
        )

        monkeypatch.setattr(gd_module, "build", lambda *a, **k: _FakeService(request))
        monkeypatch.setattr(gd_module, "MediaIoBaseDownload", _FakeDownload)
        settings = Settings(
            google_drive_refresh_token="x",
            google_drive_client_id="x",
            google_drive_client_secret="x",
            upload_max_retries=2,
            upload_initial_backoff_seconds=0.01,
            upload_max_backoff_seconds=0.02,
        )
        storage = gd_module.GoogleDriveStorage(settings)

        chunks = list(storage.download("file-id"))
        assert len(chunks) >= 1
        # the IncompleteRead was retried, not swallowed silently
        assert request.calls >= 2

    def test_download_exhausted_translates_to_storage_error(self, monkeypatch):
        """After max retries, IncompleteRead surfaces as StorageError.

        This is the critical guarantee: the next raw exception surfaces
        as StorageError, which the streaming generators' `except
        StorageError` cleanly catches - instead of escaping the generator
        after the response is committed (the ECONNRESET the browser and
        Vite proxy see).
        """
        truncated = http.client.IncompleteRead(b"partial", 100)
        request = _ScriptedRequest([truncated] * 10)

        monkeypatch.setattr(gd_module, "build", lambda *a, **k: _FakeService(request))
        monkeypatch.setattr(gd_module, "MediaIoBaseDownload", _FakeDownload)
        settings = Settings(
            google_drive_refresh_token="x",
            google_drive_client_id="x",
            google_drive_client_secret="x",
            upload_max_retries=2,
            upload_initial_backoff_seconds=0.01,
            upload_max_backoff_seconds=0.02,
        )
        storage = gd_module.GoogleDriveStorage(settings)

        with pytest.raises(StorageError, match="Network error communicating"):
            list(storage.download("file-id"))

    def test_bad_status_line_translates_to_storage_error(self, monkeypatch):
        truncated = http.client.BadStatusLine("HTTP/1.0 200 ")
        request = _ScriptedRequest([truncated] * 10)

        monkeypatch.setattr(gd_module, "build", lambda *a, **k: _FakeService(request))
        monkeypatch.setattr(gd_module, "MediaIoBaseDownload", _FakeDownload)
        settings = Settings(
            google_drive_refresh_token="x",
            google_drive_client_id="x",
            google_drive_client_secret="x",
            upload_max_retries=1,
            upload_initial_backoff_seconds=0.01,
            upload_max_backoff_seconds=0.02,
        )
        storage = gd_module.GoogleDriveStorage(settings)

        with pytest.raises(StorageError, match="Network error communicating"):
            list(storage.download("file-id"))


class TestConcurrentDownloadsWithTruncatedResponses:
    def test_simultaneous_downloads_all_finish_cleanly(self, monkeypatch):
        """The exact gallery-grid scenario: several thumbnail downloads run
        at once and each hits an IncompleteRead on its first chunk. Every
        one must finish cleanly (retry then succeed). If any leaked a raw
        http.client exception, ThreadPoolExecutor.map would re-raise it
        into this test and fail it - which is what the browser saw as
        ECONNRESET before the fix."""
        request_slot = []
        request_lock = threading.Lock()

        def _build(*args, **kwargs):
            with request_lock:
                request = request_slot.pop()
            return _FakeService(request)

        monkeypatch.setattr(gd_module, "build", _build)
        monkeypatch.setattr(gd_module, "MediaIoBaseDownload", _FakeDownload)
        settings = Settings(
            google_drive_refresh_token="x",
            google_drive_client_id="x",
            google_drive_client_secret="x",
            upload_max_retries=2,
            upload_initial_backoff_seconds=0.01,
            upload_max_backoff_seconds=0.02,
        )

        for _ in range(8):
            request_slot.append(
                _ScriptedRequest(
                    [
                        http.client.IncompleteRead(b"partial", 100),
                        (_FakeProgress(10), None),
                        (_FakeProgress(20), True),
                    ]
                )
            )

        def _download_once():
            # Each worker builds its own storage client - mirroring how
            # every thumbnail request opens its own isolated Drive client.
            storage = gd_module.GoogleDriveStorage(settings)
            return b"".join(storage.download("file-id"))

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: _download_once(), range(8)))

        assert len(results) == 8
        assert all(len(r) >= 1 for r in results)


class _FakeProgress:
    def __init__(self, resumable_progress):
        self.resumable_progress = resumable_progress
