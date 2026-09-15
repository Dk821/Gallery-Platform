from tests.conftest import login_as_client


def test_client_cannot_access_other_clients_album(
    client, seeded_client, seeded_client_b, seeded_album_for_client
):
    # Client B logs in, then tries to fetch Client A's album by id.
    login_as_client(client, seeded_client_b.client_uuid, "client-pass-2")

    resp = client.get(f"/api/client/albums/{seeded_album_for_client.id}")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ALBUM_FORBIDDEN"


def test_client_cannot_access_other_clients_media(
    client, seeded_client, seeded_client_b, seeded_media_for_client
):
    login_as_client(client, seeded_client_b.client_uuid, "client-pass-2")

    resp = client.get(f"/api/client/media/{seeded_media_for_client.id}")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "MEDIA_FORBIDDEN"


def test_client_cannot_filter_media_by_other_clients_album(
    client, seeded_client, seeded_client_b, seeded_album_for_client
):
    login_as_client(client, seeded_client_b.client_uuid, "client-pass-2")

    resp = client.get(f"/api/client/media?album_id={seeded_album_for_client.id}")
    assert resp.status_code == 403


def test_client_can_access_own_album_and_media(
    client, seeded_client, seeded_album_for_client, seeded_media_for_client
):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")

    album_resp = client.get(f"/api/client/albums/{seeded_album_for_client.id}")
    assert album_resp.status_code == 200
    assert album_resp.json()["data"]["id"] == seeded_album_for_client.id

    media_resp = client.get(f"/api/client/media/{seeded_media_for_client.id}")
    assert media_resp.status_code == 200
    assert media_resp.json()["data"]["id"] == seeded_media_for_client.id


def test_client_albums_list_only_shows_own_albums(
    client, seeded_client, seeded_client_b, seeded_album_for_client
):
    login_as_client(client, seeded_client_b.client_uuid, "client-pass-2")

    resp = client.get("/api/client/albums")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


def test_unauthenticated_client_route_requires_login(client, seeded_album_for_client):
    resp = client.get(f"/api/client/albums/{seeded_album_for_client.id}")
    assert resp.status_code == 401


def test_admin_route_rejects_client_session(client, seeded_client):
    # A client session cookie must never grant admin API access.
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get("/api/admin/clients")
    assert resp.status_code == 401
