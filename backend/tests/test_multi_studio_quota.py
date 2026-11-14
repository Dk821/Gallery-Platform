"""Storage quota: reservation -> commit/release, limits, deletion accounting, reconciliation."""

import os
import tempfile
import threading
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings
from app.database.connection import Base
from app.models.album import Album
from app.models.client import Client
from app.models.media import Media
from app.models.platform_storage import PlatformStorage
from app.models.studio import Studio
from app.models.upload_session import UploadSession
from app.services import quota_service
from app.services.quota_reconciliation import reconcile_quota
from app.services.storage_service import StorageError
from tests.ms_helpers import (
    JPEG, complete_upload, fresh, login, make_admin, make_client_album, make_media, make_studio,
    put_to_storage, start_upload, upload_file,
)

SIZE = len(JPEG)


def _uid():
    return str(uuid.uuid4())


def _platform(db):
    db.expire_all()
    row = db.get(PlatformStorage, 1)
    return (row.used_bytes, row.reserved_bytes) if row else (0, 0)


@pytest.fixture()
def env(db_session, client):
    studio = make_studio(db_session, "Quota Studio", quota=SIZE * 3)
    make_admin(db_session, studio, "q@q.dev")
    c, album = make_client_album(db_session, studio)
    login(client, "q@q.dev")
    return {"studio": studio, "client_row": c, "album": album}


def _usage(db, studio):
    row = fresh(db, Studio, studio.id)
    return row.used_bytes, row.reserved_bytes


# ---- happy path -------------------------------------------------------------------

def test_start_reserves_then_complete_converts_to_used(client, db_session, fake_storage, env):
    uid = _uid()
    started = start_upload(client, env["album"].id, uid, SIZE)
    assert started.status_code == 200, started.text
    assert _usage(db_session, env["studio"]) == (0, SIZE)
    assert _platform(db_session) == (0, SIZE)

    file_id = put_to_storage(fake_storage, env["album"].drive_folder_id, JPEG, uid)
    done = complete_upload(client, uid, file_id, SIZE)
    assert done.status_code == 200, done.text
    assert _usage(db_session, env["studio"]) == (SIZE, 0)
    assert _platform(db_session) == (SIZE, 0)
    media = db_session.query(Media).filter(Media.album_id == env["album"].id).one()
    assert media.studio_id == env["studio"].id and media.file_size == SIZE
    assert media.storage_provider == "google_drive"


def test_usage_endpoint_reflects_reserved_used_and_remaining(client, db_session, env):
    start_upload(client, env["album"].id, _uid(), SIZE)
    usage = client.get("/api/studio/usage").json()["data"]["usage"]
    assert usage == {
        "quota_bytes": SIZE * 3, "used_bytes": 0, "reserved_bytes": SIZE, "remaining_bytes": SIZE * 2,
    }


def test_actual_object_size_is_used_not_the_browser_claim(client, db_session, fake_storage, env):
    uid = _uid()
    start_upload(client, env["album"].id, uid, SIZE)
    bigger = JPEG + b"x" * 100
    fid = put_to_storage(fake_storage, env["album"].drive_folder_id, bigger, uid)
    # Browser lies about the size; the storage-reported size wins.
    done = complete_upload(client, uid, fid, 5)
    assert done.status_code == 200, done.text
    assert _usage(db_session, env["studio"]) == (len(bigger), 0)


def test_object_larger_than_quota_is_rejected_cleaned_up_and_released(client, db_session, fake_storage, env):
    uid = _uid()
    start_upload(client, env["album"].id, uid, SIZE)
    huge = JPEG + b"x" * (SIZE * 3)  # exceeds the whole studio quota
    fid = put_to_storage(fake_storage, env["album"].drive_folder_id, huge, uid)
    done = complete_upload(client, uid, fid, len(huge))
    assert done.status_code >= 400
    assert _usage(db_session, env["studio"]) == (0, 0)
    assert _platform(db_session) == (0, 0)
    assert db_session.query(Media).count() == 0
    assert fid not in fake_storage.files  # orphaned object removed


def test_duplicate_completion_does_not_double_count(client, db_session, fake_storage, env):
    uid = _uid()
    start_upload(client, env["album"].id, uid, SIZE)
    fid = put_to_storage(fake_storage, env["album"].drive_folder_id, JPEG, uid)
    first = complete_upload(client, uid, fid, SIZE)
    second = complete_upload(client, uid, fid, SIZE)
    assert first.status_code == 200
    assert second.status_code in (200, 409), second.text
    assert _usage(db_session, env["studio"]) == (SIZE, 0)
    assert db_session.query(Media).filter(Media.album_id == env["album"].id).count() == 1


# ---- limits -----------------------------------------------------------------------

