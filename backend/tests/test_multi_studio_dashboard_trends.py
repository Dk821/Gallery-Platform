"""Super admin dashboard analytics: GET /api/super-admin/stats/trends."""

import datetime

from tests.ms_helpers import PASSWORD, login, make_client_album, make_media, make_studio, make_super_admin


def _sa(client, db):
    make_super_admin(db)
    assert login(client, "root@platform.dev").status_code == 200


def test_trends_shape_and_totals(client, db_session):
    _sa(client, db_session)
    a, b = make_studio(db_session, "Alpha"), make_studio(db_session, "Beta")
    ca, al = make_client_album(db_session, a)
    cb, bl = make_client_album(db_session, b)
    make_media(db_session, a, ca, al, size=4000)
    m = make_media(db_session, a, ca, al, size=1000, name="v.mp4")
    m.file_type, m.mime_type = "video", "video/mp4"
    old = make_media(db_session, b, cb, bl, size=500)
    old.created_at = datetime.datetime.utcnow() - datetime.timedelta(days=45)  # previous 30-day window
    db_session.commit()

    r = client.get("/api/super-admin/stats/trends?days=30")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["range_days"] == 30 and len(d["series"]) == 30
    assert d["series"][-1]["date"] == datetime.datetime.utcnow().strftime("%Y-%m-%d")
    assert d["totals"]["media"] == 2 and d["totals"]["uploaded_bytes"] == 5000
    assert d["previous_totals"]["media"] == 1 and d["previous_totals"]["uploaded_bytes"] == 500
    assert d["totals"]["studios"] >= 2 and d["totals"]["clients"] == 2  # (the test shim also seeds a default studio)
    assert d["media_types"]["photo"]["files"] == 2 and d["media_types"]["video"]["files"] == 1
    assert d["most_active_studios"][0]["name"] == "Alpha" and d["most_active_studios"][0]["uploaded_bytes"] == 5000
    assert sum(p["media"] for p in d["series"]) == 2


def test_trends_range_is_clamped_and_requires_super_admin(client, db_session):
    s = make_studio(db_session, "Studio")
    assert client.get("/api/super-admin/stats/trends").status_code in (401, 403)
    from tests.ms_helpers import make_admin

    make_admin(db_session, s, "owner@studio.dev")
    assert login(client, "owner@studio.dev").status_code == 200
    assert client.get("/api/super-admin/stats/trends").status_code in (401, 403)  # studio admin is not a super admin
    client.post("/api/auth/logout")
    _sa(client, db_session)
    for asked, got in ((7, 7), (90, 90), (13, 30), (-5, 30)):
        assert client.get(f"/api/super-admin/stats/trends?days={asked}").json()["data"]["range_days"] == got
