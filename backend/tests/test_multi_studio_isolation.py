"""Tenant isolation: a studio admin / client must never reach another studio's data (IDOR)."""

import pytest

from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.media import Media
from tests.ms_helpers import (
    fresh, login, make_admin, make_client_album, make_media, make_studio, start_upload,
)


@pytest.fixture()
def two_studios(db_session, client):
    a, b = make_studio(db_session, "Studio A"), make_studio(db_session, "Studio B")
    make_admin(db_session, a, "a@a.dev")
    make_admin(db_session, b, "b@b.dev")
    ca, ala = make_client_album(db_session, a, "A")
    cb, alb = make_client_album(db_session, b, "B")
    ma = make_media(db_session, a, ca, ala)
    mb = make_media(db_session, b, cb, alb)
    assert login(client, "a@a.dev").status_code == 200
    return {"a": a, "b": b, "ca": ca, "ala": ala, "ma": ma, "cb": cb, "alb": alb, "mb": mb}


def _is_hidden(resp):
    return resp.status_code == 404


def test_lists_only_return_own_studio_rows(client, two_studios):
    ids = [c["id"] for c in client.get("/api/admin/clients").json()["data"]["items"]]
    assert ids == [two_studios["ca"].id]
    albums = client.get("/api/admin/albums").json()["data"]["items"]
    assert [a["id"] for a in albums] == [two_studios["ala"].id]


def test_foreign_client_endpoints_are_404(client, two_studios):
    cid = two_studios["cb"].id
    for method, path, body in [
        ("get", f"/api/admin/clients/{cid}", None),
        ("put", f"/api/admin/clients/{cid}", {"client_name": "hijacked"}),
        ("delete", f"/api/admin/clients/{cid}", None),
        ("get", f"/api/admin/clients/{cid}/passwords", None),
        ("post", f"/api/admin/clients/{cid}/disable", None),
        ("post", f"/api/admin/clients/{cid}/enable", None),
        ("post", f"/api/admin/clients/{cid}/regenerate-gallery-id", None),
        ("post", f"/api/admin/clients/{cid}/change-password", {"new_password": "whatever-123"}),
    ]:
        kwargs = {"json": body} if body is not None else {}
        resp = getattr(client, method)(path, **kwargs)
        assert _is_hidden(resp), (method, path, resp.status_code)


def test_foreign_album_endpoints_are_404(client, two_studios):
    aid = two_studios["alb"].id
    for method, path, body in [
        ("get", f"/api/admin/albums/{aid}", None),
        ("get", f"/api/admin/albums/{aid}/media", None),
        ("put", f"/api/admin/albums/{aid}", {"album_name": "hijacked"}),
        ("delete", f"/api/admin/albums/{aid}", None),
        ("get", f"/api/admin/albums/{aid}/comments", None),
        ("post", f"/api/admin/albums/{aid}/download-jobs", {}),
    ]:
        kwargs = {"json": body} if body is not None else {}
        resp = getattr(client, method)(path, **kwargs)
        assert _is_hidden(resp), (method, path, resp.status_code)


def test_foreign_media_endpoints_are_404(client, two_studios):
    mid = two_studios["mb"].id
    for method, path, body in [
        ("get", f"/api/admin/media/{mid}", None),
        ("patch", f"/api/admin/media/{mid}", {"file_name": "x.jpg"}),
        ("delete", f"/api/admin/media/{mid}", None),
        ("get", f"/api/admin/media/{mid}/thumbnail", None),
        ("get", f"/api/admin/media/{mid}/view", None),
        ("get", f"/api/admin/media/{mid}/download", None),
        ("post", f"/api/admin/media/{mid}/move", {"target_album_id": two_studios["ala"].id}),
    ]:
        kwargs = {"json": body} if body is not None else {}
        resp = getattr(client, method)(path, **kwargs)
        assert _is_hidden(resp), (method, path, resp.status_code)


def test_cannot_move_own_media_into_foreign_album(client, db_session, two_studios):
    resp = client.post(
        f"/api/admin/media/{two_studios['ma'].id}/move", json={"target_album_id": two_studios["alb"].id}
    )
    assert _is_hidden(resp)
    assert fresh(db_session, Media, two_studios["ma"].id).album_id == two_studios["ala"].id


def test_cannot_create_album_for_foreign_client(client, two_studios):
    resp = client.post("/api/admin/albums", json={"client_id": two_studios["cb"].id, "album_name": "x"})
    assert resp.status_code in (404, 400, 403), resp.status_code
    assert resp.status_code == 404


def test_bulk_operations_skip_foreign_ids_and_never_touch_them(client, db_session, two_studios):
    mine, theirs = two_studios["ma"].id, two_studios["mb"].id
    resp = client.post("/api/admin/media/bulk-delete", json={"media_ids": [theirs]})
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] == []
    assert fresh(db_session, Media, theirs) is not None

    resp = client.post(
        "/api/admin/media/bulk-move", json={"media_ids": [theirs], "target_album_id": two_studios["ala"].id}
    )
    assert resp.status_code == 200 and resp.json()["data"]["moved"] == []
    assert fresh(db_session, Media, theirs).album_id == two_studios["alb"].id
    assert fresh(db_session, Media, mine) is not None


def test_bulk_move_into_foreign_target_album_is_404(client, two_studios):
    resp = client.post(
        "/api/admin/media/bulk-move",
        json={"media_ids": [two_studios["ma"].id], "target_album_id": two_studios["alb"].id},
    )
    assert _is_hidden(resp)


