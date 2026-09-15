from tests.conftest import login_as_admin


def test_get_settings_lazily_creates_defaults(client, seeded_admin):
    login_as_admin(client, seeded_admin)

    resp = client.get("/api/admin/settings")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["studio"]["studio_name"] is None
    assert data["studio"]["min_client_password_length"] == 4
    assert data["studio"]["download_link_ttl_hours"] == 24
    assert data["admin"]["email"] == seeded_admin.email


def test_update_studio_profile(client, seeded_admin):
    login_as_admin(client, seeded_admin)

    resp = client.put(
        "/api/admin/settings/profile",
        json={"studio_name": "Sam Photography", "contact_email": "hello@samphoto.dev"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["studio_name"] == "Sam Photography"
    assert data["contact_email"] == "hello@samphoto.dev"

    # Persisted, not just echoed back.
    again = client.get("/api/admin/settings")
    assert again.json()["data"]["studio"]["studio_name"] == "Sam Photography"


def test_update_security_policy_rejects_out_of_range(client, seeded_admin):
    login_as_admin(client, seeded_admin)

    resp = client.put(
        "/api/admin/settings/security",
        json={"min_client_password_length": 2, "download_link_ttl_hours": 24},
    )
    assert resp.status_code == 422  # below the floor of 4


def test_security_policy_enforced_on_new_client_password(client, seeded_admin):
    login_as_admin(client, seeded_admin)

    policy_resp = client.put(
        "/api/admin/settings/security",
        json={"min_client_password_length": 8, "download_link_ttl_hours": 24},
    )
    assert policy_resp.status_code == 200

    short_resp = client.post(
        "/api/admin/clients", json={"client_name": "Short PW Client", "password": "short12"}
    )
    assert short_resp.status_code == 400
    assert short_resp.json()["error"]["code"] == "PASSWORD_TOO_SHORT"

    long_resp = client.post(
        "/api/admin/clients", json={"client_name": "Long PW Client", "password": "longenough1"}
    )
    assert long_resp.status_code == 200


def test_admin_change_own_password(client, seeded_admin):
    login_as_admin(client, seeded_admin)

    wrong_resp = client.post(
        "/api/admin/settings/change-password",
        json={"current_password": "not-the-real-password", "new_password": "brand-new-pass-1"},
    )
    assert wrong_resp.status_code == 400
    assert wrong_resp.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"

    ok_resp = client.post(
        "/api/admin/settings/change-password",
        json={"current_password": "correct-horse-1", "new_password": "brand-new-pass-1"},
    )
    assert ok_resp.status_code == 200

    # Old password no longer works; new one does.
    client.post("/api/auth/logout")
    stale_login = client.post(
        "/api/auth/admin/login", json={"email": seeded_admin.email, "password": "correct-horse-1"}
    )
    assert stale_login.status_code == 401

    fresh_login = client.post(
        "/api/auth/admin/login", json={"email": seeded_admin.email, "password": "brand-new-pass-1"}
    )
    assert fresh_login.status_code == 200


def test_security_policy_persists_ttl(client, seeded_admin):
    login_as_admin(client, seeded_admin)

    resp = client.put(
        "/api/admin/settings/security",
        json={"min_client_password_length": 4, "download_link_ttl_hours": 72},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["download_link_ttl_hours"] == 72
