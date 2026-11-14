"""Super admin Settings: edit own name/email, recent sign-ins, sign out other devices."""

from app.models.admin import Admin
from app.models.audit_log import AuditLog
from tests.ms_helpers import PASSWORD, fresh, login, make_admin, make_studio, make_super_admin


def _boot(client, db):
    root = make_super_admin(db)
    assert login(client, "root@platform.dev").status_code == 200
    return root


def test_account_shows_details_and_recent_sign_ins(client, db_session):
    _boot(client, db_session)
    client.post("/api/auth/admin/login", json={"email": "root@platform.dev", "password": "wrong-pass"})
    data = client.get("/api/super-admin/account").json()["data"]
    assert data["email"] == "root@platform.dev" and data["role"] == "super_admin"
    flags = [r["success"] for r in data["recent_sign_ins"]]
    assert True in flags and False in flags
    assert flags[0] is False  # newest first: the failed attempt


def test_name_change_needs_no_password_but_email_change_does(client, db_session):
    root = _boot(client, db_session)
    r = client.put("/api/super-admin/account", json={"name": "  New Name "})
    assert r.status_code == 200 and r.json()["data"]["name"] == "New Name"
    assert client.get("/api/auth/me").json()["data"]["name"] == "New Name"
    # email: password required and checked
    assert client.put("/api/super-admin/account", json={"email": "new@platform.dev"}).status_code == 400
    bad = client.put("/api/super-admin/account", json={"email": "new@platform.dev", "current_password": "nope"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"
    ok = client.put("/api/super-admin/account", json={"email": "New@Platform.dev", "current_password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["data"]["email"] == "new@platform.dev"
    # the new email is the sign-in name now
    other = client.post("/api/auth/admin/login", json={"email": "new@platform.dev", "password": PASSWORD})
    assert other.status_code == 200
    rows = db_session.query(AuditLog).filter(AuditLog.action == "super_admin_account_updated").all()
    assert len(rows) == 2
    assert all("password" not in str(r.event_metadata) and "platform.dev" not in str(r.event_metadata) for r in rows)


def test_email_already_used_and_blank_name_are_refused(client, db_session):
    _boot(client, db_session)
    studio = make_studio(db_session, "Taken Studio")
    make_admin(db_session, studio, "owner@taken.dev")
    dup = client.put("/api/super-admin/account", json={"email": "owner@taken.dev", "current_password": PASSWORD})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "ADMIN_EMAIL_EXISTS"
    assert client.put("/api/super-admin/account", json={"name": "   "}).status_code == 422


def test_sign_out_other_devices_keeps_this_one(client, db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    root = _boot(client, db_session)
    second = TestClient(app)
    assert second.post("/api/auth/admin/login", json={"email": "root@platform.dev", "password": PASSWORD}).status_code == 200
    assert second.get("/api/super-admin/account").status_code == 200
    assert client.post("/api/super-admin/sign-out-others").status_code == 200
    assert client.get("/api/super-admin/account").status_code == 200  # this browser stays signed in
    assert second.get("/api/super-admin/account").status_code == 401  # the other one is out
    assert db_session.query(AuditLog).filter(AuditLog.action == "super_admin_signed_out_other_devices").count() == 1


def test_account_routes_need_a_super_admin(client, db_session):
    studio = make_studio(db_session, "Plain")
    make_admin(db_session, studio, "plain@x.dev")
    assert login(client, "plain@x.dev").status_code == 200
    assert client.get("/api/super-admin/account").status_code == 403
    assert client.put("/api/super-admin/account", json={"name": "x"}).status_code == 403
    assert client.post("/api/super-admin/sign-out-others").status_code == 403


# ---------------------------------------------------------------- company name, contact number, logo
def _png(color=(200, 30, 30)) -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (40, 20), color).save(out, format="PNG")
    return out.getvalue()


def test_company_name_and_contact_number_are_stored_and_can_be_cleared(client, db_session):
    root = _boot(client, db_session)
    r = client.put("/api/super-admin/account", json={"company_name": "  LoveStory PH  ", "contact_phone": "+63 917 123 4567"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["company_name"] == "LoveStory PH" and data["contact_phone"] == "+63 917 123 4567"
    assert fresh(db_session, Admin, root.id).company_name == "LoveStory PH"
    # shown to the console through /auth/me
    me = client.get("/api/auth/me").json()["data"]
    assert me["company_name"] == "LoveStory PH"
    # leaving a field out keeps it; sending it empty clears it
    assert client.put("/api/super-admin/account", json={"name": "Boss"}).json()["data"]["company_name"] == "LoveStory PH"
    cleared = client.put("/api/super-admin/account", json={"company_name": "  ", "contact_phone": ""}).json()["data"]
    assert cleared["company_name"] is None and cleared["contact_phone"] is None
    rows = db_session.query(AuditLog).filter(AuditLog.action == "super_admin_account_updated").all()
    assert rows and "company_name" in rows[0].event_metadata["fields"]
    assert "LoveStory" not in str([r.event_metadata for r in rows])  # which fields changed, never the values


def test_contact_number_must_look_like_a_phone_number(client, db_session):
    _boot(client, db_session)
    assert client.put("/api/super-admin/account", json={"contact_phone": "call me maybe"}).status_code == 422


def test_logo_upload_is_served_publicly_replaced_and_removed(client, db_session):
    root = _boot(client, db_session)
    r = client.post("/api/super-admin/account/logo", files={"file": ("logo.png", _png(), "image/png")})
    assert r.status_code == 200
    url = r.json()["data"]["logo_url"]
    assert url.startswith(f"/api/platform/{root.id}/logo?v=")
    assert client.get("/api/auth/me").json()["data"]["logo_url"] == url
    # public: an <img> sends no credentials
    client.cookies.clear()
    img = client.get(url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content[:4] == b"\x89PNG"
    assert login(client, "root@platform.dev").status_code == 200
    # replacing gives a new URL and deletes the old object
    r2 = client.post("/api/super-admin/account/logo", files={"file": ("l.png", _png((10, 200, 10)), "image/png")})
    new_url = r2.json()["data"]["logo_url"]
    assert new_url != url
    client.cookies.clear()
    assert client.get(new_url).status_code == 200
    assert client.get(url).status_code == 404  # stale version
    assert login(client, "root@platform.dev").status_code == 200
    gone = client.delete("/api/super-admin/account/logo").json()["data"]
    assert gone["logo_url"] is None
    assert client.get(new_url).status_code == 404


def test_logo_rejects_non_images_and_studio_admins(client, db_session):
    _boot(client, db_session)
    bad = client.post("/api/super-admin/account/logo", files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 400
    client.post("/api/auth/logout")
    studio = make_studio(db_session, "Acme")
    make_admin(db_session, studio, "own@acme.dev")
    assert login(client, "own@acme.dev").status_code == 200
    assert client.post("/api/super-admin/account/logo", files={"file": ("l.png", _png(), "image/png")}).status_code == 403
    assert client.put("/api/super-admin/account", json={"company_name": "x"}).status_code == 403
    # a studio admin's id never serves a platform logo
    assert client.get(f"/api/platform/{studio.id}/logo").status_code == 404
