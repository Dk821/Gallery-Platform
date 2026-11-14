"""Super admin 'delete studio AND all its data': everything the studio owns goes, nothing of any other studio does."""

import datetime

from app.main import app
from app.models.admin import Admin
from app.models.album import Album
from app.models.album_comment import AlbumComment
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.download_job import DownloadJob
from app.models.media import Media
from app.models.media_wishlist import MediaWishlist
from app.models.platform_storage import PlatformStorage
from app.models.studio import Studio
from app.models.upload_session import UploadSession
from app.services import quota_service
from app.services.r2_storage import R2Storage
from app.services.storage_provider import get_storage_service as provider_get_storage_service
from tests.ms_helpers import fresh, login, make_admin, make_client_album, make_media, make_studio, make_super_admin
from tests.test_multi_studio_storage import FakeS3, _settings


def _studio_with_data(db, name, s3, slug, size=1000):
    studio = make_studio(db, name, used=size * 2)
    prefix = f"studios/{slug}-{studio.id}/"  # the real layout: the id is the last dash-separated part
    studio.storage_prefix = prefix
    db.commit()
    make_admin(db, studio, f"login@{slug}.dev")
    client, album = make_client_album(db, studio)
    m1 = make_media(db, studio, client, album, size=size, name="a.jpg")
    m2 = make_media(db, studio, client, album, size=size, name="b.jpg")
    for m, n in ((m1, "1"), (m2, "2")):
        m.google_drive_file_id = f"{prefix}albums/x/{n}"
        m.storage_key = m.google_drive_file_id
        m.thumbnail_reference = f"{prefix}thumbs/{n}.webp"
        s3.objects[m.google_drive_file_id] = b"original"
        s3.objects[m.thumbnail_reference] = b"thumb"
    s3.objects[f"{prefix}branding/logo.png"] = b"logo"
    s3.objects[f"{prefix}stray/leftover.bin"] = b"orphan-in-prefix"  # not referenced by any row
    admin = db.query(Admin).filter(Admin.studio_id == studio.id).one()
    db.add(UploadSession(studio_id=studio.id, upload_id=f"up-{studio.id}", admin_id=admin.id, album_id=album.id, filename="u.jpg", total_bytes=500, status="uploading", media_id=m1.id))
    db.add(MediaWishlist(client_id=client.id, media_id=m1.id))
    db.add(AlbumComment(album_id=album.id, client_id=client.id, media_id=m1.id, page_number=1, comment="hi"))
    db.add(
        DownloadJob(
            studio_id=studio.id, client_id=client.id, album_id=album.id, status="completed", requested_by_type="admin",
            requested_by_id=1, expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=1),
        )
    )
    db.commit()
    return studio, client, album


def _setup(client, db_session):
    s3 = FakeS3()
    storage = R2Storage(_settings(), client=s3)
    app.dependency_overrides[provider_get_storage_service] = lambda: storage
    make_super_admin(db_session)
    doomed, doomed_client, _ = _studio_with_data(db_session, "Doomed Studio", s3, "doomed-studio")
    other, other_client, other_album = _studio_with_data(db_session, "Other Studio", s3, "other-studio")
    # platform ledger mirrors the two studios' usage
    quota_service.ensure_platform_row(db_session)
    row = db_session.get(PlatformStorage, quota_service.PLATFORM_ROW_ID)
    row.used_bytes = 4000
    db_session.commit()
    login(client, "root@platform.dev")
    return s3, doomed, doomed_client, other, other_client


def test_deleting_with_data_needs_suspension_and_the_exact_name(client, db_session):
    s3, doomed, _, other, _ = _setup(client, db_session)
    url = f"/api/super-admin/studios/{doomed.id}"
    r = client.delete(url + "?delete_data=true&confirm_name=Doomed Studio")
    assert r.status_code == 409 and r.json()["error"]["code"] == "STUDIO_NOT_SUSPENDED"  # still active

    assert client.post(url + "/suspend").status_code == 200
    assert client.delete(url).json()["error"]["code"] == "STUDIO_NOT_EMPTY"  # default behaviour unchanged
    for bad in ("", "doomed", "Other Studio"):
        r = client.delete(url + f"?delete_data=true&confirm_name={bad}")
        assert r.status_code == 400 and r.json()["error"]["code"] == "CONFIRMATION_MISMATCH", bad
    db_session.expire_all()
    assert db_session.get(Studio, doomed.id) is not None
    assert db_session.query(Media).filter(Media.studio_id == doomed.id).count() == 2
    assert any(k.startswith(f"studios/doomed-studio-{doomed.id}/") for k in s3.objects)  # nothing was deleted by the refusals