def test_upload_over_studio_quota_is_rejected_without_leaving_a_reservation(client, db_session, env):
    resp = start_upload(client, env["album"].id, _uid(), SIZE * 3 + 1)
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "STUDIO_QUOTA_EXCEEDED"
    assert _usage(db_session, env["studio"]) == (0, 0)
    assert _platform(db_session) == (0, 0)


def test_quota_counts_reserved_bytes_too(client, db_session, env):
    assert start_upload(client, env["album"].id, _uid(), SIZE * 2).status_code == 200
    assert start_upload(client, env["album"].id, _uid(), SIZE).status_code == 200
    third = start_upload(client, env["album"].id, _uid(), 1)
    assert third.status_code == 413
    assert _usage(db_session, env["studio"]) == (0, SIZE * 3)


def test_upload_over_platform_capacity_is_rejected(client, db_session, env, monkeypatch):
    monkeypatch.setattr(get_settings(), "platform_capacity_bytes", SIZE + 10)
    assert start_upload(client, env["album"].id, _uid(), SIZE).status_code == 200
    resp = start_upload(client, env["album"].id, _uid(), SIZE)
    assert resp.status_code == 507 and resp.json()["error"]["code"] == "PLATFORM_CAPACITY_EXCEEDED"
    # The failed attempt left nothing behind on the studio or platform counters.
    assert _usage(db_session, env["studio"]) == (0, SIZE)
    assert _platform(db_session) == (0, SIZE)


def test_platform_capacity_is_shared_across_studios(client, db_session, env, monkeypatch):
    other = make_studio(db_session, "Other", quota=10 * SIZE)
    monkeypatch.setattr(get_settings(), "platform_capacity_bytes", SIZE * 2)
    assert start_upload(client, env["album"].id, _uid(), SIZE * 2).status_code == 200
    # a different studio's reservation is blocked by the platform total
    s = db_session.query(UploadSession).one()
    with pytest.raises(Exception) as exc:
        extra = UploadSession(upload_id=_uid(), admin_id=s.admin_id, album_id=s.album_id, filename="x", studio_id=other.id)
        db_session.add(extra)
        db_session.commit()
        quota_service.reserve(db_session, extra, other.id, SIZE)
    assert getattr(exc.value, "status_code", None) == 507


def test_zero_or_negative_sizes_are_rejected(client, env):
    for bad in (0, -5):
        assert start_upload(client, env["album"].id, _uid(), bad).status_code in (400, 422)


# ---- failure / release ---------------------------------------------------------------

def test_abandoned_upload_releases_reservation(client, db_session, env):
    uid = _uid()
    start_upload(client, env["album"].id, uid, SIZE)
    assert _usage(db_session, env["studio"]) == (0, SIZE)
    assert client.post(f"/api/admin/media/upload-session/{uid}/abandon").status_code == 200
    assert _usage(db_session, env["studio"]) == (0, 0)
    assert _platform(db_session) == (0, 0)
    # freed capacity can be used again
    assert start_upload(client, env["album"].id, _uid(), SIZE * 3).status_code == 200


def test_completion_with_missing_object_fails_and_releases(client, db_session, fake_storage, env):
    uid = _uid()
    start_upload(client, env["album"].id, uid, SIZE)
    done = complete_upload(client, uid, "does-not-exist", SIZE)
    assert done.status_code >= 400
    assert _usage(db_session, env["studio"]) == (0, 0)
    assert db_session.query(Media).count() == 0


def test_completion_by_another_studio_admin_cannot_use_the_session(client, db_session, fake_storage, env):
    uid = _uid()
    start_upload(client, env["album"].id, uid, SIZE)
    fid = put_to_storage(fake_storage, env["album"].drive_folder_id, JPEG, uid)
    other = make_studio(db_session, "Other")
    make_admin(db_session, other, "o@o.dev")
    client.cookies.clear()
    login(client, "o@o.dev")
    resp = complete_upload(client, uid, fid, SIZE)
    assert resp.status_code in (404, 409)
    assert _usage(db_session, env["studio"]) == (0, SIZE)  # untouched
    assert _usage(db_session, other) == (0, 0)


def test_retrying_a_started_upload_does_not_reserve_twice(client, db_session, env):
    uid = _uid()
    start_upload(client, env["album"].id, uid, SIZE)
    start_upload(client, env["album"].id, uid, SIZE)
    assert _usage(db_session, env["studio"])[1] == SIZE


