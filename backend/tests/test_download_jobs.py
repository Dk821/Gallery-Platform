import datetime
import io
import zipfile

from PIL import Image

from tests.conftest import login_as_admin, login_as_client


def _jpeg_bytes(color=(10, 20, 30)):
    img = Image.new("RGB", (100, 80), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _upload(client, album_id, filename, content=None):
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(album_id)},
        files={"file": (filename, content or _jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# Client: whole-album ZIP
# ---------------------------------------------------------------------------


def test_client_download_all_creates_correct_zip(client, seeded_admin, seeded_client, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    _upload(client, seeded_album_for_client.id, "b.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    create_resp = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={})
    assert create_resp.status_code == 200
    job = create_resp.json()["data"]
    # The creation response is serialized before its background task updates
    # the row, so fetch the job again to observe the final state.
    job = client.get(f"/api/client/download-jobs/{job['id']}").json()["data"]
    assert job["status"] == "completed"
    assert job["total_files"] == 2
    assert job["completed_files"] == 2

    file_resp = client.get(f"/api/client/download-jobs/{job['id']}/file")
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(file_resp.content)) as zf:
        names = set(zf.namelist())
        assert names == {"a.jpg", "b.jpg"}
        assert zf.testzip() is None  # verifies every entry's CRC - a real, uncorrupted zip


def test_client_download_selected_only_includes_selected(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    m1 = _upload(client, seeded_album_for_client.id, "keep.jpg")
    _upload(client, seeded_album_for_client.id, "skip.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    create_resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/download-jobs",
        json={"media_ids": [m1["id"]]},
    )
    job = create_resp.json()["data"]
    assert job["total_files"] == 1

    file_resp = client.get(f"/api/client/download-jobs/{job['id']}/file")
    with zipfile.ZipFile(io.BytesIO(file_resp.content)) as zf:
        assert zf.namelist() == ["keep.jpg"]


def test_zip_deduplicates_identical_filenames(client, seeded_admin, seeded_client, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "IMG_0001.jpg", _jpeg_bytes((1, 1, 1)))
    _upload(client, seeded_album_for_client.id, "IMG_0001.jpg", _jpeg_bytes((2, 2, 2)))
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    create_resp = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={})
    job = create_resp.json()["data"]

    file_resp = client.get(f"/api/client/download-jobs/{job['id']}/file")
    with zipfile.ZipFile(io.BytesIO(file_resp.content)) as zf:
        names = zf.namelist()
        assert len(names) == 2
        assert "IMG_0001.jpg" in names
        assert any(n != "IMG_0001.jpg" for n in names)  # the duplicate got a distinct name


def test_no_unauthorized_media_included_wrong_album_ids_are_dropped(
    client, seeded_admin, seeded_client, seeded_album_for_client, seeded_second_album_for_client
):
    login_as_admin(client, seeded_admin)
    in_album = _upload(client, seeded_album_for_client.id, "in_album.jpg")
    other_album_item = _upload(client, seeded_second_album_for_client.id, "other_album.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    # Ask for an id that belongs to a DIFFERENT album than the one the job
    # is scoped to - it must be silently dropped, not included.
    create_resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/download-jobs",
        json={"media_ids": [in_album["id"], other_album_item["id"]]},
    )
    job = create_resp.json()["data"]
    assert job["total_files"] == 1

    file_resp = client.get(f"/api/client/download-jobs/{job['id']}/file")
    with zipfile.ZipFile(io.BytesIO(file_resp.content)) as zf:
        assert zf.namelist() == ["in_album.jpg"]


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_client_cannot_create_job_for_another_clients_album(
    client, seeded_client_b, seeded_album_for_client
):
    login_as_client(client, seeded_client_b.client_uuid, "client-pass-2")
    resp = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={})
    assert resp.status_code == 403


def test_client_cannot_view_another_clients_download_job(
    client, seeded_admin, seeded_client, seeded_client_b, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    job = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={}).json()["data"]
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client_b.client_uuid, "client-pass-2")
    resp = client.get(f"/api/client/download-jobs/{job['id']}")
    assert resp.status_code == 403

    file_resp = client.get(f"/api/client/download-jobs/{job['id']}/file")
    assert file_resp.status_code == 403


def test_unauthenticated_cannot_create_job(client, seeded_album_for_client):
    resp = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={})
    assert resp.status_code == 401


