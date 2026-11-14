"""Super-admin API: multi-studio management, quotas, credentials and audit logs."""

import pytest

from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.models.studio import Studio
from tests.conftest import login_as_admin  # noqa: F401  (kept for parity with other suites)
from tests.ms_helpers import PASSWORD, fresh, login, make_admin, make_client_album, make_studio, make_super_admin, upload_file


def _create_studio(client, name="Acme Photo", admin_email="boss@acme.dev", **extra):
    payload = {"name": name, "admin_name": "Acme Boss", "admin_email": admin_email, **extra}
    return client.post("/api/super-admin/studios", json=payload)


def test_super_admin_creates_and_lists_multiple_studios(client, db_session):
    make_super_admin(db_session)
    assert login(client, "root@platform.dev").status_code == 200

    r1 = _create_studio(client, "Acme Photo", "boss@acme.dev", quota_bytes=10_000_000_000)
    r2 = _create_studio(client, "Beta Weddings", "owner@beta.dev", quota_bytes=20_000_000_000)
    assert r1.status_code == 200 and r2.status_code == 200
    s1, s2 = r1.json()["data"]["studio"], r2.json()["data"]["studio"]
    assert s1["id"] != s2["id"]
    assert s1["usage"] == {"quota_bytes": 10_000_000_000, "used_bytes": 0, "reserved_bytes": 0, "remaining_bytes": 10_000_000_000}
    assert s2["usage"]["quota_bytes"] == 20_000_000_000

    listing = client.get("/api/super-admin/studios").json()["data"]
    names = {s["name"] for s in listing["items"]}
    assert {"Acme Photo", "Beta Weddings"} <= names
    assert listing["total"] >= 2 and "has_more" in listing

    only_beta = client.get("/api/super-admin/studios", params={"search": "beta"}).json()["data"]
    assert [s["name"] for s in only_beta["items"]] == ["Beta Weddings"]

    detail = client.get(f"/api/super-admin/studios/{s1['id']}").json()["data"]
    assert detail["counts"]["admins"] == 1


def test_new_studio_gets_a_permanent_readable_storage_folder(client, db_session):
    from app.models.studio import Studio

    make_super_admin(db_session)
    assert login(client, "root@platform.dev").status_code == 200
    sid = _create_studio(client, "Acme Photo & Co.", "boss@acme.dev").json()["data"]["studio"]["id"]
    assert db_session.query(Studio).filter(Studio.id == sid).one().storage_prefix == f"studios/acme-photo-co-{sid}"

    # Renaming the studio must NOT move its files, so the folder stays as it was.
    assert client.put(f"/api/super-admin/studios/{sid}", json={"name": "Totally Different Name"}).status_code == 200
    db_session.expire_all()
    assert db_session.query(Studio).filter(Studio.id == sid).one().storage_prefix == f"studios/acme-photo-co-{sid}"