def test_orphaned_reservations_are_released_on_startup_sweep(db_session, env):
    s = UploadSession(
        upload_id=_uid(), admin_id=1, album_id=env["album"].id, filename="x", studio_id=env["studio"].id, status="uploading"
    )
    from app.models.admin import Admin
    admin = db_session.query(Admin).first()
    s.admin_id = admin.id
    db_session.add(s)
    db_session.commit()
    quota_service.reserve(db_session, s, env["studio"].id, SIZE)
    assert _usage(db_session, env["studio"]) == (0, SIZE)
    s.status = "failed"  # as the startup sweep marks interrupted uploads
    db_session.commit()
    assert quota_service.release_orphaned_reservations(db_session) == 1
    db_session.commit()
    assert _usage(db_session, env["studio"]) == (0, 0)
    assert _platform(db_session) == (0, 0)


# ---- deletion --------------------------------------------------------------------------

def _upload_n(client, db_session, fake_storage, env, n):
    for _ in range(n):
        _, done, _ = upload_file(client, fake_storage, env["album"], _uid())
        assert done.status_code == 200, done.text


def test_successful_media_delete_decreases_usage(client, db_session, fake_storage, env):
    _upload_n(client, db_session, fake_storage, env, 2)
    mid = db_session.query(Media).first().id
    assert client.delete(f"/api/admin/media/{mid}").status_code == 200
    assert _usage(db_session, env["studio"]) == (SIZE, 0)
    assert _platform(db_session) == (SIZE, 0)


def test_failed_storage_delete_does_not_decrease_usage(client, db_session, fake_storage, env, monkeypatch):
    _upload_n(client, db_session, fake_storage, env, 1)
    mid = db_session.query(Media).one().id

    def boom(_file_id):
        raise StorageError("provider unavailable")

    monkeypatch.setattr(fake_storage, "delete", boom)
    resp = client.delete(f"/api/admin/media/{mid}")
    assert resp.status_code >= 400
    assert _usage(db_session, env["studio"]) == (SIZE, 0)
    assert db_session.get(Media, mid) is not None


def test_bulk_delete_decreases_usage(client, db_session, fake_storage, env):
    _upload_n(client, db_session, fake_storage, env, 3)
    ids = [m.id for m in db_session.query(Media).all()]
    resp = client.post("/api/admin/media/bulk-delete", json={"media_ids": ids})
    assert resp.status_code == 200 and len(resp.json()["data"]["deleted"]) == 3
    assert _usage(db_session, env["studio"]) == (0, 0)
    assert _platform(db_session) == (0, 0)


def test_deleting_an_album_frees_its_usage_and_releases_in_flight_reservations(client, db_session, fake_storage, env):
    _upload_n(client, db_session, fake_storage, env, 2)
    start_upload(client, env["album"].id, _uid(), SIZE)  # in flight
    assert _usage(db_session, env["studio"]) == (SIZE * 2, SIZE)
    assert client.delete(f"/api/admin/albums/{env['album'].id}").status_code == 200
    assert _usage(db_session, env["studio"]) == (0, 0)
    assert _platform(db_session) == (0, 0)


def test_deleting_a_client_frees_all_its_usage(client, db_session, fake_storage, env):
    _upload_n(client, db_session, fake_storage, env, 2)
    assert client.delete(f"/api/admin/clients/{env['client_row'].id}").status_code == 200
    assert _usage(db_session, env["studio"]) == (0, 0)


def test_usage_never_goes_negative(db_session):
    studio = make_studio(db_session, used=5)
    quota_service.decrease_used(db_session, studio.id, 50)
    db_session.commit()
    assert _usage(db_session, studio) == (0, 0)


# ---- reconciliation ---------------------------------------------------------------------

def test_reconcile_detects_and_repairs_drift(db_session):
    studio = make_studio(db_session, used=999, reserved=77)
    c, album = make_client_album(db_session, studio)
    make_media(db_session, studio, c, album, size=300)
    make_media(db_session, studio, c, album, size=200)
    report = reconcile_quota(db_session, apply=False)
    assert report["studios_out_of_sync"] == 1
    assert _usage(db_session, studio) == (999, 77)  # dry run changes nothing

    reconcile_quota(db_session, apply=True)
    assert _usage(db_session, studio) == (500, 0)
    again = reconcile_quota(db_session, apply=False)
    assert again["studios_out_of_sync"] == 0 and again["platform"]["in_sync"] is True
    assert _platform(db_session) == (500, 0)


def test_reconcile_is_scoped_to_one_studio(db_session):
    a, b = make_studio(db_session, "A", used=1), make_studio(db_session, "B", used=2)
    reconcile_quota(db_session, apply=True, studio_id=a.id)
    assert _usage(db_session, a) == (0, 0)
    assert _usage(db_session, b) == (2, 0)


# ---- concurrency --------------------------------------------------------------------------