def test_download_job_response_never_exposes_drive_ids_or_zip_path(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={})
    assert "google_drive_file_id" not in resp.text
    assert "thumbnail_reference" not in resp.text
    assert "zip_path" not in resp.text


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def test_client_cannot_download_expired_album(
    client, seeded_admin, seeded_client, seeded_album_for_client, db_session
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    client.post("/api/auth/logout")

    seeded_album_for_client.expires_at = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    db_session.commit()

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ALBUM_EXPIRED"


def test_admin_can_still_zip_expired_album(client, seeded_admin, seeded_album_for_client, db_session):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")

    seeded_album_for_client.expires_at = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    db_session.commit()

    resp = client.post(f"/api/admin/albums/{seeded_album_for_client.id}/download-jobs", json={})
    assert resp.status_code == 200
    job = resp.json()["data"]
    status = client.get(f"/api/admin/download-jobs/{job['id']}").json()["data"]
    assert status["status"] == "completed"


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_storage_failure_marks_job_failed_and_removes_partial_zip(
    client, seeded_admin, seeded_client, seeded_album_for_client, fake_storage, monkeypatch
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    _upload(client, seeded_album_for_client.id, "b.jpg")
    client.post("/api/auth/logout")

    from app.services.storage_service import StorageError

    call_count = {"n": 0}
    real_download = fake_storage.download

    def flaky_download(file_id):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise StorageError("simulated failure on second file")
        return real_download(file_id)

    monkeypatch.setattr(fake_storage, "download", flaky_download)

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={})
    job = resp.json()["data"]
    job = client.get(f"/api/client/download-jobs/{job['id']}").json()["data"]
    assert job["status"] == "failed"
    assert job["error_message"]

    file_resp = client.get(f"/api/client/download-jobs/{job['id']}/file")
    assert file_resp.status_code == 422
    assert file_resp.json()["error"]["code"] == "DOWNLOAD_FAILED"


def test_empty_selection_rejected(client, seeded_admin, seeded_client, seeded_album_for_client):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={"media_ids": [999999]}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "DOWNLOAD_JOB_EMPTY"


def test_job_for_nonexistent_album_403s_for_client(client, seeded_client):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post("/api/client/albums/999999/download-jobs", json={})
    assert resp.status_code == 403  # ownership check fails before "not found" would ever be considered


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_cleanup_removes_expired_completed_jobs(
    client, seeded_admin, seeded_client, seeded_album_for_client, db_session
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    job = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={}).json()["data"]

    from app.models.download_job import DownloadJob
    from app.services.download_job_service import cleanup_expired_download_jobs

    db_job = db_session.query(DownloadJob).filter(DownloadJob.id == job["id"]).first()
    assert db_job.status == "completed"
    assert db_job.zip_path is not None
    import os

    zip_path = db_job.zip_path
    assert os.path.exists(zip_path)

    # Force it into the past so cleanup picks it up.
    db_job.expires_at = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    db_session.commit()

    cleaned = cleanup_expired_download_jobs(db_session)
    assert cleaned == 1

    db_session.refresh(db_job)
    assert db_job.status == "expired"
    assert db_job.zip_path is None
    assert not os.path.exists(zip_path)


def test_cleanup_ignores_jobs_not_yet_expired(client, seeded_admin, seeded_client, seeded_album_for_client, db_session):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    job = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={}).json()["data"]

    from app.services.download_job_service import cleanup_expired_download_jobs

    cleaned = cleanup_expired_download_jobs(db_session)
    assert cleaned == 0  # freshly completed job, expires_at is far in the future

    status_resp = client.get(f"/api/client/download-jobs/{job['id']}")
    assert status_resp.json()["data"]["status"] == "completed"


