"""R2 provider (against a fake S3 client), tenant-prefixed keys, and the legacy-data mapping service."""

import io
import uuid

import pytest

from app.api.deps import get_current_admin  # noqa: F401
from app.config.settings import Settings
from app.models.admin import Admin
from app.models.client import Client
from app.models.media import Media
from app.models.studio import Studio
from app.services import legacy_mapping
from app.services.legacy_mapping import LegacyMappingError
from app.services.r2_storage import R2Storage
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageError, StorageNotFoundError
from tests.ms_helpers import (
    JPEG, complete_upload, fresh, login, make_admin, make_client_album, make_media, make_studio, start_upload,
)


class FakeS3:
    """Just enough of the boto3 S3 client surface for R2Storage."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.presigned: list[dict] = []

    def generate_presigned_url(self, op, Params, ExpiresIn, HttpMethod):
        self.presigned.append({"op": op, "params": Params, "expires": ExpiresIn, "method": HttpMethod})
        return f"https://r2.example/{Params['Bucket']}/{Params['Key']}?sig=abc"

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            err = Exception("nf")
            err.response = {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}
            raise err
        return {"ContentLength": len(self.objects[Key]), "ContentType": "image/jpeg"}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def upload_fileobj(self, fileobj, Bucket, Key, ExtraArgs=None):
        self.objects[Key] = fileobj.read()

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key, Range=None):
        data = self.objects[Key]
        class Body:
            def iter_chunks(self_inner, n):
                yield data
            def close(self_inner):
                pass
        return {"Body": Body()}

    def get_paginator(self, name):
        outer = self
        class P:
            def paginate(self_inner, Bucket, Prefix, Delimiter=None):
                yield {"Contents": [{"Key": k, "Size": len(v)} for k, v in outer.objects.items() if k.startswith(Prefix)]}
        return P()

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.objects.pop(o["Key"], None)


def _settings(**kw):
    base = dict(
        r2_account_id="acct", r2_access_key_id="AKIA-TEST", r2_secret_access_key="SECRET-TEST", r2_bucket="bkt",
        r2_presign_ttl_seconds=600,
    )
    base.update(kw)
    return Settings.model_construct(**base)


@pytest.fixture()
def r2():
    s3 = FakeS3()
    return R2Storage(_settings(), client=s3), s3


# ---- R2 provider unit tests --------------------------------------------------------

def test_object_keys_are_tenant_scoped(r2):
    storage, _ = r2
    assert storage.object_key_for(7, 12, "abc-uuid") == "studios/7/albums/12/abc-uuid"
    assert storage.provider_name == "r2"


def test_owns_object_rejects_other_tenants_and_traversal(r2):
    storage, _ = r2
    assert storage.owns_object("studios/7/albums/1/x", 7)
    assert not storage.owns_object("studios/8/albums/1/x", 7)
    assert not storage.owns_object("studios/70/albums/1/x", 7)       # prefix must end at the "/" boundary
    assert not storage.owns_object("studios/7/../8/albums/1/x", 7)
    assert not storage.owns_object("/studios/7/albums/1/x", 7)
    assert not storage.owns_object("", 7)


def test_presigned_url_signs_key_length_and_expiry_without_leaking_secrets(r2):
    storage, s3 = r2
    url = storage.create_resumable_session(
        "p.jpg", "image/jpeg", 1234, "studios/7/albums/1", upload_id="u1", object_key="studios/7/albums/1/k"
    )
    sent = s3.presigned[0]
    assert sent["method"] == "PUT" and sent["expires"] == 600
    assert sent["params"]["Key"] == "studios/7/albums/1/k" and sent["params"]["ContentLength"] == 1234
    assert "SECRET-TEST" not in url and "AKIA-TEST" not in url


def test_put_bytes_stores_under_the_exact_key_and_refuses_bad_keys(r2):
    storage, s3 = r2
    storage.put_bytes("studios/7/branding/logo-abc.png", b"png-bytes", "image/png")
    assert s3.objects["studios/7/branding/logo-abc.png"] == b"png-bytes"
    for bad in ("", "/etc/passwd", "studios/7/../8/x"):
        with pytest.raises(StorageError):
            storage.put_bytes(bad, b"x", "image/png")


def test_files_over_5_gib_are_refused_for_single_put(r2):
    storage, _ = r2
    with pytest.raises(StorageError):
        storage.create_resumable_session("v.mp4", "video/mp4", 6 * 1024**3, "studios/1/albums/1")


def test_get_delete_and_not_found(r2):
    storage, s3 = r2
    s3.objects["studios/1/albums/1/a"] = b"hello"
    assert storage.get_file("studios/1/albums/1/a").size == 5
    storage.delete("studios/1/albums/1/a")
    storage.delete("studios/1/albums/1/a")  # idempotent
    with pytest.raises(StorageNotFoundError):
        storage.get_file("studios/1/albums/1/a")


def test_delete_folder_only_removes_its_prefix(r2):
    storage, s3 = r2
    s3.objects.update({"studios/1/albums/1/a": b"1", "studios/1/albums/10/b": b"2", "studios/2/albums/1/c": b"3"})
    storage.delete_folder("studios/1/albums/1")
    assert set(s3.objects) == {"studios/1/albums/10/b", "studios/2/albums/1/c"}


def test_missing_configuration_names_variables_but_never_values():
    with pytest.raises(StorageError) as exc:
        R2Storage(_settings(r2_bucket="", r2_secret_access_key=None))
    assert "R2_BUCKET" in str(exc.value) and "R2_SECRET_ACCESS_KEY" in str(exc.value)
    assert "AKIA-TEST" not in str(exc.value)


# ---- end-to-end with R2 as the active provider ----------------------------------------

@pytest.fixture()
def r2_app(client, db_session, r2):
    from app.main import app
    storage, s3 = r2
    app.dependency_overrides[get_storage_service] = lambda: storage
    studio = make_studio(db_session, "R2 Studio", quota=10_000)
    make_admin(db_session, studio, "r2@r2.dev")
    c, album = make_client_album(db_session, studio)
    login(client, "r2@r2.dev")
    return {"studio": studio, "album": album, "s3": s3, "storage": storage}


def test_r2_upload_flow_uses_a_server_chosen_tenant_key_and_counts_usage(client, db_session, r2_app):
    uid = str(uuid.uuid4())
    started = start_upload(client, r2_app["album"].id, uid, len(JPEG))
    assert started.status_code == 200, started.text
    presigned = r2_app["s3"].presigned[-1]["params"]
    key = presigned["Key"]
    assert key.startswith(f"studios/{r2_app['studio'].id}/albums/{r2_app['album'].id}/")
    assert presigned["ContentLength"] == len(JPEG)

    r2_app["s3"].objects[key] = JPEG  # the browser's direct PUT
    # Even if the browser names a *foreign* object, the server uses the key it issued.
    done = complete_upload(client, uid, "studios/999/albums/1/stolen", len(JPEG))
    assert done.status_code == 200, done.text
    media = db_session.query(Media).one()
    assert media.storage_provider == "r2" and media.storage_key == key
    assert fresh(db_session, Studio, r2_app["studio"].id).used_bytes == len(JPEG)


def test_r2_client_folders_live_under_the_studio_prefix(client, db_session, r2_app):
    # Every object a studio user creates (originals AND thumbnails, which sit in
    # the client's folder) must be under studios/{id}/ - never at the bucket root.
    sid = r2_app["studio"].id
    res = client.post("/api/admin/clients", json={"client_name": "Rooted Couple"})
    assert res.status_code in (200, 201), res.text
    folder = db_session.query(Client).filter(Client.client_name == "Rooted Couple").one().drive_folder_id
    assert folder.startswith(f"studios/{sid}/")
    storage = r2_app["storage"]
    assert storage.owns_object(folder + "/Thumbnails/t.webp", sid)
    assert not storage.owns_object(folder + "/Thumbnails/t.webp", sid + 1)


def test_named_studio_layout_for_clients_albums_uploads_and_logo(client, db_session, r2_app):
    # A studio with a stored prefix gets readable folders end to end:
    #   studios/acme-photo-1/<Client>_C_<uid>/Thumbnails/...   (client folder)
    #   studios/acme-photo-1/albums/<client-name>_<album id>/<uuid>   (originals)
    studio = r2_app["studio"]
    studio.storage_prefix = f"studios/acme-photo-{studio.id}"
    db_session.commit()
    prefix = studio.storage_prefix

    made = client.post("/api/admin/clients", json={"client_name": "Test Couple"})
    assert made.status_code in (200, 201), made.text
    cid = made.json()["data"]["id"]
    folder = db_session.query(Client).filter(Client.id == cid).one().drive_folder_id
    assert folder.startswith(prefix + "/Test Couple_C_")

    alb = client.post("/api/admin/albums", json={"client_id": cid, "album_name": "Wedding Day"})
    assert alb.status_code in (200, 201), alb.text
    album_id = alb.json()["data"]["id"]
    album_folder = f"{prefix}/albums/test-couple_{album_id}"
    from app.models.album import Album
    assert db_session.query(Album).filter(Album.id == album_id).one().drive_folder_id == album_folder

    uid = str(uuid.uuid4())
    assert start_upload(client, album_id, uid, len(JPEG)).status_code == 200
    key = r2_app["s3"].presigned[-1]["params"]["Key"]
    assert key.startswith(album_folder + "/") and len(key) == len(album_folder) + 1 + 36

    r2_app["s3"].objects[key] = JPEG
    assert complete_upload(client, uid, "ignored", len(JPEG)).status_code == 200
    assert db_session.query(Media).one().storage_key == key

    from app.services.studio_logo_service import logo_key
    assert logo_key(studio, "0123456789abcdef") == f"{prefix}/branding/logo-0123456789abcdef.png"


def test_legacy_studio_without_a_prefix_keeps_the_id_layout(client, db_session, r2_app):
    studio = r2_app["studio"]
    assert studio.storage_prefix is None
    made = client.post("/api/admin/clients", json={"client_name": "Old Couple"})
    cid = made.json()["data"]["id"]
    assert db_session.query(Client).filter(Client.id == cid).one().drive_folder_id.startswith(f"studios/{studio.id}/Old Couple_C_")
    from app.services.studio_logo_service import logo_key
    assert logo_key(studio, "0123456789abcdef") == f"studios/{studio.id}/branding/logo-0123456789abcdef.png"


def test_studio_prefix_helpers_and_tenant_check(r2):
    from app.services.storage_paths import build_studio_prefix, slugify

    storage, _ = r2
    assert build_studio_prefix("Acme Photo & Co.", 12) == "studios/acme-photo-co-12"
    assert build_studio_prefix("  ", 3) == "studios/studio-3"
    assert build_studio_prefix("\u0939\u093f\u0902\u0926\u0940", 4) == "studios/studio-4"
    assert slugify("A" * 100, "x") == "a" * 30
    # named and legacy folders both belong to exactly their own studio
    assert storage.owns_object("studios/acme-photo-12/albums/x_1/u", 12)
    assert storage.owns_object("studios/12/albums/1/u", 12)
    assert not storage.owns_object("studios/acme-photo-12/albums/x_1/u", 2)      # "...-12" is not studio 2
    assert not storage.owns_object("studios/acme-photo-2/albums/x_1/u", 12)
    assert not storage.owns_object("studios/acme-1-12/albums/x_1/u", 1)          # a name ending in -1 does not fool it
    assert not storage.owns_object("other/acme-photo-12/x", 12)
    assert not storage.owns_object("studios/acme-photo-12", 12)                  # no object under it


def test_r2_delete_removes_the_object_and_frees_quota(client, db_session, r2_app):
    uid = str(uuid.uuid4())
    start_upload(client, r2_app["album"].id, uid, len(JPEG))
    key = r2_app["s3"].presigned[-1]["params"]["Key"]
    r2_app["s3"].objects[key] = JPEG
    complete_upload(client, uid, key, len(JPEG))
    mid = db_session.query(Media).one().id
    assert client.delete(f"/api/admin/media/{mid}").status_code == 200
    assert key not in r2_app["s3"].objects
    assert fresh(db_session, Studio, r2_app["studio"].id).used_bytes == 0


def test_r2_completion_when_object_was_never_uploaded_fails_and_releases(client, db_session, r2_app):
    uid = str(uuid.uuid4())
    start_upload(client, r2_app["album"].id, uid, len(JPEG))
    done = complete_upload(client, uid, "ignored", len(JPEG))
    assert done.status_code >= 400
    row = fresh(db_session, Studio, r2_app["studio"].id)
    assert (row.used_bytes, row.reserved_bytes) == (0, 0)


# ---- legacy mapping --------------------------------------------------------------------

def _legacy_world(db):
    """Rows exactly as the migration leaves existing data: studio_id NULL."""
    studio = make_studio(db, "Legacy Owner", quota=100_000)
    admin = make_admin(db, studio, "old@admin.dev")
    c, album = make_client_album(db, studio)
    m1, m2 = make_media(db, studio, c, album, size=3000), make_media(db, studio, c, album, size=2000)
    for row in (admin, c, album, m1, m2):
        row.studio_id = None
    db.commit()
    return studio, admin, c


def test_report_lists_unmapped_rows_and_bytes(db_session):
    _legacy_world(db_session)
    report = legacy_mapping.report_unmapped(db_session)
    assert report["unmapped_rows"]["clients"] == 1 and report["unmapped_rows"]["media"] == 2
    assert report["unmapped_media_bytes"] == 5000 and len(report["unmapped_admins"]) == 1


def test_dry_run_changes_nothing_and_apply_maps_everything_and_updates_counters(db_session):
    studio, admin, c = _legacy_world(db_session)
    plan = legacy_mapping.map_legacy_to_studio(db_session, studio.id)
    assert plan["applied"] is False and plan["media_bytes_to_map"] == 5000
    assert fresh(db_session, Client, c.id).studio_id is None

    legacy_mapping.map_legacy_to_studio(db_session, studio.id, apply=True)
    assert fresh(db_session, Client, c.id).studio_id == studio.id
    assert fresh(db_session, Admin, admin.id).studio_id == studio.id
    assert {m.studio_id for m in db_session.query(Media)} == {studio.id}
    assert fresh(db_session, Studio, studio.id).used_bytes == 5000
    # Idempotent: a second run maps nothing and does not double-count.
    legacy_mapping.map_legacy_to_studio(db_session, studio.id, apply=True)
    assert fresh(db_session, Studio, studio.id).used_bytes == 5000


def test_mapping_refuses_when_legacy_data_does_not_fit_the_quota(db_session):
    studio, _, c = _legacy_world(db_session)
    studio.quota_bytes = 4000
    db_session.commit()
    with pytest.raises(LegacyMappingError):
        legacy_mapping.map_legacy_to_studio(db_session, studio.id, apply=True)
    assert fresh(db_session, Client, c.id).studio_id is None  # nothing changed


def test_mapping_to_a_missing_studio_fails(db_session):
    with pytest.raises(LegacyMappingError):
        legacy_mapping.map_legacy_to_studio(db_session, 424242)
