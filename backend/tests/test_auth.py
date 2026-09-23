def test_admin_login_success(client, seeded_admin):
    resp = client.post(
        "/api/auth/admin/login",
        json={"email": "owner@studio.dev", "password": "correct-horse-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "admin_session" in resp.cookies


def test_admin_login_wrong_password(client, seeded_admin):
    resp = client.post(
        "/api/auth/admin/login",
        json={"email": "owner@studio.dev", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_CREDENTIALS"


def test_admin_login_unknown_email_same_error(client, seeded_admin):
    # Must not leak whether the email exists.
    resp = client.post(
        "/api/auth/admin/login",
        json={"email": "nobody@studio.dev", "password": "whatever"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_client_login_success_and_me(client, seeded_client):
    login = client.post(
        "/api/auth/client/login",
        json={"gallery_id": seeded_client.client_uuid, "password": "client-pass-1"},
    )
    assert login.status_code == 200
    assert "client_session" in login.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    data = me.json()["data"]
    assert data["user_type"] == "client"
    assert data["id"] == seeded_client.id


def test_client_login_wrong_password(client, seeded_client):
    resp = client.post(
        "/api/auth/client/login",
        json={"gallery_id": seeded_client.client_uuid, "password": "wrong"},
    )
    assert resp.status_code == 401


def test_client_login_disabled_account_rejected(client, seeded_client, db_session):
    seeded_client.status = "disabled"
    db_session.commit()
    resp = client.post(
        "/api/auth/client/login",
        json={"gallery_id": seeded_client.client_uuid, "password": "client-pass-1"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Optional gallery password - galleries without a password open directly
# ---------------------------------------------------------------------------


def _make_passwordless_client(db_session):
    from app.models.client import Client

    c = Client(
        client_uuid="33333333-3333-3333-3333-333333333333",
        client_name="Open Wedding",
        password_hash=None,
        status="active",
        drive_folder_id="folder-test-client-open",
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c


def test_gallery_access_password_protected_requires_password(client, seeded_client):
    resp = client.get(f"/api/client/gallery/access/{seeded_client.client_uuid}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["requires_password"] is True
    assert data["client_name"] == seeded_client.client_name


def test_gallery_access_passwordless_opens_directly(client, db_session):
    c = _make_passwordless_client(db_session)
    resp = client.get(f"/api/client/gallery/access/{c.client_uuid}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["requires_password"] is False


def test_gallery_access_unknown_gallery_not_found(client):
    resp = client.get("/api/client/gallery/access/99999999-9999-9999-9999-999999999999")
    assert resp.status_code == 404


def test_password_protected_gallery_rejects_passwordless_login(client, seeded_client):
    # A gallery WITH a password must never be entered without a password.
    resp = client.post(
        "/api/auth/client/login",
        json={"gallery_id": seeded_client.client_uuid, "password": ""},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_password_protected_gallery_rejects_wrong_password_client(client, seeded_client):
    resp = client.post(
        "/api/auth/client/login",
        json={"gallery_id": seeded_client.client_uuid, "password": "nope-wrong"},
    )
    assert resp.status_code == 401


def test_passwordless_gallery_login_and_gallery_access(client, db_session):
    c = _make_passwordless_client(db_session)

    # No password supplied -> still gets a session.
    login = client.post(
        "/api/auth/client/login",
        json={"gallery_id": c.client_uuid, "password": ""},
    )
    assert login.status_code == 200
    assert "client_session" in login.cookies

    # And can reach the gallery endpoint (session still required).
    gallery = client.get("/api/client/gallery")
    assert gallery.status_code == 200
    assert gallery.json()["data"]["client_uuid"] == c.client_uuid


def test_passwordless_gallery_login_without_password_key(client, db_session):
    c = _make_passwordless_client(db_session)
    login = client.post("/api/auth/client/login", json={"gallery_id": c.client_uuid})
    assert login.status_code == 200
    assert "client_session" in login.cookies


def test_logout_clears_session(client, seeded_client):
    client.post(
        "/api/auth/client/login",
        json={"gallery_id": seeded_client.client_uuid, "password": "client-pass-1"},
    )
    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    me = client.get("/api/auth/me")
    assert me.json()["data"] is None


def test_unauthenticated_me_returns_null(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["data"] is None


# ---------------------------------------------------------------------------
# Cross-origin cookie config (SameSite/Secure) - see app/security/session.py
# ---------------------------------------------------------------------------


def _admin_login_set_cookie_header(client, seeded_admin) -> str:
    resp = client.post(
        "/api/auth/admin/login",
        json={"email": "owner@studio.dev", "password": "correct-horse-1"},
    )
    assert resp.status_code == 200
    set_cookie_headers = resp.headers.get_list("set-cookie")
    admin_cookie_header = next(h for h in set_cookie_headers if h.startswith("admin_session="))
    return admin_cookie_header


def test_same_origin_default_uses_samesite_lax(client, seeded_admin):
    # Default config (cross_site_frontend=False): SameSite=Lax, the
    # stronger baseline CSRF-protective default for same-origin setups.
    header = _admin_login_set_cookie_header(client, seeded_admin)
    assert "samesite=lax" in header.lower()


def test_cross_site_frontend_enabled_uses_samesite_none_and_secure(client, seeded_admin, monkeypatch):
    from app.security import session as session_module

    monkeypatch.setattr(session_module.settings, "cross_site_frontend", True)
    header = _admin_login_set_cookie_header(client, seeded_admin)
    assert "samesite=none" in header.lower()
    # SameSite=None is meaningless (and rejected by browsers) without
    # Secure - the fix must always pair the two together.
    assert "secure" in header.lower()


def test_cookie_security_attrs_same_origin_dev_is_insecure_lax():
    from app.security.session import _cookie_security_attrs, settings

    original_env = settings.environment
    original_cross_site = settings.cross_site_frontend
    try:
        settings.environment = "development"
        settings.cross_site_frontend = False
        secure, samesite = _cookie_security_attrs()
        assert secure is False
        assert samesite == "lax"
    finally:
        settings.environment = original_env
        settings.cross_site_frontend = original_cross_site


def test_cookie_security_attrs_same_origin_prod_is_secure_lax():
    from app.security.session import _cookie_security_attrs, settings

    original_env = settings.environment
    original_cross_site = settings.cross_site_frontend
    try:
        settings.environment = "production"
        settings.cross_site_frontend = False
        secure, samesite = _cookie_security_attrs()
        assert secure is True
        assert samesite == "lax"
    finally:
        settings.environment = original_env
        settings.cross_site_frontend = original_cross_site


def test_cookie_security_attrs_cross_site_always_secure_none_regardless_of_env():
    from app.security.session import _cookie_security_attrs, settings

    original_env = settings.environment
    original_cross_site = settings.cross_site_frontend
    try:
        settings.cross_site_frontend = True
        for env in ("development", "production"):
            settings.environment = env
            secure, samesite = _cookie_security_attrs()
            assert secure is True
            assert samesite == "none"
    finally:
        settings.environment = original_env
        settings.cross_site_frontend = original_cross_site
