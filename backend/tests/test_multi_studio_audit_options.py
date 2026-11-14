"""Super admin Audit log options: category / actor / search / sort filters, summary, CSV export."""

import csv
import datetime
import io

from app.models.audit_log import AuditLog
from tests.ms_helpers import login, make_admin, make_studio, make_super_admin


def _row(db, action, *, studio=None, user_type="admin", role="studio_admin", ip=None, meta=None, rid=None, uid=None, ago_hours=0):
    r = AuditLog(
        user_type=user_type,
        user_id=uid,
        action=action,
        studio_id=studio.id if studio else None,
        actor_role=role,
        ip_address=ip,
        event_metadata=meta,
        resource_type="media" if action.startswith("media_") else None,
        resource_id=rid,
        created_at=datetime.datetime.utcnow() - datetime.timedelta(hours=ago_hours),
    )
    db.add(r)
    db.commit()
    return r


def _setup(client, db):
    make_super_admin(db)
    assert login(client, "root@platform.dev").status_code == 200
    alpha, beta = make_studio(db, "Alpha Photo"), make_studio(db, "Beta Films")
    _row(db, "admin_login_failed", role=None, ip="10.1.2.3")
    _row(db, "studio_suspended", studio=alpha, role="super_admin")
    _row(db, "studio_admin_password_reset", studio=beta, role="super_admin")
    _row(db, "studio_quota_changed", studio=beta, role="super_admin")
    _row(db, "media_uploaded", studio=alpha, rid=777)
    _row(db, "client_login", studio=alpha, user_type="client", role=None, ago_hours=30)
    _row(db, "media_upload_failed", studio=beta)
    return alpha, beta


def _actions(client, qs):
    d = client.get(f"/api/super-admin/audit-logs?limit=200&{qs}")
    assert d.status_code == 200, d.text
    return [r["action"] for r in d.json()["data"]["items"]]


def test_category_actor_search_and_sort(client, db_session):
    alpha, beta = _setup(client, db_session)
    assert set(_actions(client, "category=sign_in")) >= {"admin_login_failed", "client_login"}
    assert "studio_suspended" not in _actions(client, "category=sign_in")
    assert _actions(client, "category=studios") == ["studio_suspended"]
    assert _actions(client, "category=logins") == ["studio_admin_password_reset"]
    assert _actions(client, "category=storage") == ["studio_quota_changed"]
    content = _actions(client, "category=content")
    assert "media_uploaded" in content and "media_upload_failed" not in content and "client_login" not in content
    assert set(_actions(client, "category=problems")) == {"admin_login_failed"}
    assert client.get("/api/super-admin/audit-logs?category=bogus").status_code == 400

    assert set(_actions(client, "actor=super_admin")) == {"studio_suspended", "studio_admin_password_reset", "studio_quota_changed"} | {
        a for a in _actions(client, "actor=super_admin") if a.startswith("admin_login")  # the root login of this test
    }
    assert _actions(client, "actor=client") == ["client_login"]
    assert client.get("/api/super-admin/audit-logs?actor=nobody").status_code == 400

    assert _actions(client, "search=10.1.2") == ["admin_login_failed"]  # IP
    assert set(_actions(client, "search=alpha")) == {"studio_suspended", "media_uploaded", "client_login"}  # studio name
    assert _actions(client, "search=777") == ["media_uploaded"]  # resource id
    assert _actions(client, "search=%25") == []  # a literal % is not a wildcard

    newest = client.get("/api/super-admin/audit-logs?limit=200&sort=newest").json()["data"]["items"]
    oldest = client.get("/api/super-admin/audit-logs?limit=200&sort=oldest").json()["data"]["items"]
    assert [r["id"] for r in oldest] == [r["id"] for r in reversed(newest)]
    assert client.get("/api/super-admin/audit-logs?sort=sideways").status_code == 422


def test_summary_counts_last_day_and_failed_sign_ins(client, db_session):
    _setup(client, db_session)
    s = client.get("/api/super-admin/audit-logs").json()["data"]["summary"]
    assert s["failed_sign_ins_24h"] == 1
    assert s["events_24h"] >= 6 and s["total"] >= s["events_24h"] + 1  # the 30-hour-old client_login is outside 24h


def test_export_csv_respects_filters_is_formula_safe_and_audited(client, db_session):
    alpha, beta = _setup(client, db_session)
    _row(db_session, "media_uploaded", studio=alpha, meta={"name": "=HYPERLINK(\"x\")"})
    r = client.get("/api/super-admin/audit-logs/export?search=alpha&category=content")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert {x["action"] for x in rows} == {"media_uploaded"} and all(x["studio"] == "Alpha Photo" for x in rows)
    evil = make_studio(db_session, "=SUM(1+1)")
    _row(db_session, "media_deleted", studio=evil)
    cell = list(csv.DictReader(io.StringIO(client.get("/api/super-admin/audit-logs/export?search=SUM").text.lstrip("\ufeff"))))[0]["studio"]
    assert cell == "'=SUM(1+1)"  # a spreadsheet will not run it as a formula
    assert "password" not in r.text.lower()
    log = client.get("/api/super-admin/audit-logs?action=audit_log_exported").json()["data"]["items"]
    assert any(l["metadata"]["rows"] == len(rows) for l in log)
    assert client.get("/api/super-admin/audit-logs/export?from=2026-02-02&to=2026-01-01").status_code == 400


def test_new_options_need_super_admin_and_studio_route_unchanged(client, db_session):
    s = make_studio(db_session, "Studio")
    make_admin(db_session, s, "owner@studio.dev")
    other = make_studio(db_session, "Other")
    _row(db_session, "media_uploaded", studio=other)
    for path in ("/api/super-admin/audit-logs/export", "/api/super-admin/audit-logs?category=sign_in"):
        assert client.get(path).status_code in (401, 403)
    assert login(client, "owner@studio.dev").status_code == 200
    assert client.get("/api/super-admin/audit-logs/export").status_code in (401, 403)
    own = client.get("/api/studio/audit-logs").json()["data"]["items"]  # studio side keeps its hard studio filter
    assert own and all(r["studio_id"] == s.id for r in own)


def test_date_filter_uses_the_viewers_calendar_day(client, db_session):
    """An entry at 20:00 UTC is already "tomorrow" in India (UTC+5:30); `tz_offset` makes from/to local days."""
    make_super_admin(db_session)
    assert login(client, "root@platform.dev").status_code == 200
    studio = make_studio(db_session, "Zone Studio")
    day = datetime.date(2030, 1, 10)
    late = AuditLog(user_type="admin", action="studio_suspended", studio_id=studio.id, actor_role="super_admin",
                    created_at=datetime.datetime(2030, 1, 10, 20, 0))
    early = AuditLog(user_type="admin", action="studio_activated", studio_id=studio.id, actor_role="super_admin",
                     created_at=datetime.datetime(2030, 1, 10, 2, 0))
    db_session.add_all([late, early])
    db_session.commit()
    q = f"from={day}&to={day}&studio_id={studio.id}"
    assert set(_actions(client, q)) == {"studio_suspended", "studio_activated"}  # UTC day
    assert _actions(client, q + "&tz_offset=330") == ["studio_activated"]  # 02:00 UTC = 07:30 IST on the 10th; 20:00 UTC = 01:30 IST on the 11th
    assert _actions(client, f"from={day + datetime.timedelta(days=1)}&to={day + datetime.timedelta(days=1)}&studio_id={studio.id}&tz_offset=330") == ["studio_suspended"]
    assert client.get("/api/super-admin/audit-logs?tz_offset=9999").status_code in (400, 422)
