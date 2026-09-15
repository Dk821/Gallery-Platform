"""
Tests for the resumable-upload hardening work: idempotency (Section 4),
disk protection (Section 5), concurrency (Section 3), progress (Section
8), timeout handling (Section 10), and orphan reconciliation (Section 9).

Drive-level chunking/resume itself (Section 2) is exercised directly
against GoogleDriveStorage in test_drive_resumable_upload.py using a fake
googleapiclient-shaped request object, since FakeStorageService
deliberately doesn't reimplement Drive's resumable protocol.
"""

import datetime
import io

import pytest

from app.models.upload_session import UploadSession
from app.services.disk_service import DiskReservationTracker, InsufficientDiskSpaceError, get_disk_tracker
from app.services.orphan_reconciliation import reconcile_orphans
from app.services.upload_concurrency import UploadConcurrencyLimiter
from tests.conftest import login_as_admin

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0123456789" * 50  # valid JPEG signature, fake body


# ---------------------------------------------------------------------------
# Idempotency (Section 4)
# ---------------------------------------------------------------------------


def test_retry_with_same_upload_id_after_success_returns_same_media_no_duplicate(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    login_as_admin(client, seeded_admin)
    upload_id = "retry-after-success-upload-id"

    first = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": upload_id},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert first.status_code == 200
    media_id = first.json()["data"]["id"]

    # Simulate the browser never seeing the first response and retrying
    # with the exact same upload_id.
    second = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": upload_id},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert second.status_code == 200
    assert second.json()["data"]["id"] == media_id

    # Only ONE Drive file and one Media row exist, not two.
    assert len(fake_storage.files) == 1


def test_duplicate_upload_id_while_in_progress_is_rejected(
    client, seeded_admin, seeded_album_for_client, db_session
):
    login_as_admin(client, seeded_admin)
    session = UploadSession(
        upload_id="in-flight-upload-id",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="a.jpg",
        total_bytes=1000,
        bytes_uploaded=100,
        status="uploading",
    )
    db_session.add(session)
    db_session.commit()

    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": "in-flight-upload-id"},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "UPLOAD_ALREADY_IN_PROGRESS"


def test_retry_after_failed_attempt_is_allowed_and_succeeds(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    login_as_admin(client, seeded_admin)
    upload_id = "retry-after-failure-upload-id"
    fake_storage.fail_next_upload = True

    failed = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": upload_id},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert failed.status_code == 502

    retried = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": upload_id},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert retried.status_code == 200
    assert len(fake_storage.files) == 1


def test_two_simultaneous_identical_requests_only_one_wins(
    client, seeded_admin, seeded_album_for_client, db_session
):
    # Simulates the race directly: two requests both trying to create the
    # very first UploadSession row for the same (admin_id, upload_id).
    # The DB's unique constraint means only one insert can succeed.
    login_as_admin(client, seeded_admin)
    from app.services.media_service import _reserve_upload_session
    from app.schemas.errors import ApiError

    session, existing = _reserve_upload_session(
        db_session, seeded_admin.id, "race-upload-id", seeded_album_for_client, "a.jpg", 100
    )
    assert existing is None
    assert session.status == "uploading"

    with pytest.raises(ApiError) as exc_info:
        _reserve_upload_session(
            db_session, seeded_admin.id, "race-upload-id", seeded_album_for_client, "a.jpg", 100
        )
    assert exc_info.value.status_code == 409


def test_upload_id_is_not_reused_across_different_filenames_as_a_key(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    # The idempotency key is upload_id, not filename - two different
    # logical uploads must never collide just because a filename repeats.
    login_as_admin(client, seeded_admin)
    for upload_id in ("upload-a", "upload-b"):
        resp = client.post(
            "/api/admin/media/upload",
            data={"album_id": str(seeded_album_for_client.id), "upload_id": upload_id},
            files={"file": ("same_name.jpg", JPEG_BYTES, "image/jpeg")},
        )
        assert resp.status_code == 200
    assert len(fake_storage.files) == 2


def test_missing_upload_id_still_works_backward_compatibly(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 200


def test_upload_id_over_max_length_is_rejected_cleanly(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    # Regression test: a client that mints upload_id by embedding the raw
    # filename (e.g. `${file.name}-${file.size}-${timestamp}-${random}`)
    # can easily produce something longer than the upload_id column
    # (VARCHAR(100)) once the filename itself is long - a real, long movie
    # title once triggered a raw 500 DataError all the way from MySQL
    # instead of ever reaching input validation. This must be a clean 400.
    login_as_admin(client, seeded_admin)
    too_long_upload_id = "x" * 101
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": too_long_upload_id},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_UPLOAD_ID"


def test_upload_id_at_exactly_max_length_is_accepted(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    login_as_admin(client, seeded_admin)
    exactly_100 = "y" * 100
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": exactly_100},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 200


def test_empty_upload_id_string_falls_back_to_generated_id(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    # An empty string is falsy in Python, so `upload_id or uuid4()` in the
    # route (same fallback used for an omitted field) replaces it with a
    # fresh generated id before it ever reaches validation - this is
    # existing, intentional behavior, not a gap: an empty string and an
    # omitted field end up equivalent.
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": ""},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Progress (Section 8)
# ---------------------------------------------------------------------------


def test_upload_status_endpoint_reports_completion(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    login_as_admin(client, seeded_admin)
    upload_id = "progress-check-upload-id"
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": upload_id},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 200

    status_resp = client.get(f"/api/admin/media/upload-status/{upload_id}")
    assert status_resp.status_code == 200
    data = status_resp.json()["data"]
    assert data["status"] == "completed"
    assert data["percentage"] == 100
    assert data["bytes_uploaded"] == data["total_bytes"]
    assert data["media_id"] is not None
    # Never expose internal storage references.
    assert "google_drive_file_id" not in data
    assert "drive_file_id" not in data


def test_upload_status_never_reports_100_percent_before_completion(db_session, seeded_admin, seeded_album_for_client):
    session = UploadSession(
        upload_id="partial-upload-id",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="a.jpg",
        total_bytes=1000,
        bytes_uploaded=1000,  # fully received bytes, but not yet finalized
        status="uploading",
    )
    db_session.add(session)
    db_session.commit()

    from app.api.presenters import upload_session_to_response

    response = upload_session_to_response(session)
    assert response.percentage < 100
    assert response.status == "uploading"


def test_upload_status_for_unknown_id_is_404(client, seeded_admin):
    login_as_admin(client, seeded_admin)
    resp = client.get("/api/admin/media/upload-status/does-not-exist")
    assert resp.status_code == 404


def test_upload_sessions_endpoint_restores_recent_uploads_for_refresh(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    # Refresh-recovery: the Uploads page rebuilds its in-memory list from
    # this endpoint after a page reload. The server persists every session,
    # so the endpoint must return them (newest first) with enough context to
    # render the row - filename plus owning album/client label.
    login_as_admin(client, seeded_admin)
    for upload_id, filename in (("recent-a", "a.jpg"), ("recent-b", "b.jpg")):
        resp = client.post(
            "/api/admin/media/upload",
            data={"album_id": str(seeded_album_for_client.id), "upload_id": upload_id},
            files={"file": (filename, JPEG_BYTES, "image/jpeg")},
        )
        assert resp.status_code == 200

    resp = client.get("/api/admin/media/upload-sessions")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 2
    assert {item["filename"] for item in data} == {"a.jpg", "b.jpg"}
    assert {item["status"] for item in data} == {"completed"}
    assert all(item["album_name"] and item["client_name"] for item in data)
    # Never expose internal storage references.
    assert all("drive_file_id" not in item for item in data)
    assert all("google_drive_file_id" not in item for item in data)


def test_upload_sessions_endpoint_is_scoped_to_the_admin(client, seeded_admin, db_session, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    session = UploadSession(
        upload_id="other-admins-upload",
        admin_id=999999,  # belongs to nobody we can log in as
        album_id=seeded_album_for_client.id,
        filename="secret.jpg",
        total_bytes=10,
        bytes_uploaded=0,
        status="uploading",
    )
    db_session.add(session)
    db_session.commit()

    resp = client.get("/api/admin/media/upload-sessions")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data == []  # never leak another admin's sessions


def test_stale_uploading_session_is_flipped_to_failed_on_status_poll(
    client, seeded_admin, db_session, seeded_album_for_client
):
    # A server restart/crash leaves sessions stuck in "uploading" forever
    # with no thread behind them. Without the staleness sweep the frontend
    # would poll upload-status on them ~every second, forever (each poll a
    # pair of DB SELECTs). The status endpoint must flip them to "failed"
    # so the poll loop terminates.
    login_as_admin(client, seeded_admin)
    session = UploadSession(
        upload_id="stale-upload-id",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="stale.jpg",
        total_bytes=1000,
        bytes_uploaded=100,
        status="uploading",
    )
    session.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
    session.updated_at = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
    db_session.add(session)
    db_session.commit()

    resp = client.get("/api/admin/media/upload-status/stale-upload-id")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "failed"
    assert data["error_code"] == "UPLOAD_STALE"

    # And the console shows it as failed too, so a page refresh won't
    # restore it as in-flight and start polling again.
    resp2 = client.get("/api/admin/media/upload-sessions")
    assert resp2.status_code == 200
    shown = {item["upload_id"]: item["status"] for item in resp2.json()["data"]}
    assert shown["stale-upload-id"] == "failed"


def test_recent_in_progress_upload_is_never_marked_stale(
    client, seeded_admin, db_session, seeded_album_for_client
):
    # The staleness sweep keys off updated_at: a genuinely active upload
    # keeps writing progress, so its row stays fresh and must never be
    # mis-failed - even if its created_at is old.
    login_as_admin(client, seeded_admin)
    session = UploadSession(
        upload_id="active-upload-id",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="active.jpg",
        total_bytes=1000,
        bytes_uploaded=500,
        status="uploading",
    )
    session.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
    session.updated_at = datetime.datetime.utcnow()  # touched a moment ago
    db_session.add(session)
    db_session.commit()

    resp = client.get("/api/admin/media/upload-status/active-upload-id")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "uploading"


# ---------------------------------------------------------------------------
# Disk protection (Section 5)
# ---------------------------------------------------------------------------


def test_insufficient_disk_space_rejects_upload_with_structured_error(
    client, seeded_admin, seeded_album_for_client, monkeypatch
):
    login_as_admin(client, seeded_admin)

    def _tiny_free_space(self, key, size_bytes, *, min_free_bytes, path="/"):
        raise InsufficientDiskSpaceError(size_bytes, 0)

    monkeypatch.setattr(DiskReservationTracker, "try_reserve", _tiny_free_space)

    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": "no-space-upload-id"},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 507
    assert resp.json()["error"]["code"] == "INSUFFICIENT_DISK_SPACE"


def test_disk_reservation_accounts_for_concurrent_reservations_not_just_itself():
    tracker = DiskReservationTracker()
    gb = 1024**3

    # 30 GB free (simulated via a huge min_free_bytes budget trick is
    # awkward, so instead we directly exercise the accounting logic with
    # a monkeypatched free-space figure).
    import shutil

    class _FakeUsage:
        free = 30 * gb

    orig = shutil.disk_usage
    shutil.disk_usage = lambda path: _FakeUsage()
    try:
        tracker.try_reserve("upload-a", 10 * gb, min_free_bytes=0)
        tracker.try_reserve("upload-b", 10 * gb, min_free_bytes=0)
        # A third 10 GB upload would blow the 30 GB budget once A and B's
        # reservations are both accounted for (20 GB already reserved).
        with pytest.raises(InsufficientDiskSpaceError):
            tracker.try_reserve("upload-c", 10 * gb + 1, min_free_bytes=0)
        # Exactly the remaining headroom still fits.
        tracker.try_reserve("upload-c", 10 * gb, min_free_bytes=0)
    finally:
        shutil.disk_usage = orig


def test_disk_reservation_is_released_after_success_and_failure(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    login_as_admin(client, seeded_admin)
    tracker = get_disk_tracker()

    client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": "release-on-success"},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert tracker.total_reserved() == 0

    fake_storage.fail_next_upload = True
    client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": "release-on-failure"},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert tracker.total_reserved() == 0


# ---------------------------------------------------------------------------
# Concurrency (Section 3)
# ---------------------------------------------------------------------------


def test_concurrency_limiter_never_exceeds_configured_maximum():
    import threading
    import time

    limiter = UploadConcurrencyLimiter(max_concurrent=3)
    max_seen = {"value": 0}
    lock = threading.Lock()

    def _worker():
        with limiter.slot():
            with lock:
                max_seen["value"] = max(max_seen["value"], limiter.active_count)
            time.sleep(0.05)

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert max_seen["value"] <= 3
    assert limiter.active_count == 0  # every slot released


def test_concurrency_limiter_releases_slot_on_exception():
    limiter = UploadConcurrencyLimiter(max_concurrent=1)

    with pytest.raises(ValueError):
        with limiter.slot():
            raise ValueError("simulated failure mid-upload")

    assert limiter.active_count == 0
    # Slot must be immediately reusable - if it leaked, this would block
    # forever (bounded semaphore would raise instead, since acquire() has
    # no waiter here to hang).
    with limiter.slot():
        assert limiter.active_count == 1
    assert limiter.active_count == 0


def test_concurrency_limiter_slot_timeout_raises_and_releases_nothing():
    import threading
    import time

    from app.services.upload_concurrency import UploadQueueTimeoutError

    limiter = UploadConcurrencyLimiter(max_concurrent=1)

    def _hold_slot():
        with limiter.slot():
            time.sleep(0.3)

    holder = threading.Thread(target=_hold_slot)
    holder.start()
    time.sleep(0.05)  # let the holder actually acquire first

    with pytest.raises(UploadQueueTimeoutError):
        with limiter.slot(timeout=0.05):
            pytest.fail("should never enter the block - slot was held")

    holder.join(timeout=5)
    assert limiter.active_count == 0  # holder released cleanly on its own


def test_concurrency_limiter_slot_succeeds_once_freed_within_timeout():
    import threading
    import time

    limiter = UploadConcurrencyLimiter(max_concurrent=1)

    def _hold_briefly():
        with limiter.slot():
            time.sleep(0.1)

    holder = threading.Thread(target=_hold_briefly)
    holder.start()
    time.sleep(0.02)

    # Waits up to 2s - the holder releases after ~0.1s, well within that.
    with limiter.slot(timeout=2.0):
        assert limiter.active_count == 1

    holder.join(timeout=5)


def test_upload_returns_503_when_processing_pipeline_is_saturated(
    client, seeded_admin, seeded_album_for_client, monkeypatch
):
    # Simulates the whole server being at its configured concurrent-upload
    # ceiling: forces the outer limiter's max_concurrent down to 1 and
    # the queue-wait down to something fast, then holds the one slot open
    # from another thread so a real upload request has nowhere to go.
    import threading
    import time

    from app.config.settings import get_settings
    from app.services.upload_concurrency import get_upload_limiter

    settings = get_settings()
    monkeypatch.setattr(settings, "upload_max_concurrent_requests", 1)
    monkeypatch.setattr(settings, "upload_queue_wait_seconds", 0.2)
    get_upload_limiter.cache_clear()

    limiter = get_upload_limiter(1)
    release_event = threading.Event()

    def _hold_the_only_slot():
        with limiter.slot():
            release_event.wait(timeout=5)

    holder = threading.Thread(target=_hold_the_only_slot)
    holder.start()
    time.sleep(0.05)  # ensure the holder has acquired before we try

    try:
        login_as_admin(client, seeded_admin)
        resp = client.post(
            "/api/admin/media/upload",
            data={"album_id": str(seeded_album_for_client.id)},
            files={"file": ("photo1.jpg", _real_jpeg_bytes_local(), "image/jpeg")},
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "SERVER_BUSY"
    finally:
        release_event.set()
        holder.join(timeout=5)
        get_upload_limiter.cache_clear()


def _real_jpeg_bytes_local() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (200, 150), color=(10, 200, 90))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Timeout handling (Section 10)
# ---------------------------------------------------------------------------


def test_upload_timeout_returns_504_and_marks_session_failed(
    client, seeded_admin, seeded_album_for_client, fake_storage, db_session
):
    login_as_admin(client, seeded_admin)
    fake_storage.fail_next_upload_timeout = True

    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": "timeout-upload-id"},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "UPLOAD_TIMEOUT"

    session = (
        db_session.query(UploadSession)
        .filter_by(admin_id=seeded_admin.id, upload_id="timeout-upload-id")
        .first()
    )
    assert session.status == "failed"
    assert session.error_code == "UPLOAD_TIMEOUT"


def test_upload_retryable_after_timeout(client, seeded_admin, seeded_album_for_client, fake_storage):
    login_as_admin(client, seeded_admin)
    fake_storage.fail_next_upload_timeout = True
    client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": "timeout-then-retry"},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )

    retried = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": "timeout-then-retry"},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert retried.status_code == 200


# ---------------------------------------------------------------------------
# Orphan reconciliation (Section 9)
# ---------------------------------------------------------------------------


def test_orphan_candidate_detected_after_grace_period_but_not_before(
    db_session, seeded_admin, seeded_album_for_client, fake_storage
):
    import datetime

    old_session = UploadSession(
        upload_id="orphan-old",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="a.jpg",
        total_bytes=100,
        bytes_uploaded=100,
        status="uploading",  # never reached "completed" - process died
        drive_file_id="file-orphan-old",
    )
    old_session.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=72)
    fresh_session = UploadSession(
        upload_id="orphan-fresh",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="b.jpg",
        total_bytes=100,
        bytes_uploaded=100,
        status="uploading",
        drive_file_id="file-orphan-fresh",
    )
    fresh_session.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    db_session.add_all([old_session, fresh_session])
    db_session.commit()

    result = reconcile_orphans(db_session, fake_storage, grace_period_hours=48, dry_run=True)

    assert "file-orphan-old" in result["confirmed"]
    assert "file-orphan-fresh" not in result["confirmed"]
    # dry_run=True must never delete anything.
    assert result["deleted"] == []


def test_orphan_with_completed_media_is_never_flagged(
    db_session, seeded_admin, seeded_album_for_client, seeded_client, fake_storage
):
    import datetime

    from app.models.media import Media

    media = Media(
        client_id=seeded_client.id,
        album_id=seeded_album_for_client.id,
        file_uuid="uuid-1",
        file_name="a.jpg",
        file_type="photo",
        mime_type="image/jpeg",
        file_size=100,
        google_drive_file_id="file-still-valid",
        status="ready",
    )
    db_session.add(media)
    db_session.commit()

    session = UploadSession(
        upload_id="completed-but-old",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="a.jpg",
        total_bytes=100,
        bytes_uploaded=100,
        status="completed",
        drive_file_id="file-still-valid",
        media_id=media.id,
    )
    session.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=100)
    db_session.add(session)
    db_session.commit()

    result = reconcile_orphans(db_session, fake_storage, grace_period_hours=48, dry_run=True)
    assert "file-still-valid" not in result["confirmed"]


def test_orphan_cleanup_deletes_confirmed_orphans_when_not_dry_run(
    db_session, seeded_admin, seeded_album_for_client, fake_storage
):
    import datetime

    fake_storage.files["file-real-orphan"] = {
        "name": "a.jpg",
        "mime_type": "image/jpeg",
        "parent_folder_id": seeded_album_for_client.drive_folder_id,
        "content": b"data",
        "upload_id": "real-orphan",
    }
    session = UploadSession(
        upload_id="real-orphan",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="a.jpg",
        total_bytes=100,
        bytes_uploaded=100,
        status="uploading",
        drive_file_id="file-real-orphan",
    )
    session.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=72)
    db_session.add(session)
    db_session.commit()

    result = reconcile_orphans(db_session, fake_storage, grace_period_hours=48, dry_run=False)

    assert "file-real-orphan" in result["deleted"]
    assert "file-real-orphan" not in fake_storage.files
    assert session.status == "cancelled"


def test_reconcile_orphans_endpoint_is_dry_run_by_default(
    client, seeded_admin, seeded_album_for_client, fake_storage, db_session
):
    import datetime

    fake_storage.files["file-endpoint-orphan"] = {
        "name": "a.jpg",
        "mime_type": "image/jpeg",
        "parent_folder_id": seeded_album_for_client.drive_folder_id,
        "content": b"data",
        "upload_id": "endpoint-orphan",
    }
    session = UploadSession(
        upload_id="endpoint-orphan",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="a.jpg",
        total_bytes=100,
        bytes_uploaded=100,
        status="uploading",
        drive_file_id="file-endpoint-orphan",
    )
    session.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=72)
    db_session.add(session)
    db_session.commit()

    login_as_admin(client, seeded_admin)
    resp = client.post("/api/admin/media/reconcile-orphans")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["dry_run"] is True
    assert "file-endpoint-orphan" in data["confirmed"]
    assert "file-endpoint-orphan" in fake_storage.files  # not deleted


# ---------------------------------------------------------------------------
# Security: internal identifiers never leak (extends existing coverage)
# ---------------------------------------------------------------------------


def test_upload_response_never_exposes_upload_session_internals(
    client, seeded_admin, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id), "upload_id": "no-leak-upload-id"},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    body = resp.json()["data"]
    serialized = str(body)
    assert "drive_file_id" not in serialized
    assert "google_drive_file_id" not in serialized
    assert "thumbnail_drive_file_id" not in serialized
