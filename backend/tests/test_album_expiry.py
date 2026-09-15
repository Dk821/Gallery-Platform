import datetime
import io

from PIL import Image

from tests.conftest import login_as_admin, login_as_client


def _jpeg_bytes():
    img = Image.new("RGB", (200, 150), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_client_can_access_album_without_expiry(client, seeded_client, seeded_album_for_client):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get(f"/api/client/albums/{seeded_album_for_client.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["expires_at"] is None


def test_client_blocked_from_expired_album(client, seeded_client, seeded_album_for_client, db_session):
    seeded_album_for_client.expires_at = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    db_session.commit()

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get(f"/api/client/albums/{seeded_album_for_client.id}")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ALBUM_EXPIRED"


def test_client_blocked_from_expired_album_media_list(client, seeded_client, seeded_album_for_client, db_session):
    seeded_album_for_client.expires_at = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    db_session.commit()

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get(f"/api/client/media?album_id={seeded_album_for_client.id}")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ALBUM_EXPIRED"


def test_client_blocked_from_expired_album_media_detail_view_download_thumbnail(
    client, seeded_admin, seeded_client, seeded_album_for_client, db_session
):
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    media_id = upload_resp.json()["data"]["id"]
    client.post("/api/auth/logout")

    seeded_album_for_client.expires_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
    db_session.commit()

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    for suffix in ("", "/view", "/download", "/thumbnail"):
        resp = client.get(f"/api/client/media/{media_id}{suffix}")
        assert resp.status_code == 403, f"path '{suffix}' should be forbidden once the album has expired"
        assert resp.json()["error"]["code"] == "ALBUM_EXPIRED"


def test_client_not_yet_expired_album_still_accessible(client, seeded_client, seeded_album_for_client, db_session):
    seeded_album_for_client.expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=2)
    db_session.commit()

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get(f"/api/client/albums/{seeded_album_for_client.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["expires_at"] is not None


def test_admin_can_still_manage_expired_album(client, seeded_admin, seeded_album_for_client, db_session):
    seeded_album_for_client.expires_at = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    db_session.commit()

    login_as_admin(client, seeded_admin)
    get_resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}")
    assert get_resp.status_code == 200

    update_resp = client.put(
        f"/api/admin/albums/{seeded_album_for_client.id}", json={"album_name": "Still Editable"}
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["data"]["album_name"] == "Still Editable"


def test_admin_can_set_and_clear_expiry(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    future = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()

    set_resp = client.put(f"/api/admin/albums/{seeded_album_for_client.id}", json={"expires_at": future})
    assert set_resp.status_code == 200
    assert set_resp.json()["data"]["expires_at"] is not None

    clear_resp = client.put(f"/api/admin/albums/{seeded_album_for_client.id}", json={"expires_at": None})
    assert clear_resp.status_code == 200
    assert clear_resp.json()["data"]["expires_at"] is None


def test_updating_other_fields_does_not_clear_expiry(client, seeded_admin, seeded_album_for_client):
    # Regression guard for the "expires_at omitted vs explicit null" distinction -
    # a PATCH-style update that doesn't mention expires_at at all must never
    # wipe out a previously-set expiry.
    login_as_admin(client, seeded_admin)
    future = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()
    client.put(f"/api/admin/albums/{seeded_album_for_client.id}", json={"expires_at": future})

    resp = client.put(f"/api/admin/albums/{seeded_album_for_client.id}", json={"album_name": "Renamed"})
    assert resp.status_code == 200
    assert resp.json()["data"]["expires_at"] is not None
    assert resp.json()["data"]["album_name"] == "Renamed"