# ---------------------------------------------------------------------------
# get_ready_zip_path_or_error - unit-level checks for states TestClient's
# synchronous background-task execution can't otherwise reach via HTTP
# ---------------------------------------------------------------------------


def test_get_ready_zip_path_raises_not_ready_for_in_progress_job():
    from app.models.download_job import DownloadJob
    from app.schemas.errors import ApiError
    from app.services.download_job_service import get_ready_zip_path_or_error

    for status in ("queued", "preparing", "processing"):
        job = DownloadJob(
            client_id=1, album_id=1, status=status, requested_by_type="client", requested_by_id=1
        )
        try:
            get_ready_zip_path_or_error(job)
            assert False, f"expected ApiError for status={status}"
        except ApiError as exc:
            assert exc.detail["code"] == "DOWNLOAD_NOT_READY"


def test_get_ready_zip_path_raises_expired_for_expired_status():
    from app.models.download_job import DownloadJob
    from app.schemas.errors import ApiError
    from app.services.download_job_service import get_ready_zip_path_or_error

    job = DownloadJob(
        client_id=1, album_id=1, status="expired", requested_by_type="client", requested_by_id=1
    )
    try:
        get_ready_zip_path_or_error(job)
        assert False, "expected ApiError"
    except ApiError as exc:
        assert exc.detail["code"] == "DOWNLOAD_EXPIRED"


# ---------------------------------------------------------------------------
# Admin bulk ZIP
# ---------------------------------------------------------------------------


