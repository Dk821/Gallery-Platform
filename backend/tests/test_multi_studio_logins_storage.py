"""Super admin sidebar pages: 'Studio logins' (GET /logins) and 'Storage' (GET/POST /storage/reconcile)."""

from app.models.admin import Admin
from tests.ms_helpers import fresh, login, make_admin, make_studio, make_super_admin


def _sa(client, db):
    make_super_admin(db)
    assert login(client, "root@platform.dev").status_code == 200


def test_logins_list_states_search_and_last_signin(client, db_session):
    alpha, beta, gamma = (make_studio(db_session, n) for n in ("Alpha Studio", "Beta Studio", "Gamma Studio"))
    make_admin(db_session, alpha, "owner@alpha.dev")
    off = make_admin(db_session, beta, "owner@beta.dev")
    off.status = "disabled"
    db_session.commit()  # Gamma has no login at all
    # Alpha's owner signs in once -> last sign-in comes from the audit trail
    assert login(client, "owner@alpha.dev").status_code == 200
    client.post("/api/auth/logout")
    _sa(client, db_session)

    d = client.get("/api/super-admin/logins?limit=200").json()["data"]
    rows = {r["studio_name"]: r for r in d["items"]}
    assert rows["Alpha Studio"]["login"]["email"] == "owner@alpha.dev" and rows["Alpha Studio"]["login"]["last_login"]
    assert rows["Beta Studio"]["login"]["status"] == "disabled" and rows["Beta Studio"]["login"]["last_login"] is None
    assert rows["Gamma Studio"]["login"] is None
    assert "password_hash" not in str(d) and "session_version" not in str(d)  # no secrets
    assert d["summary"]["none"] >= 1 and d["summary"]["disabled"] == 1 and d["summary"]["active"] >= 1

    names = lambda q: {r["studio_name"] for r in client.get(f"/api/super-admin/logins?{q}&limit=200").json()["data"]["items"]}  # noqa: E731
    assert names("state=disabled") == {"Beta Studio"}
    assert "Gamma Studio" in names("state=none") and "Alpha Studio" not in names("state=none")
    assert names("state=active") >= {"Alpha Studio"} and "Beta Studio" not in names("state=active")
    assert names("search=owner@beta") == {"Beta Studio"}
    assert names("search=gamma") == {"Gamma Studio"}
    assert client.get("/api/super-admin/logins?state=bogus").status_code == 400


def test_logins_and_storage_require_super_admin(client, db_session):
    s = make_studio(db_session, "Studio")
    make_admin(db_session, s, "owner@studio.dev")
    for path in ("/api/super-admin/logins", "/api/super-admin/storage/reconcile"):
        assert client.get(path).status_code in (401, 403)
    assert login(client, "owner@studio.dev").status_code == 200
    assert client.get("/api/super-admin/logins").status_code in (401, 403)
    assert client.get("/api/super-admin/storage/reconcile").status_code in (401, 403)
    assert client.post("/api/super-admin/storage/reconcile").status_code in (401, 403)


def test_storage_check_reports_drift_and_repair_fixes_it_and_is_audited(client, db_session):
    from tests.ms_helpers import make_client_album, make_media

    s = make_studio(db_session, "Drifty", quota=10_000_000, used=0)
    c, a = make_client_album(db_session, s)
    make_media(db_session, s, c, a, size=3000)
    make_media(db_session, s, c, a, size=2000)  # real rows = 5000 bytes, counter says 0
    ok = make_studio(db_session, "Fine", quota=10_000_000, used=0)
    _sa(client, db_session)

    r = client.get("/api/super-admin/storage/reconcile").json()["data"]
    assert r["applied"] is False and r["studios_out_of_sync"] >= 1
    flagged = {x["name"]: x for x in r["studios"]}
    assert flagged["Drifty"]["used_drift_bytes"] == -5000 and flagged["Drifty"]["actual_used_bytes"] == 5000
    assert "Fine" not in flagged  # in sync -> not listed
    assert fresh(db_session, type(s), s.id).used_bytes == 0  # the check changed nothing

    fixed = client.post("/api/super-admin/storage/reconcile").json()["data"]
    assert fixed["applied"] is True and fixed["studios_out_of_sync"] == 0 and "Drifty" not in {x["name"] for x in fixed["studios"]}
    db_session.expire_all()
    assert int(fresh(db_session, type(s), s.id).used_bytes) == 5000
    assert client.get("/api/super-admin/storage/reconcile").json()["data"]["studios_out_of_sync"] == 0

    log = client.get("/api/super-admin/audit-logs?limit=20").json()["data"]["items"]
    assert any(row["action"] == "storage_counters_repaired" for row in log)
    assert ok.id  # untouched
