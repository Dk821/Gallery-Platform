import datetime
import io

from PIL import Image

from tests.conftest import login_as_admin, login_as_client


def _jpeg_bytes():
    img = Image.new("RGB", (100, 80), color=(50, 60, 70))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _upload(client, album_id, filename):
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(album_id)},
        files={"file": (filename, _jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_find_my_photos_case_insensitive_partial_match(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "IMG_Kumar_001.jpg")
    _upload(client, seeded_album_for_client.id, "Sunset_Beach.jpg")
    _upload(client, seeded_album_for_client.id, "IMG_0234_KUMAR.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get("/api/client/media?search=kumar")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    names = {item["file_name"] for item in data["items"]}
    assert names == {"IMG_Kumar_001.jpg", "IMG_0234_KUMAR.jpg"}


def test_find_my_photos_scoped_to_own_client_only(
    client, seeded_admin, seeded_client, seeded_client_b, seeded_album_for_client, seeded_album_for_client_b
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "Kumar_ClientA.jpg")
    _upload(client, seeded_album_for_client_b.id, "Kumar_ClientB.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get("/api/client/media?search=kumar")
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["file_name"] == "Kumar_ClientA.jpg"


def test_find_my_photos_no_match_returns_empty(client, seeded_client, seeded_album_for_client):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get("/api/client/media?search=nonexistent")
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0


def test_selection_summary_returns_ids_and_total_bytes(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    media_a = _upload(client, seeded_album_for_client.id, "a.jpg")
    media_b = _upload(client, seeded_album_for_client.id, "b.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get("/api/client/media/selection-summary")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_count"] == 2
    assert set(data["ids"]) == {media_a["id"], media_b["id"]}
    assert data["total_bytes"] > 0


def test_selection_summary_respects_search(client, seeded_admin, seeded_client, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "Kumar_1.jpg")
    _upload(client, seeded_album_for_client.id, "Other.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get("/api/client/media/selection-summary?search=kumar")
    data = resp.json()["data"]
    assert data["total_count"] == 1


def test_selection_summary_excludes_expired_album(
    client, seeded_admin, seeded_client, seeded_album_for_client, db_session
):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "photo.jpg")
    client.post("/api/auth/logout")

    seeded_album_for_client.expires_at = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    db_session.commit()

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get("/api/client/media/selection-summary")
    data = resp.json()["data"]
    assert data["total_count"] == 0


def test_selection_summary_requires_client_auth(client):
    resp = client.get("/api/client/media/selection-summary")
    assert resp.status_code == 401