@pytest.fixture()
def file_engine():
    """A real multi-connection database (not the shared in-memory StaticPool connection)."""
    url = os.environ.get("CONCURRENCY_TEST_DATABASE_URL")
    path = None
    if not url:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        url = f"sqlite:///{path}"
    kwargs = {"connect_args": {"timeout": 60, "check_same_thread": False}} if url.startswith("sqlite") else {"pool_size": 20}
    engine = create_engine(url, **kwargs)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
    if path:
        os.unlink(path)


def _seed_concurrency(engine, studio_quota, n):
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as db:
        studio = Studio(name="C", status="active", quota_bytes=studio_quota)
        db.add(studio)
        db.commit()
        from app.models.admin import Admin
        admin = Admin(name="a", email="c@c.dev", password_hash="x", role="studio_admin", studio_id=studio.id, status="active")
        client_row = Client(studio_id=studio.id, client_uuid=_uid(), client_name="c", status="active", drive_folder_id="f")
        db.add_all([admin, client_row])
        db.commit()
        album = Album(studio_id=studio.id, client_id=client_row.id, album_uuid=_uid(), album_name="a", status="active", drive_folder_id="g")
        db.add(album)
        db.commit()
        ids = []
        for i in range(n):
            s = UploadSession(upload_id=_uid(), admin_id=admin.id, album_id=album.id, filename=f"{i}", studio_id=studio.id)
            db.add(s)
            db.commit()
            ids.append(s.id)
        return studio.id, ids


def _race(engine, studio_id, session_ids, nbytes):
    Session = sessionmaker(bind=engine, autoflush=False)
    barrier = threading.Barrier(len(session_ids))
    results = []

    def worker(sid):
        with Session() as db:
            s = db.get(UploadSession, sid)
            barrier.wait()
            try:
                quota_service.reserve(db, s, studio_id, nbytes)
                results.append("ok")
            except Exception as exc:  # ApiError
                results.append(exc.detail["code"] if hasattr(exc, "detail") else type(exc).__name__)

    threads = [threading.Thread(target=worker, args=(sid,)) for sid in session_ids]
    [t.start() for t in threads]
    [t.join(120) for t in threads]
    return results


def test_concurrent_reservations_cannot_oversubscribe_the_studio(file_engine):
    studio_id, ids = _seed_concurrency(file_engine, studio_quota=1000, n=12)
    results = _race(file_engine, studio_id, ids, 300)
    assert results.count("ok") == 3  # 3 * 300 <= 1000 < 4 * 300
    assert all(r in ("ok", "STUDIO_QUOTA_EXCEEDED") for r in results), results
    Session = sessionmaker(bind=file_engine)
    with Session() as db:
        studio = db.get(Studio, studio_id)
        assert studio.reserved_bytes == 900 <= studio.quota_bytes
        assert db.get(PlatformStorage, 1).reserved_bytes == 900
        held = db.query(UploadSession).filter(UploadSession.reservation_status == "reserved").count()
        assert held == 3


def test_concurrent_reservations_cannot_oversubscribe_the_platform(file_engine, monkeypatch):
    monkeypatch.setattr(get_settings(), "platform_capacity_bytes", 500)
    studio_id, ids = _seed_concurrency(file_engine, studio_quota=10_000, n=10)
    results = _race(file_engine, studio_id, ids, 200)
    assert results.count("ok") == 2
    assert all(r in ("ok", "PLATFORM_CAPACITY_EXCEEDED") for r in results), results
    Session = sessionmaker(bind=file_engine)
    with Session() as db:
        # The failed attempts must have rolled back their studio-level claim too.
        assert db.get(Studio, studio_id).reserved_bytes == 400
        assert db.get(PlatformStorage, 1).reserved_bytes == 400


# ---- audit trail for uploads -----------------------------------------------------------

def test_upload_success_and_failures_are_audited_without_sensitive_data(client, db_session, fake_storage, env):
    from app.models.audit_log import AuditLog

    # success
    _, done, _ = upload_file(client, fake_storage, env["album"], _uid())
    assert done.status_code == 200
    # abandoned
    abandoned = _uid()
    start_upload(client, env["album"].id, abandoned, SIZE)
    client.post(f"/api/admin/media/upload-session/{abandoned}/abandon")
    # rejected by quota
    start_upload(client, env["album"].id, _uid(), SIZE * 10)

    rows = db_session.query(AuditLog).filter(AuditLog.studio_id == env["studio"].id).all()
    by_action = {}
    for r in rows:
        by_action.setdefault(r.action, []).append(r)
    assert len(by_action["media_uploaded"]) == 1
    failed_codes = sorted(r.event_metadata["error_code"] for r in by_action["media_upload_failed"])
    assert failed_codes == ["STUDIO_QUOTA_EXCEEDED", "UPLOAD_ABANDONED"]
    dump = " ".join(str(r.event_metadata) for r in rows)
    assert "fake.drive" not in dump and "http" not in dump