def test_create_studio_defaults_quota_from_config_and_returns_one_time_password(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    resp = _create_studio(client)
    data = resp.json()["data"]
    assert data["studio"]["usage"]["quota_bytes"] == 10_000_000_000  # DEFAULT_STUDIO_QUOTA_BYTES
    temp = data["temporary_password"]
    assert temp and len(temp) >= 16
    assert resp.headers["cache-control"] == "no-store"
    # The generated password really works for the new studio admin ...
    client.post("/api/auth/logout")
    assert login(client, "boss@acme.dev", temp).status_code == 200
    # ... and is stored only as a hash.
    admin = db_session.query(Admin).filter(Admin.email == "boss@acme.dev").one()
    assert temp not in admin.password_hash and admin.role == "studio_admin"


def test_supplied_admin_password_is_not_echoed_back(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    resp = _create_studio(client, admin_password="My-Own-Strong-Pass-1")
    assert resp.json()["data"]["temporary_password"] is None
    assert "My-Own-Strong-Pass-1" not in resp.text


def test_studio_admin_cannot_use_super_admin_endpoints(client, db_session):
    studio = make_studio(db_session)
    make_admin(db_session, studio, "a@studio.dev")
    login(client, "a@studio.dev")
    for method, url in [
        ("get", "/api/super-admin/studios"),
        ("get", "/api/super-admin/stats"),
        ("get", "/api/super-admin/audit-logs"),
        ("post", "/api/super-admin/studios"),
        ("put", f"/api/super-admin/studios/{studio.id}/quota"),
        ("post", f"/api/super-admin/studios/{studio.id}/suspend"),
    ]:
        resp = getattr(client, method)(url, **({"json": {}} if method in ("post", "put") else {}))
        assert resp.status_code == 403, (method, url, resp.status_code)
        assert resp.json()["error"]["code"] == "SUPER_ADMIN_REQUIRED"


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/super-admin/studios").status_code == 401
    assert client.get("/api/studio/profile").status_code == 401
    assert client.get("/api/admin/clients").status_code == 401


def test_super_admin_cannot_browse_studio_galleries_through_admin_routes(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    resp = client.get("/api/admin/clients")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "STUDIO_ADMIN_REQUIRED"


def test_update_studio_details(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    sid = _create_studio(client).json()["data"]["studio"]["id"]
    resp = client.put(
        f"/api/super-admin/studios/{sid}",
        json={"name": "Acme Photography", "contact_phone": "+63 900 000 0000", "brand_color": "#112233", "logo_url": "https://cdn.example.com/logo.png"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["name"] == "Acme Photography" and body["brand_color"] == "#112233"


def test_logo_url_must_be_https_and_color_must_be_hex(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    sid = _create_studio(client).json()["data"]["studio"]["id"]
    assert client.put(f"/api/super-admin/studios/{sid}", json={"logo_url": "javascript:alert(1)"}).status_code == 422
    assert client.put(f"/api/super-admin/studios/{sid}", json={"brand_color": "red"}).status_code == 422


def test_duplicate_admin_email_is_a_409(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    assert _create_studio(client, admin_email="dup@x.dev").status_code == 200
    again = _create_studio(client, name="Other", admin_email="dup@x.dev")
    assert again.status_code == 409 and again.json()["error"]["code"] == "ADMIN_EMAIL_EXISTS"


def test_suspend_and_reactivate_with_audit(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    sid = _create_studio(client).json()["data"]["studio"]["id"]
    sus = client.post(f"/api/super-admin/studios/{sid}/suspend", json={"reason": "unpaid invoice"})
    assert sus.json()["data"]["status"] == "suspended"
    assert fresh(db_session, Studio, sid).status == "suspended"
    react = client.post(f"/api/super-admin/studios/{sid}/reactivate")
    assert react.json()["data"]["status"] == "active"

    logs = client.get("/api/super-admin/audit-logs", params={"studio_id": sid}).json()["data"]["items"]
    actions = [row["action"] for row in logs]
    assert {"studio_created", "studio_suspended", "studio_reactivated"} <= set(actions)
    suspended = next(r for r in logs if r["action"] == "studio_suspended")
    assert suspended["metadata"] == {"reason": "unpaid invoice"}
    assert suspended["actor_role"] == "super_admin" and suspended["studio_id"] == sid


def test_quota_change_is_audited_with_old_and_new_values(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    sid = _create_studio(client, quota_bytes=10_000_000_000).json()["data"]["studio"]["id"]
    resp = client.put(f"/api/super-admin/studios/{sid}/quota", json={"quota_bytes": 25_000_000_000})
    assert resp.status_code == 200 and resp.json()["data"]["usage"]["quota_bytes"] == 25_000_000_000
    row = db_session.query(AuditLog).filter(AuditLog.action == "studio_quota_changed").one()
    assert row.event_metadata == {"old_quota_bytes": 10_000_000_000, "new_quota_bytes": 25_000_000_000}


def test_quota_cannot_be_set_below_current_usage(client, db_session):
    make_super_admin(db_session)
    studio = make_studio(db_session, quota=10_000, used=6_000, reserved=2_000)
    login(client, "root@platform.dev")
    resp = client.put(f"/api/super-admin/studios/{studio.id}/quota", json={"quota_bytes": 7_000})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "QUOTA_BELOW_USAGE"
    assert client.put(f"/api/super-admin/studios/{studio.id}/quota", json={"quota_bytes": 8_000}).status_code == 200
    assert client.put(f"/api/super-admin/studios/{studio.id}/quota", json={"quota_bytes": 0}).status_code == 422


def test_usage_and_platform_stats(client, db_session):
    make_super_admin(db_session)
    a = make_studio(db_session, "A", quota=1_000, used=400, reserved=100)
    make_studio(db_session, "B", quota=2_000, status="suspended")
    login(client, "root@platform.dev")
    usage = client.get(f"/api/super-admin/studios/{a.id}/usage").json()["data"]
    assert usage["usage"] == {"quota_bytes": 1000, "used_bytes": 400, "reserved_bytes": 100, "remaining_bytes": 500}
    stats = client.get("/api/super-admin/stats").json()["data"]
    # +1: the conftest default studio (id=1) always exists.
    assert stats["studios"]["total"] == 3 and stats["studios"]["suspended"] == 1
    assert stats["storage"]["capacity_bytes"] == 1_000_000_000_000  # decimal 1 TB default
    assert stats["storage"]["allocated_quota_bytes"] == 900_000_000_000 + 3_000
    assert "unmapped_legacy_rows" in stats


def test_reset_studio_admin_password_revokes_old_credentials_and_sessions(client, db_session):
    make_super_admin(db_session)
    studio = make_studio(db_session)
    victim = make_admin(db_session, studio, "victim@studio.dev", password="Old-Password-123")

    # The victim is logged in somewhere with a still-valid session cookie.
    login(client, "victim@studio.dev", "Old-Password-123")
    old_cookie = client.cookies.get("admin_session")
    assert client.get("/api/admin/clients").status_code == 200

    client.post("/api/auth/logout")
    client.cookies.clear()
    login(client, "root@platform.dev")
    resp = client.post(f"/api/super-admin/studios/{studio.id}/admins/{victim.id}/reset-password")
    assert resp.status_code == 200
    temp = resp.json()["data"]["temporary_password"]
    assert temp and resp.headers["cache-control"] == "no-store"

    # Audit row exists and contains NO password material.
    row = db_session.query(AuditLog).filter(AuditLog.action == "studio_admin_password_reset").one()
    assert row.studio_id == studio.id and row.resource_id == victim.id
    assert temp not in str(row.event_metadata) and "password" not in (row.event_metadata or {})

    client.cookies.clear()
    assert login(client, "victim@studio.dev", "Old-Password-123").status_code == 401  # old password dead
    client.cookies.clear()
    client.cookies.set("admin_session", old_cookie)
    assert client.get("/api/admin/clients").status_code == 401  # old session dead
    client.cookies.clear()
    assert login(client, "victim@studio.dev", temp).status_code == 200  # new one works


def test_reset_cannot_target_an_admin_of_another_studio(client, db_session):
    make_super_admin(db_session)
    a, b = make_studio(db_session, "A"), make_studio(db_session, "B")
    admin_b = make_admin(db_session, b, "b@b.dev")
    login(client, "root@platform.dev")
    resp = client.post(f"/api/super-admin/studios/{a.id}/admins/{admin_b.id}/reset-password")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "ADMIN_NOT_FOUND"


def test_audit_log_listing_filters_and_pagination(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    for i in range(3):
        _create_studio(client, f"S{i}", f"s{i}@x.dev")
    page = client.get("/api/super-admin/audit-logs", params={"action": "studio_created", "limit": 2}).json()["data"]
    assert page["total"] == 3 and len(page["items"]) == 2 and page["has_more"] is True
    assert client.get("/api/super-admin/audit-logs", params={"from": "2030-01-02", "to": "2030-01-01"}).status_code == 400


def test_login_events_are_audited_including_failures(client, db_session):
    studio = make_studio(db_session)
    admin = make_admin(db_session, studio, "a@studio.dev")
    login(client, "a@studio.dev")
    assert login(client, "a@studio.dev", "wrong-password").status_code == 401
    assert login(client, "nobody@nowhere.dev", "x").status_code == 401
    rows = db_session.query(AuditLog).order_by(AuditLog.id).all()
    actions = [r.action for r in rows]
    assert actions.count("admin_login") == 1 and actions.count("admin_login_failed") == 2
    ok = next(r for r in rows if r.action == "admin_login")
    assert ok.user_id == admin.id and ok.studio_id == studio.id and ok.actor_role == "studio_admin"
    # Neither the attempted password nor the attempted email is stored.
    dump = " ".join(str(r.event_metadata) for r in rows)
    assert "wrong-password" not in dump and "nobody@nowhere.dev" not in dump


def test_me_endpoint_reports_role_and_studio(client, db_session):
    studio = make_studio(db_session, "Me Studio")
    make_admin(db_session, studio, "a@studio.dev")
    login(client, "a@studio.dev")
    me = client.get("/api/auth/me").json()["data"]
    assert me["role"] == "studio_admin" and me["studio_id"] == studio.id and me["studio_name"] == "Me Studio"
    assert me["name"] and me["id"] and me["user_type"] == "admin"  # original contract preserved


def test_studio_admin_updates_only_branding_never_quota_or_status(client, db_session):
    studio = make_studio(db_session, quota=5_000)
    make_admin(db_session, studio, "a@studio.dev")
    login(client, "a@studio.dev")
    resp = client.put(
        "/api/studio/profile",
        json={"name": "Renamed", "brand_color": "#abcdef", "quota_bytes": 999_999_999, "status": "suspended", "studio_id": 99},
    )
    assert resp.status_code == 200
    row = fresh(db_session, Studio, studio.id)
    assert row.name == "Renamed" and row.brand_color == "#abcdef"
    assert row.quota_bytes == 5_000 and row.status == "active"
    usage = client.get("/api/studio/usage").json()["data"]
    assert usage["usage"]["quota_bytes"] == 5_000 and usage["usage"]["remaining_bytes"] == 5_000


def test_super_admin_changes_own_password(client, db_session):
    root = make_super_admin(db_session)
    login(client, "root@platform.dev")

    # wrong current password is refused and changes nothing
    bad = client.post("/api/super-admin/change-password", json={"current_password": "nope", "new_password": "abcd"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"

    # below the minimum (4) is refused by validation
    assert client.post(
        "/api/super-admin/change-password", json={"current_password": PASSWORD, "new_password": "abc"}
    ).status_code == 422

    ok = client.post("/api/super-admin/change-password", json={"current_password": PASSWORD, "new_password": "abcd"})
    assert ok.status_code == 200 and ok.headers.get("cache-control") == "no-store"
    # this browser stays signed in (cookie re-issued)
    assert client.get("/api/super-admin/stats").status_code == 200

    # old password is dead, new one works
    client.post("/api/auth/logout")
    assert login(client, "root@platform.dev", PASSWORD).status_code == 401
    assert login(client, "root@platform.dev", "abcd").status_code == 200

    # audited, with no password material
    rows = db_session.query(AuditLog).filter(AuditLog.action == "super_admin_password_changed").all()
    assert len(rows) == 1 and rows[0].user_id == root.id
    assert "abcd" not in str(rows[0].metadata_json if hasattr(rows[0], "metadata_json") else rows[0].__dict__)


def test_studio_admin_cannot_use_super_admin_change_password(client, db_session):
    studio = make_studio(db_session)
    make_admin(db_session, studio, "a@studio.dev")
    login(client, "a@studio.dev")
    r = client.post("/api/super-admin/change-password", json={"current_password": PASSWORD, "new_password": "abcd"})
    assert r.status_code == 403


def test_super_admin_edits_disables_and_enables_a_studio_admin(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    sid = _create_studio(client, admin_email="boss@acme.dev", admin_password="boss-pass-1").json()["data"]["studio"]["id"]
    aid = client.get(f"/api/super-admin/studios/{sid}/admins").json()["data"][0]["id"]

    # a studio admin is signed in on a second client
    from fastapi.testclient import TestClient
    from app.main import app

    other = TestClient(app)
    assert other.post("/api/auth/admin/login", json={"email": "boss@acme.dev", "password": "boss-pass-1"}).status_code == 200
    assert other.get("/api/admin/settings").status_code == 200

    # rename only: still signed in
    r = client.put(f"/api/super-admin/studios/{sid}/admins/{aid}", json={"name": "New Name"})
    assert r.status_code == 200 and r.json()["data"]["name"] == "New Name"
    assert other.get("/api/admin/settings").status_code == 200

    # email change: validated, unique, ends the old session, new email logs in
    make_admin(db_session, make_studio(db_session, "Other"), "taken@other.dev")
    assert client.put(f"/api/super-admin/studios/{sid}/admins/{aid}", json={"email": "taken@other.dev"}).status_code == 409
    assert client.put(f"/api/super-admin/studios/{sid}/admins/{aid}", json={"email": "not-an-email"}).status_code == 422
    assert client.put(f"/api/super-admin/studios/{sid}/admins/{aid}", json={"email": "Boss2@Acme.dev"}).json()["data"]["email"] == "boss2@acme.dev"
    assert other.get("/api/admin/settings").status_code == 401
    assert other.post("/api/auth/admin/login", json={"email": "boss2@acme.dev", "password": "boss-pass-1"}).status_code == 200

    # disable: signed out now, cannot sign in; enable: can again
    assert client.post(f"/api/super-admin/studios/{sid}/admins/{aid}/disable").json()["data"]["status"] == "disabled"
    assert other.get("/api/admin/settings").status_code == 401
    assert other.post("/api/auth/admin/login", json={"email": "boss2@acme.dev", "password": "boss-pass-1"}).status_code == 401
    assert client.post(f"/api/super-admin/studios/{sid}/admins/{aid}/enable").json()["data"]["status"] == "active"
    assert other.post("/api/auth/admin/login", json={"email": "boss2@acme.dev", "password": "boss-pass-1"}).status_code == 200

    actions = {r.action for r in db_session.query(AuditLog).all()}
    assert {"studio_admin_updated", "studio_admin_disabled", "studio_admin_enabled"} <= actions


def test_studio_admin_edit_cannot_cross_studios_or_target_super_admin(client, db_session):
    root = make_super_admin(db_session)
    s1, s2 = make_studio(db_session, "S1"), make_studio(db_session, "S2")
    a2 = make_admin(db_session, s2, "a2@s2.dev")
    login(client, "root@platform.dev")
    # admin of studio 2 addressed through studio 1's URL -> 404
    assert client.put(f"/api/super-admin/studios/{s1.id}/admins/{a2.id}", json={"name": "x"}).status_code == 404
    assert client.post(f"/api/super-admin/studios/{s1.id}/admins/{a2.id}/disable").status_code == 404
    # the super admin account itself cannot be edited/disabled through a studio URL
    assert client.post(f"/api/super-admin/studios/{s1.id}/admins/{root.id}/disable").status_code == 404
    # studio admins cannot call any of these
    client.post("/api/auth/logout")
    login(client, "a2@s2.dev")
    assert client.put(f"/api/super-admin/studios/{s2.id}/admins/{a2.id}", json={"name": "x"}).status_code == 403
    assert client.post(f"/api/super-admin/studios/{s2.id}/admins/{a2.id}/disable").status_code == 403


def test_a_studio_has_exactly_one_login_and_no_second_can_be_added(client, db_session):
    make_super_admin(db_session)
    login(client, "root@platform.dev")
    sid = _create_studio(client, admin_email="only@acme.dev", admin_password="Only-pass-123").json()["data"]["studio"]["id"]
    body = {"name": "Second", "email": "second@acme.dev", "password": "Second-pass-123"}

    r = client.post(f"/api/super-admin/studios/{sid}/admins", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "STUDIO_USER_LIMIT"
    aid = client.get(f"/api/super-admin/studios/{sid}/admins").json()["data"][0]["id"]
    # a disabled login still counts: it is edited / re-enabled, never replaced by a second one
    assert client.post(f"/api/super-admin/studios/{sid}/admins/{aid}/disable").status_code == 200
    assert client.post(f"/api/super-admin/studios/{sid}/admins", json=body).status_code == 409
    assert len(client.get(f"/api/super-admin/studios/{sid}/admins").json()["data"]) == 1
    # there is no endpoint that deletes the login
    assert client.delete(f"/api/super-admin/studios/{sid}/admins/{aid}").status_code in (404, 405)


def test_a_studio_without_a_login_can_be_given_exactly_one(client, db_session):
    make_super_admin(db_session)
    studio = make_studio(db_session, "Loginless")  # e.g. an old studio created before this rule
    sid = studio.id
    login(client, "root@platform.dev")
    ok = client.post(f"/api/super-admin/studios/{sid}/admins", json={"name": "First", "email": "first@l.dev", "password": "First-pass-123"})
    assert ok.status_code == 200 and ok.json()["data"]["admin"]["email"] == "first@l.dev"
    again = client.post(f"/api/super-admin/studios/{sid}/admins", json={"name": "Two", "email": "two@l.dev", "password": "Two-pass-123"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "STUDIO_USER_LIMIT"


def test_the_database_itself_refuses_a_second_admin_for_one_studio(db_session):
    from sqlalchemy.exc import IntegrityError

    studio = make_studio(db_session, "DB Rule")
    make_admin(db_session, studio, "a@db.dev")
    with pytest.raises(IntegrityError):
        make_admin(db_session, studio, "b@db.dev")
    db_session.rollback()
    # several admins WITHOUT a studio (super admins, unmapped legacy admins) are fine
    make_super_admin(db_session, "s1@platform.dev")
    make_super_admin(db_session, "s2@platform.dev")


def test_delete_studio_requires_suspended_and_no_content(client, db_session):
    make_super_admin(db_session)
    studio = make_studio(db_session, "Doomed")
    make_admin(db_session, studio, "u@doomed.dev")
    sid = studio.id
    login(client, "root@platform.dev")
    url = f"/api/super-admin/studios/{sid}"

    # 1. an active studio cannot be deleted
    r = client.delete(url)
    assert r.status_code == 409 and r.json()["error"]["code"] == "STUDIO_NOT_SUSPENDED"
    assert client.post(url + "/suspend").status_code == 200

    # 2. a studio that still holds a client / files cannot be deleted (and keeps its login)
    from tests.ms_helpers import make_client_album

    make_client_album(db_session, fresh(db_session, Studio, sid))
    r = client.delete(url)
    assert r.status_code == 409 and r.json()["error"]["code"] == "STUDIO_NOT_EMPTY"
    db_session.expire_all()
    assert db_session.get(Studio, sid) is not None
    assert db_session.query(Admin).filter(Admin.studio_id == sid).count() == 1


def test_delete_empty_suspended_studio_removes_it_and_its_logo_and_is_audited(client, db_session, fake_storage):
    make_super_admin(db_session)
    keep = make_studio(db_session, "Keep Me")
    studio = make_studio(db_session, "Delete Me")
    make_admin(db_session, studio, "gone@deleteme.dev")
    make_admin(db_session, keep, "stays@keepme.dev")
    sid, kid = studio.id, keep.id
    login(client, "root@platform.dev")
    assert _upload_logo(client, sid, _png()).status_code == 200
    assert any("/branding/" in k for k in fake_storage.files)
    assert client.post(f"/api/super-admin/studios/{sid}/suspend", json={"reason": "closing"}).status_code == 200

    r = client.delete(f"/api/super-admin/studios/{sid}")
    assert r.status_code == 200 and r.json()["data"] == {"id": sid, "deleted": True}
    db_session.expire_all()
    assert db_session.get(Studio, sid) is None
    assert db_session.get(Studio, kid) is not None  # another studio is untouched
    assert not any("/branding/" in k for k in fake_storage.files)  # logo image removed
    assert db_session.query(Admin).filter(Admin.email == "gone@deleteme.dev").count() == 0  # its single login went with it
    assert db_session.query(Admin).filter(Admin.email == "stays@keepme.dev").count() == 1  # another studio's login stays
    assert db_session.query(Admin).filter(Admin.role == "super_admin").count() == 1  # the super admin is untouched
    assert client.get(f"/api/super-admin/studios/{sid}").status_code == 404
    assert client.delete(f"/api/super-admin/studios/{sid}").status_code == 404
    listed = [s["id"] for s in client.get("/api/super-admin/studios").json()["data"]["items"]]
    assert sid not in listed and kid in listed

    row = db_session.query(AuditLog).filter(AuditLog.action == "studio_deleted").one()
    assert row.resource_id == sid and row.event_metadata["name"] == "Delete Me"
    # earlier history of that studio is kept, just no longer tied to a studio row
    assert db_session.query(AuditLog).filter(AuditLog.action == "studio_suspended").count() == 1


def test_delete_studio_is_super_admin_only(client, db_session):
    make_super_admin(db_session)
    studio = make_studio(db_session, "Mine", status="suspended")
    make_admin(db_session, studio, "owner@mine.dev")
    sid = studio.id
    assert client.delete(f"/api/super-admin/studios/{sid}").status_code == 401
    login(client, "owner@mine.dev")
    assert client.delete(f"/api/super-admin/studios/{sid}").status_code == 403
    db_session.expire_all()
    assert db_session.get(Studio, sid) is not None


# ------------------------------------------------------------------- logo image
def _png(size=(800, 400), color=(180, 133, 59, 255)) -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGBA", size, color).save(out, format="PNG")
    return out.getvalue()


def _upload_logo(client, studio_id, data, name="logo.png", mime="image/png"):
    return client.post(f"/api/super-admin/studios/{studio_id}/logo", files={"file": (name, data, mime)})


def test_super_admin_uploads_replaces_and_removes_a_studio_logo(client, db_session, fake_storage):
    import io

    from PIL import Image

    make_super_admin(db_session)
    studio = make_studio(db_session, "Logo Studio")
    login(client, "root@platform.dev")

    resp = _upload_logo(client, studio.id, _png())
    assert resp.status_code == 200
    url = resp.json()["data"]["logo_url"]
    assert url.startswith(f"/api/studios/{studio.id}/logo?v=")
    keys = [k for k in fake_storage.files if k.startswith(f"studios/{studio.id}/branding/")]
    assert len(keys) == 1

    # Served publicly (no login), as a bounded PNG, cacheable because the URL is versioned.
    client.post("/api/auth/logout")
    got = client.get(url)
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    assert "immutable" in got.headers["cache-control"]
    assert got.headers["x-content-type-options"] == "nosniff"
    img = Image.open(io.BytesIO(got.content))
    assert max(img.size) == 512  # 800x400 shrunk to fit 512

    # Replacing it gives a new URL, serves the new picture and deletes the old object.
    login(client, "root@platform.dev")
    resp2 = _upload_logo(client, studio.id, _png(size=(64, 64), color=(10, 20, 30, 255)))
    url2 = resp2.json()["data"]["logo_url"]
    assert url2 != url
    assert [k for k in fake_storage.files if k.startswith(f"studios/{studio.id}/branding/")] != keys
    assert len([k for k in fake_storage.files if k.startswith(f"studios/{studio.id}/branding/")]) == 1
    assert client.get(url).status_code == 404  # stale version
    assert Image.open(io.BytesIO(client.get(url2).content)).size == (64, 64)

    # Removing clears the column and the object.
    removed = client.delete(f"/api/super-admin/studios/{studio.id}/logo")
    assert removed.status_code == 200 and removed.json()["data"]["logo_url"] is None
    assert not [k for k in fake_storage.files if k.startswith(f"studios/{studio.id}/branding/")]
    assert client.get(url2).status_code == 404
    assert client.delete(f"/api/super-admin/studios/{studio.id}/logo").status_code == 200  # idempotent

    actions = [a.action for a in db_session.query(AuditLog).filter(AuditLog.studio_id == studio.id).all()]
    assert actions.count("studio_logo_updated") == 2 and "studio_logo_removed" in actions


def test_logo_upload_rejects_non_images_oversize_and_unknown_studios(client, db_session):
    make_super_admin(db_session)
    studio = make_studio(db_session)
    login(client, "root@platform.dev")

    for bad in (b"", b"not an image at all", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"):
        r = _upload_logo(client, studio.id, bad)
        assert r.status_code == 400, bad
    assert _upload_logo(client, studio.id, b"x" * (5 * 1024 * 1024 + 10)).status_code == 413
    assert _upload_logo(client, 999_999, _png()).status_code == 404
    assert fresh(db_session, Studio, studio.id).logo_url is None


def test_logo_endpoints_are_super_admin_only_and_missing_logo_is_404(client, db_session):
    studio = make_studio(db_session)
    make_admin(db_session, studio, "owner@studio.dev")
    login(client, "owner@studio.dev")
    assert _upload_logo(client, studio.id, _png()).status_code == 403
    assert client.delete(f"/api/super-admin/studios/{studio.id}/logo").status_code == 403
    client.post("/api/auth/logout")
    assert client.get(f"/api/studios/{studio.id}/logo").status_code == 404
    assert client.get("/api/studios/999999/logo").status_code == 404
