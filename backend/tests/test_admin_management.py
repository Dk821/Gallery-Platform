from tests.conftest import login_as_admin, login_as_client


def test_admin_create_and_list_client(client, seeded_admin):
    login_as_admin(client, seeded_admin)

    create_resp = client.post(
        "/api/admin/clients", json={"client_name": "New Client", "password": "good"}
    )
    assert create_resp.status_code == 200
    body = create_resp.json()["data"]
    assert body["client_name"] == "New Client"
    assert body["gallery_url_path"].startswith("/gallery/")
    assert body["has_download_password"] is False

    list_resp = client.get("/api/admin/clients")
    assert list_resp.status_code == 200
    items = list_resp.json()["data"]["items"]
    assert any(item["client_name"] == "New Client" for item in items)


def test_admin_set_and_change_download_password(client, seeded_admin, seeded_client):
    login_as_admin(client, seeded_admin)

    set_resp = client.post(
        f"/api/admin/clients/{seeded_client.id}/change-download-password",
        json={"password": "1234"},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["data"]["has_download_password"] is True

    change_resp = client.post(
        f"/api/admin/clients/{seeded_client.id}/change-download-password",
        json={"password": "5678"},
    )
    assert change_resp.status_code == 200

    detail_resp = client.get(f"/api/admin/clients/{seeded_client.id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["data"]["has_download_password"] is True


def test_admin_clear_download_password(client, seeded_admin, seeded_client):
    login_as_admin(client, seeded_admin)
    client.post(
        f"/api/admin/clients/{seeded_client.id}/change-download-password",
        json={"password": "abcd"},
    )
    clear_resp = client.post(
        f"/api/admin/clients/{seeded_client.id}/change-download-password",
        json={"password": None},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["data"]["has_download_password"] is False


def test_admin_disable_then_client_login_fails(client, seeded_admin, seeded_client):
    login_as_admin(client, seeded_admin)

    disable_resp = client.post(f"/api/admin/clients/{seeded_client.id}/disable")
    assert disable_resp.status_code == 200
    assert disable_resp.json()["data"]["status"] == "disabled"

    # Client can no longer log in while disabled.
    login_resp = client.post(
        "/api/auth/client/login",
        json={"gallery_id": seeded_client.client_uuid, "password": "client-pass-1"},
    )
    assert login_resp.status_code == 401


def test_admin_regenerate_gallery_id_changes_url(client, seeded_admin, seeded_client):
    login_as_admin(client, seeded_admin)
    old_uuid = seeded_client.client_uuid

    resp = client.post(f"/api/admin/clients/{seeded_client.id}/regenerate-gallery-id")
    assert resp.status_code == 200
    new_uuid = resp.json()["data"]["client_uuid"]
    assert new_uuid != old_uuid

    # Old gallery link must stop working immediately.
    old_login = client.post("/api/auth/client/login", json={"gallery_id": old_uuid, "password": "client-pass-1"})
    assert old_login.status_code == 401


def test_admin_create_album_for_client(client, seeded_admin, seeded_client):
    login_as_admin(client, seeded_admin)

    resp = client.post(
        "/api/admin/albums",
        json={"client_id": seeded_client.id, "album_name": "Reception", "description": "Evening reception"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["album_name"] == "Reception"


def test_admin_create_album_for_nonexistent_client_fails(client, seeded_admin):
    login_as_admin(client, seeded_admin)

    resp = client.post(
        "/api/admin/albums", json={"client_id": 999999, "album_name": "Ghost Album"}
    )
    assert resp.status_code == 404


def test_non_admin_cannot_call_admin_routes(client):
    resp = client.get("/api/admin/clients")
    assert resp.status_code == 401


def test_admin_delete_album(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    resp = client.delete(f"/api/admin/albums/{seeded_album_for_client.id}")
    assert resp.status_code == 200

    get_resp = client.put(f"/api/admin/albums/{seeded_album_for_client.id}", json={"album_name": "x"})
    assert get_resp.status_code == 404


def test_admin_view_passwords_new_client(client, seeded_admin):
    login_as_admin(client, seeded_admin)

    created = client.post(
        "/api/admin/clients",
        json={"client_name": "Viewable Client", "password": "abcd", "download_password": "1234"},
    )
    assert created.status_code == 200
    client_id = created.json()["data"]["id"]

    resp = client.get(f"/api/admin/clients/{client_id}/passwords")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["gallery_password"] == "abcd"
    assert data["download_password"] == "1234"


def test_admin_view_passwords_legacy_client_returns_none(client, seeded_admin, seeded_client):
    login_as_admin(client, seeded_admin)

    # seeded_client was inserted directly with a hash and no encrypted copy
    # (simulating a client created before this feature shipped).
    resp = client.get(f"/api/admin/clients/{seeded_client.id}/passwords")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["gallery_password"] is None
    assert data["download_password"] is None


def test_admin_view_passwords_reflects_changes(client, seeded_admin, seeded_client):
    login_as_admin(client, seeded_admin)

    # After changing an old client's password, the encrypted copy is written
    # so the admin can view it again.
    resp = client.post(
        f"/api/admin/clients/{seeded_client.id}/change-password", json={"password": "wxyz"}
    )
    assert resp.status_code == 200

    view = client.get(f"/api/admin/clients/{seeded_client.id}/passwords")
    assert view.status_code == 200
    assert view.json()["data"]["gallery_password"] == "wxyz"

    # Clearing a download password also clears the viewable copy.
    set_pw = client.post(
        f"/api/admin/clients/{seeded_client.id}/change-download-password", json={"password": "5678"}
    )
    assert set_pw.status_code == 200
    view = client.get(f"/api/admin/clients/{seeded_client.id}/passwords")
    assert view.json()["data"]["download_password"] == "5678"

    clear_pw = client.post(
        f"/api/admin/clients/{seeded_client.id}/change-download-password", json={"password": None}
    )
    assert clear_pw.status_code == 200
    view = client.get(f"/api/admin/clients/{seeded_client.id}/passwords")
    assert view.json()["data"]["download_password"] is None


def test_client_session_cannot_view_admin_passwords(client, seeded_client):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get(f"/api/admin/clients/{seeded_client.id}/passwords")
    assert resp.status_code == 401