def test_cannot_start_upload_into_foreign_album(client, db_session, two_studios):
    resp = start_upload(client, two_studios["alb"].id, "11111111-1111-4111-8111-111111111111", 100)
    assert _is_hidden(resp)
    assert fresh(db_session, type(two_studios["b"]), two_studios["b"].id).reserved_bytes == 0


def test_studio_id_supplied_by_the_caller_is_ignored(client, db_session, two_studios):
    resp = client.post(
        "/api/admin/clients",
        json={"client_name": "New Client", "studio_id": two_studios["b"].id},
    )
    assert resp.status_code == 200
    row = db_session.get(Client, resp.json()["data"]["id"])
    assert row.studio_id == two_studios["a"].id
    # query-string studio_id is not an accepted filter either
    ids = [c["id"] for c in client.get("/api/admin/clients", params={"studio_id": two_studios["b"].id}).json()["data"]["items"]]
    assert two_studios["cb"].id not in ids


def test_dashboard_and_storage_are_scoped(client, two_studios):
    dash = client.get("/api/admin/dashboard").json()["data"]
    assert dash["total_clients"] == 1 and dash["total_photos"] == 1
    assert dash["storage_used_bytes"] == two_studios["ma"].file_size
    assert dash["studio_quota"]["quota_bytes"] == two_studios["a"].quota_bytes


def test_studio_audit_logs_only_show_own_studio(client, db_session, two_studios):
    db_session.add(AuditLog(user_type="admin", user_id=999, action="secret_b_action", studio_id=two_studios["b"].id))
    db_session.add(AuditLog(user_type="admin", user_id=1, action="mine", studio_id=two_studios["a"].id))
    db_session.commit()
    items = client.get("/api/studio/audit-logs").json()["data"]["items"]
    actions = {i["action"] for i in items}
    assert "mine" in actions and "secret_b_action" not in actions


def test_unmapped_legacy_admin_is_locked_out_until_mapped(client, db_session):
    studio = make_studio(db_session)
    admin = make_admin(db_session, studio, "legacy@x.dev")
    admin.studio_id = None
    db_session.commit()
    login(client, "legacy@x.dev")
    resp = client.get("/api/admin/clients")
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "STUDIO_NOT_ASSIGNED"


# ----- clients (gallery visitors) -------------------------------------------------

def _client_login(test_client, c):
    return test_client.post("/api/auth/client/login", json={"gallery_id": c.client_uuid, "password": "client-pass-1"})


def test_client_only_sees_own_albums_and_media(client, db_session):
    a, b = make_studio(db_session, "A"), make_studio(db_session, "B")
    ca, ala = make_client_album(db_session, a)
    cb, alb = make_client_album(db_session, b)
    ma, mb = make_media(db_session, a, ca, ala), make_media(db_session, b, cb, alb)
    assert _client_login(client, ca).status_code == 200
    assert [x["id"] for x in client.get("/api/client/albums").json()["data"]["items"]] == [ala.id]
    assert client.get(f"/api/client/albums/{alb.id}").status_code in (403, 404)  # existing contract: 403 for a foreign gallery
    assert client.get(f"/api/client/media/{mb.id}").status_code in (403, 404)  # existing contract: 403 for a foreign gallery
    assert client.get(f"/api/client/media/{mb.id}/download").status_code in (403, 404)  # existing contract: 403 for a foreign gallery
    assert client.get(f"/api/client/media/{ma.id}").status_code == 200


def test_clients_of_a_suspended_studio_cannot_log_in_or_keep_sessions(client, db_session):
    s = make_studio(db_session)
    c, album = make_client_album(db_session, s)
    assert _client_login(client, c).status_code == 200
    assert client.get("/api/client/albums").status_code == 200
    s.status = "suspended"
    db_session.commit()
    assert client.get("/api/client/albums").status_code in (401, 403)
    client.cookies.clear()
    assert _client_login(client, c).status_code == 401
    s.status = "active"
    db_session.commit()
    assert _client_login(client, c).status_code == 200


def test_client_session_cannot_call_admin_or_super_admin_routes(client, db_session):
    s = make_studio(db_session)
    c, _ = make_client_album(db_session, s)
    _client_login(client, c)
    assert client.get("/api/admin/clients").status_code == 401
    assert client.get("/api/super-admin/studios").status_code == 401


# ----- suspension -----------------------------------------------------------------

def test_suspended_studio_blocks_writes_but_allows_reads(client, db_session, two_studios):
    two_studios["a"].status = "suspended"
    db_session.commit()
    assert client.get("/api/admin/clients").status_code == 200
    assert client.get("/api/admin/dashboard").status_code == 200
    for method, path, body in [
        ("post", "/api/admin/clients", {"client_name": "New"}),
        ("post", "/api/admin/albums", {"client_id": two_studios["ca"].id, "album_name": "x"}),
        ("delete", f"/api/admin/media/{two_studios['ma'].id}", None),
        ("put", "/api/studio/profile", {"name": "x"}),
    ]:
        kwargs = {"json": body} if body is not None else {}
        resp = getattr(client, method)(path, **kwargs)
        assert resp.status_code == 403 and resp.json()["error"]["code"] == "STUDIO_SUSPENDED", (method, path)
    resp = start_upload(client, two_studios["ala"].id, "22222222-2222-4222-8222-222222222222", 100)
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "STUDIO_SUSPENDED"
    assert fresh(db_session, Media, two_studios["ma"].id) is not None
