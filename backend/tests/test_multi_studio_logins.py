"""One studio = one studio login: cleaning up studios that already have several, and the guards around it."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.models.upload_session import UploadSession
from app.services import legacy_mapping, quota_service
from app.services import studio_login_service as svc
from tests.ms_helpers import fresh, login, make_admin, make_client_album, make_media, make_studio, make_super_admin


def _allow_duplicates(db):
    """Recreate the state of an install that predates the rule (no unique index yet)."""
    db.commit()
    svc.drop_unique_index(db.get_bind())


@pytest.fixture()
def legacy_dupes(db_session):
    """Studio with three logins (oldest, middle, newest), another studio with one, and a super admin."""
    _allow_duplicates(db_session)
    studio = make_studio(db_session, "Many Logins")
    other = make_studio(db_session, "One Login")
    a1 = make_admin(db_session, studio, "old@many.dev")
    a2 = make_admin(db_session, studio, "mid@many.dev")
    a3 = make_admin(db_session, studio, "new@many.dev")
    solo = make_admin(db_session, other, "solo@one.dev")
    root = make_super_admin(db_session)
    return {"studio": studio.id, "other": other.id, "ids": [a1.id, a2.id, a3.id], "solo": solo.id, "root": root.id}


def test_report_lists_only_studios_with_several_logins(db_session, legacy_dupes):
    report = svc.find_duplicates(db_session)
    assert [r["studio_id"] for r in report] == [legacy_dupes["studio"]]
    assert [a["id"] for a in report[0]["accounts"]] == legacy_dupes["ids"]
    assert {"email", "status", "created_at", "last_login", "uploads_in_flight"} <= set(report[0]["accounts"][0])


def test_the_tool_never_guesses_which_login_is_the_intended_one(db_session, legacy_dupes):
    dupes = svc.find_duplicates(db_session)
    sid, ids = legacy_dupes["studio"], legacy_dupes["ids"]
    with pytest.raises(svc.ConsolidationError, match="no account chosen"):
        svc.pick_keepers(dupes, None, None)
    with pytest.raises(svc.ConsolidationError, match="does not belong"):
        svc.pick_keepers(dupes, {sid: legacy_dupes["solo"]}, None)  # another studio's account
    with pytest.raises(svc.ConsolidationError, match="no duplicate logins"):
        svc.pick_keepers(dupes, {sid: ids[1], legacy_dupes["other"]: legacy_dupes["solo"]}, None)
    assert svc.pick_keepers(dupes, {sid: ids[1]}, None) == {sid: ids[1]}
    assert svc.pick_keepers(dupes, None, "oldest") == {sid: ids[0]}
    assert svc.pick_keepers(dupes, None, "newest") == {sid: ids[2]}


def test_database_rule_cannot_be_added_while_duplicates_exist(db_session, legacy_dupes):
    assert svc.ensure_unique_index(db_session.get_bind()) == "blocked"


def test_consolidate_keeps_the_chosen_login_revokes_the_others_and_touches_no_data(client, db_session, legacy_dupes):
    sid, (old, mid, new) = legacy_dupes["studio"], legacy_dupes["ids"]
    studio = fresh(db_session, type(make_studio(db_session, "tmp")), sid)
    cl, album = make_client_album(db_session, studio)
    make_media(db_session, studio, cl, album, size=700)
    counts_before = {
        "clients": db_session.query(type(cl)).filter_by(studio_id=sid).count(),
        "media": db_session.query(type(make_media(db_session, studio, cl, album, size=1))).filter_by(studio_id=sid).count(),
    }

    # the middle account is signed in and has an upload in flight holding 500 bytes
    mid_client = client.__class__(client.app)
    assert login(mid_client, "mid@many.dev").status_code == 200 and mid_client.get("/api/admin/settings").status_code == 200
    sess = UploadSession(upload_id="u-mid", admin_id=mid, album_id=album.id, filename="x", studio_id=sid, status="uploading")
    db_session.add(sess)
    db_session.commit()
    quota_service.reserve(db_session, sess, sid, 500)
    db_session.commit()
    assert fresh(db_session, type(studio), sid).reserved_bytes == 500

    keep_client = client.__class__(client.app)
    assert login(keep_client, "new@many.dev").status_code == 200

    done = svc.consolidate(db_session, {sid: new})
    db_session.expire_all()
    assert done[0]["kept"] == new and sorted(h["id"] for h in done[0]["handled"]) == [old, mid]

    keeper = db_session.get(Admin, new)
    assert keeper.studio_id == sid and keeper.status == "active"  # exactly as before
    for gone_id in (old, mid):
        row = db_session.get(Admin, gone_id)
        assert row is not None  # nothing deleted
        assert row.studio_id is None and row.status == "disabled" and row.session_version == 1
    # their sessions stop working immediately; the kept login's session still works
    assert mid_client.get("/api/admin/settings").status_code == 401
    assert login(client.__class__(client.app), "mid@many.dev").status_code == 401
    assert keep_client.get("/api/admin/settings").status_code == 200
    # the detached accounts cannot use any studio route even if they were enabled again (no studio)
    # held reservation is given back; data untouched
    assert fresh(db_session, type(studio), sid).reserved_bytes == 0
    assert db_session.get(UploadSession, sess.id).reservation_status == "released"
    assert db_session.query(type(cl)).filter_by(studio_id=sid).count() == counts_before["clients"]
    assert db_session.query(type(make_media(db_session, studio, cl, album, size=1))).filter_by(studio_id=sid).count() == counts_before["media"] + 1
    # another studio's login and the super admin are untouched
    assert db_session.get(Admin, legacy_dupes["solo"]).studio_id == legacy_dupes["other"]
    assert db_session.get(Admin, legacy_dupes["root"]).role == "super_admin"
    # audited, without account secrets
    row = db_session.query(AuditLog).filter(AuditLog.action == "studio_login_consolidated").one()
    assert row.studio_id == sid and row.event_metadata["kept_admin_id"] == new
    # now clean: the database rule can be (and is) created, and then enforced
    assert svc.find_duplicates(db_session) == []
    assert svc.ensure_unique_index(db_session.get_bind()) == "created"
    assert svc.ensure_unique_index(db_session.get_bind()) == "exists"
    with pytest.raises(IntegrityError):
        make_admin(db_session, fresh(db_session, type(studio), sid), "extra@many.dev")
    db_session.rollback()


def test_consolidate_delete_action_removes_only_the_other_accounts(db_session, legacy_dupes):
    sid, (old, mid, new) = legacy_dupes["studio"], legacy_dupes["ids"]
    svc.consolidate(db_session, {sid: old}, action="delete")
    db_session.expire_all()
    assert db_session.get(Admin, old) is not None
    assert db_session.get(Admin, mid) is None and db_session.get(Admin, new) is None
    assert db_session.get(Admin, legacy_dupes["solo"]) is not None


def test_consolidate_rejects_an_unknown_action(db_session, legacy_dupes):
    with pytest.raises(svc.ConsolidationError):
        svc.consolidate(db_session, {legacy_dupes["studio"]: legacy_dupes["ids"][0]}, action="wipe")


def test_legacy_mapping_refuses_to_give_a_studio_a_second_login(db_session):
    studio = make_studio(db_session, "Mapped")
    make_admin(db_session, studio, "already@mapped.dev")
    legacy = make_admin(db_session, make_studio(db_session, "Elsewhere"), "legacy@old.dev")
    legacy.studio_id = None  # a genuinely unmapped legacy admin
    db_session.commit()
    with pytest.raises(legacy_mapping.LegacyMappingError, match="only one login"):
        legacy_mapping.map_legacy_to_studio(db_session, studio.id, apply=False)
    db_session.rollback()
    # an EMPTY studio may receive exactly one
    empty = make_studio(db_session, "Empty")
    plan = legacy_mapping.map_legacy_to_studio(db_session, empty.id, apply=True)
    assert plan["admins"] == 1
    db_session.commit()
    assert db_session.get(Admin, legacy.id).studio_id == empty.id