def test_admin_can_create_bulk_zip_for_selected_media(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    m1 = _upload(client, seeded_album_for_client.id, "a.jpg")
    _upload(client, seeded_album_for_client.id, "b.jpg")

    resp = client.post(
        f"/api/admin/albums/{seeded_album_for_client.id}/download-jobs",
        json={"media_ids": [m1["id"]]},
    )
    assert resp.status_code == 200
    job = resp.json()["data"]
    assert job["total_files"] == 1
    status = client.get(f"/api/admin/download-jobs/{job['id']}").json()["data"]
    assert status["status"] == "completed"


def test_admin_download_job_requires_admin_auth(client, seeded_album_for_client):
    resp = client.post(f"/api/admin/albums/{seeded_album_for_client.id}/download-jobs", json={})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Client download password (per-client, set by admin)
# ---------------------------------------------------------------------------


def _set_download_password(client, client_id, password):
    """Helper: set/change a client's download password via the admin route."""
    resp = client.post(
        f"/api/admin/clients/{client_id}/change-download-password",
        json={"password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_has_password_flag_false_without_download_password(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    job = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={}).json()["data"]
    assert job["has_password"] is False

    # Without a password needed, the ZIP downloads directly.
    file_resp = client.get(f"/api/client/download-jobs/{job['id']}/file")
    assert file_resp.status_code == 200


def test_client_download_blocks_without_password_when_set(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    _set_download_password(client, seeded_client.id, "srt4")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    job = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={}).json()["data"]
    assert job["has_password"] is True

    # No password supplied -> blocked.
    file_resp = client.get(f"/api/client/download-jobs/{job['id']}/file")
    assert file_resp.status_code == 403
    assert file_resp.json()["error"]["code"] == "DOWNLOAD_PASSWORD_REQUIRED"

    # A query-string password is deliberately ignored. Verification is stored
    # against the server-side session instead, so secrets never enter URLs.
    wrong = client.get(f"/api/client/download-jobs/{job['id']}/file?password=wrong")
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "DOWNLOAD_PASSWORD_REQUIRED"


def test_client_download_with_correct_password_succeeds(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    _set_download_password(client, seeded_client.id, "srt4")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    job = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={}).json()["data"]

    verify = client.post("/api/client/verify-download-password", json={"password": "srt4"})
    assert verify.status_code == 200

    file_resp = client.get(f"/api/client/download-jobs/{job['id']}/file")
    assert file_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(file_resp.content)) as zf:
        assert zf.namelist() == ["a.jpg"]


def test_verify_password_endpoint_accepts_correct_password(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    _set_download_password(client, seeded_client.id, "srt4")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    job = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={}).json()["data"]

    ok = client.post(f"/api/client/download-jobs/{job['id']}/verify-password", json={"password": "srt4"})
    assert ok.status_code == 200
    assert ok.json()["data"]["verified"] is True

    bad = client.post(f"/api/client/download-jobs/{job['id']}/verify-password", json={"password": "nope"})
    assert bad.status_code == 403
    assert bad.json()["error"]["code"] == "INVALID_DOWNLOAD_PASSWORD"


def test_clear_download_password_removes_requirement(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    _set_download_password(client, seeded_client.id, "srt4")

    # Clearing (empty/null password) removes the requirement.
    resp = client.post(
        f"/api/admin/clients/{seeded_client.id}/change-download-password", json={"password": None}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["has_download_password"] is False
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    job = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={}).json()["data"]
    assert job["has_password"] is False


def test_login_password_and_download_password_are_distinct(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    # The seeded client already has an album; set a download password.
    _upload(client, seeded_album_for_client.id, "a.jpg")
    _set_download_password(client, seeded_client.id, "4567")
    client.post("/api/auth/logout")

    # Login uses the login password.
    login = client.post(
        "/api/auth/client/login",
        json={"gallery_id": seeded_client.client_uuid, "password": "client-pass-1"},
    )
    assert login.status_code == 200

    # Download requires the separate download password, not the login one.
    job = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={}
    ).json()["data"]
    assert job["has_password"] is True

    with_login_pw = client.post("/api/client/verify-download-password", json={"password": "client-pass-1"})
    assert with_login_pw.status_code == 403

    with_dl_pw = client.post("/api/client/verify-download-password", json={"password": "4567"})
    assert with_dl_pw.status_code == 200


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancel_before_processing_leaves_job_cancelled_and_produces_no_zip(
    client, seeded_admin, seeded_client, seeded_album_for_client, fake_storage, db_session
):
    from app.services.album_service import get_album_for_client_or_403
    from app.services.download_job_service import create_download_job, process_download_job

    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    client.post("/api/auth/logout")

    # Create the job straight through the service layer (no HTTP call, so
    # no BackgroundTasks get scheduled) - this is what lets the test cancel
    # it BEFORE process_download_job ever runs. A job created via the real
    # HTTP endpoint can't be caught in this window: the TestClient's
    # synchronous transport runs the background task to completion before
    # the create request even returns.
    album = get_album_for_client_or_403(db_session, seeded_album_for_client.id, seeded_client.id)
    job = create_download_job(
        db_session, album, None, requested_by_type="client", requested_by_id=seeded_client.id
    )

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    cancel_resp = client.post(f"/api/client/download-jobs/{job.id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["data"]["status"] == "cancelled"

    # Now run the worker - it must notice the job was already cancelled
    # and do nothing, rather than overwriting "cancelled" with real progress.
    process_download_job(job.id, fake_storage)

    status_resp = client.get(f"/api/client/download-jobs/{job.id}")
    assert status_resp.json()["data"]["status"] == "cancelled"

    file_resp = client.get(f"/api/client/download-jobs/{job.id}/file")
    assert file_resp.status_code == 410
    assert file_resp.json()["error"]["code"] == "DOWNLOAD_CANCELLED"


def test_cancel_mid_zip_write_stops_and_cleans_up_partial_file(
    client, seeded_admin, seeded_client, seeded_album_for_client, fake_storage, monkeypatch, db_session
):
    import os

    from app.config.settings import get_settings
    from app.models.download_job import DownloadJob
    from app.services.album_service import get_album_for_client_or_403
    from app.services.download_job_service import (
        cancel_download_job,
        create_download_job,
        process_download_job,
    )

    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    _upload(client, seeded_album_for_client.id, "b.jpg")
    _upload(client, seeded_album_for_client.id, "c.jpg")
    client.post("/api/auth/logout")

    album = get_album_for_client_or_403(db_session, seeded_album_for_client.id, seeded_client.id)
    job = create_download_job(
        db_session, album, None, requested_by_type="client", requested_by_id=seeded_client.id
    )
    job_id = job.id

    # Simulate a cancel request landing after the first file has already
    # been zipped - this exercises the checkpoint inside the ZIP-write
    # loop (post per-entry commit), not the "not started yet" case above.
    real_download = fake_storage.download
    call_count = {"n": 0}

    def download_then_cancel_after_first(file_id):
        call_count["n"] += 1
        if call_count["n"] == 2:
            live_job = db_session.query(DownloadJob).filter(DownloadJob.id == job_id).first()
            cancel_download_job(db_session, live_job)
        return real_download(file_id)

    monkeypatch.setattr(fake_storage, "download", download_then_cancel_after_first)

    # ZIP_TEMP_DIR is a real, on-disk directory shared across the whole
    # test session (unlike the in-memory DB, it isn't reset per test) - so
    # snapshot its contents before running the job and diff afterward,
    # rather than asserting "nothing matching job-{id}" outright. Sqlite
    # autoincrement restarts at 1 for every test's fresh in-memory DB, so
    # an unrelated earlier test's job #1 can easily have left its own
    # (correctly named) job-1-*.zip sitting in this same directory.
    zip_dir = get_settings().zip_temp_dir
    os.makedirs(zip_dir, exist_ok=True)
    before = set(os.listdir(zip_dir))

    process_download_job(job_id, fake_storage)

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    status_resp = client.get(f"/api/client/download-jobs/{job_id}")
    data = status_resp.json()["data"]
    assert data["status"] == "cancelled"
    assert data["completed_files"] < data["total_files"]

    # No NEW leftover file survives on disk for a cancelled job - the
    # partial ZIP this run created (if any) must have been removed.
    after = set(os.listdir(zip_dir))
    assert after - before == set()


def test_cancel_already_completed_job_is_rejected(client, seeded_admin, seeded_client, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    create_resp = client.post(f"/api/client/albums/{seeded_album_for_client.id}/download-jobs", json={})
    job = create_resp.json()["data"]
    job = client.get(f"/api/client/download-jobs/{job['id']}").json()["data"]
    assert job["status"] == "completed"

    cancel_resp = client.post(f"/api/client/download-jobs/{job['id']}/cancel")
    assert cancel_resp.status_code == 400
    assert cancel_resp.json()["error"]["code"] == "DOWNLOAD_JOB_NOT_CANCELLABLE"


def test_client_cannot_cancel_another_clients_download_job(
    client, seeded_admin, seeded_client, seeded_client_b, seeded_album_for_client, db_session
):
    from app.services.album_service import get_album_for_client_or_403
    from app.services.download_job_service import create_download_job

    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    client.post("/api/auth/logout")

    album = get_album_for_client_or_403(db_session, seeded_album_for_client.id, seeded_client.id)
    job = create_download_job(
        db_session, album, None, requested_by_type="client", requested_by_id=seeded_client.id
    )

    login_as_client(client, seeded_client_b.client_uuid, "client-pass-2")
    cancel_resp = client.post(f"/api/client/download-jobs/{job.id}/cancel")
    assert cancel_resp.status_code == 403


def test_admin_can_cancel_a_download_job(client, seeded_admin, seeded_client, seeded_album_for_client, db_session):
    from app.services.album_service import get_album_for_client_or_403
    from app.services.download_job_service import create_download_job

    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")

    album = get_album_for_client_or_403(db_session, seeded_album_for_client.id, seeded_client.id)
    job = create_download_job(
        db_session, album, None, requested_by_type="admin", requested_by_id=seeded_admin.id
    )

    cancel_resp = client.post(f"/api/admin/download-jobs/{job.id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["data"]["status"] == "cancelled"