def test_delete_studio_and_all_its_data_removes_rows_and_files_only_for_that_studio(client, db_session):
    s3, doomed, doomed_client, other, other_client = _setup(client, db_session)
    did, oid = doomed.id, other.id
    doomed_client_id, doomed_gallery = doomed_client.id, doomed_client.client_uuid
    other_client_id = other_client.id
    other_media_before = db_session.query(Media).filter(Media.studio_id == oid).count()
    url = f"/api/super-admin/studios/{did}"
    client.post(url + "/suspend")

    r = client.delete(url + "?delete_data=true&confirm_name=Doomed Studio")
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {"id": did, "deleted": True, "data_deleted": True, "storage_failures": 0}

    db_session.expire_all()
    # --- everything of the deleted studio is gone
    assert db_session.get(Studio, did) is None
    for model in (Client, Album, Media, DownloadJob, UploadSession):
        assert db_session.query(model).filter(model.studio_id == did).count() == 0, model
    assert db_session.query(Admin).filter(Admin.studio_id == did).count() == 0
    assert db_session.query(MediaWishlist).filter(MediaWishlist.client_id == doomed_client_id).count() == 0
    assert db_session.query(AlbumComment).filter(AlbumComment.client_id == doomed_client_id).count() == 0
    assert not any(k.startswith(f"studios/doomed-studio-{did}/") for k in s3.objects)  # files, thumbnails, logo, strays
    # --- the other studio and the super admin are untouched
    assert db_session.get(Studio, oid) is not None
    assert db_session.query(Media).filter(Media.studio_id == oid).count() == other_media_before
    assert db_session.query(Client).filter(Client.studio_id == oid).count() == 1
    assert db_session.query(Admin).filter(Admin.studio_id == oid).count() == 1
    assert db_session.query(Admin).filter(Admin.role == "super_admin").count() == 1
    assert db_session.query(MediaWishlist).filter(MediaWishlist.client_id == other_client_id).count() == 1
    assert sum(1 for k in s3.objects if k.startswith(f"studios/other-studio-{oid}/")) == 6  # 2 originals, 2 thumbs, logo, stray
    # --- platform ledger gave back the deleted studio's bytes
    assert db_session.get(PlatformStorage, quota_service.PLATFORM_ROW_ID).used_bytes == 2000
    # --- audit
    row = db_session.query(AuditLog).filter(AuditLog.action == "studio_deleted").one()
    assert row.event_metadata["name"] == "Doomed Studio" and row.event_metadata["data_deleted"] is True
    assert row.event_metadata["clients"] == 1 and row.event_metadata["media"] == 2
    # --- its client can no longer open the gallery
    client.cookies.clear()
    r = client.post("/api/auth/client/login", json={"gallery_id": doomed_gallery, "password": "client-pass-1"})
    assert r.status_code in (401, 404)


def test_storage_failures_do_not_leave_a_half_deleted_studio(client, db_session):
    s3, doomed, *_ = _setup(client, db_session)

    def boom(Bucket, Key):
        raise RuntimeError("r2 down")

    s3.delete_object = boom
    url = f"/api/super-admin/studios/{doomed.id}"
    client.post(url + "/suspend")
    r = client.delete(url + "?delete_data=true&confirm_name=Doomed Studio")
    assert r.status_code == 200 and r.json()["data"]["storage_failures"] > 0
    db_session.expire_all()
    assert db_session.get(Studio, doomed.id) is None  # the studio is gone from the database regardless
    assert db_session.query(Media).filter(Media.studio_id == doomed.id).count() == 0


def test_delete_with_data_is_super_admin_only(client, db_session):
    s3, doomed, *_ = _setup(client, db_session)
    client.post(f"/api/super-admin/studios/{doomed.id}/suspend")
    client.cookies.clear()
    login(client, "login@doomed-studio.dev")
    r = client.delete(f"/api/super-admin/studios/{doomed.id}?delete_data=true&confirm_name=Doomed Studio")
    assert r.status_code == 403
    db_session.expire_all()
    assert db_session.get(Studio, doomed.id) is not None
