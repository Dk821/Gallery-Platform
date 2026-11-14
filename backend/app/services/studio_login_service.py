"""
One studio = one studio login. Tools for finding and safely consolidating studios that, from
before this rule, have MORE THAN ONE studio-admin account.

Nothing here deletes anything unless the operator explicitly asks (`action="delete"`); the
default `detach` keeps every account row, disables it, signs it out everywhere and unassigns it
from the studio (it becomes an unmapped legacy admin, which every studio route refuses).
Clients, albums, media and storage objects are never touched.
"""

from __future__ import annotations

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as DbSession

from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.models.upload_session import UploadSession
from app.services import audit_service, quota_service

UNIQUE_INDEX_NAME = "uq_admins_studio_id"
OLD_INDEX_NAME = "ix_admins_studio_id"
ACTIONS = ("detach", "delete")


class ConsolidationError(Exception):
    """Raised before anything is changed when the requested clean-up is not valid."""


def find_duplicates(db: DbSession) -> list[dict]:
    """Studios with more than one admin account, each with its accounts (oldest first)."""
    studio_ids = [
        row[0]
        for row in db.execute(
            select(Admin.studio_id)
            .where(Admin.studio_id.is_not(None))
            .group_by(Admin.studio_id)
            .having(func.count(Admin.id) > 1)
            .order_by(Admin.studio_id)
        )
    ]
    report = []
    for studio_id in studio_ids:
        accounts = []
        for a in db.query(Admin).filter(Admin.studio_id == studio_id).order_by(Admin.created_at, Admin.id):
            last_login = db.execute(
                select(func.max(AuditLog.created_at)).where(
                    AuditLog.user_type == "admin", AuditLog.user_id == a.id, AuditLog.action == "admin_login"
                )
            ).scalar()
            held = db.execute(
                select(func.count(UploadSession.id)).where(
                    UploadSession.admin_id == a.id, UploadSession.reservation_status == "reserved"
                )
            ).scalar()
            accounts.append(
                {
                    "id": a.id,
                    "name": a.name,
                    "email": a.email,
                    "role": a.role,
                    "status": a.status,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "last_login": last_login.isoformat() if last_login else None,
                    "uploads_in_flight": int(held or 0),
                }
            )
        report.append({"studio_id": studio_id, "accounts": accounts})
    return report


def pick_keepers(duplicates: list[dict], keep: dict[int, int] | None, strategy: str | None) -> dict[int, int]:
    """
    Decide which account each duplicated studio keeps. `keep` ({studio_id: admin_id}) always wins;
    `strategy` ("oldest" | "newest") fills in the rest. A studio with no decision is an error:
    this tool never guesses which login is the intended one.
    """
    keep = dict(keep or {})
    chosen: dict[int, int] = {}
    problems = []
    for entry in duplicates:
        sid, ids = entry["studio_id"], [a["id"] for a in entry["accounts"]]
        if sid in keep:
            if keep[sid] not in ids:
                problems.append(f"studio {sid}: account {keep[sid]} does not belong to it (accounts: {ids})")
            else:
                chosen[sid] = keep[sid]
        elif strategy == "oldest":
            chosen[sid] = ids[0]
        elif strategy == "newest":
            chosen[sid] = ids[-1]
        else:
            problems.append(f"studio {sid}: no account chosen to keep (accounts: {ids}); use --keep {sid}:ADMIN_ID")
    for sid in keep:
        if sid not in {e["studio_id"] for e in duplicates}:
            problems.append(f"studio {sid} has no duplicate logins, so --keep {sid}:{keep[sid]} does not apply")
    if problems:
        raise ConsolidationError("; ".join(problems))
    return chosen


def consolidate(db: DbSession, keepers: dict[int, int], *, action: str = "detach") -> list[dict]:
    """
    Applies the decision in ONE transaction. For every account that is not the keeper:
      * its held upload reservations are released (the studio's quota is given back),
      * it is disabled and `session_version` is bumped, so every session/cookie stops working at once,
      * `detach` (default): it is unassigned from the studio, the row is kept;
        `delete`: its upload-session rows and the account row are removed.
    The keeper is left exactly as it is (even if it is disabled - enabling it is a separate, deliberate step).
    """
    if action not in ACTIONS:
        raise ConsolidationError(f"action must be one of {ACTIONS}")
    results = []
    for studio_id, keep_id in keepers.items():
        others = (
            db.query(Admin).filter(Admin.studio_id == studio_id, Admin.id != keep_id).order_by(Admin.id).all()
        )
        handled = []
        for other in others:
            quota_service.release_admin_reservations(db, admin_id=other.id)
            other.status = "disabled"
            other.session_version = int(other.session_version or 0) + 1
            handled.append({"id": other.id, "email": other.email})
            if action == "detach":
                other.studio_id = None
            else:
                db.query(UploadSession).filter(UploadSession.admin_id == other.id).delete(synchronize_session=False)
                db.delete(other)
        audit_service.record(
            db,
            action="studio_login_consolidated",
            user_type="admin",
            user_id=None,
            actor_role="system",
            studio_id=studio_id,
            resource_type="studio",
            resource_id=studio_id,
            metadata={"kept_admin_id": keep_id, "removed_admin_ids": [h["id"] for h in handled], "action": action},
            commit=False,
        )
        results.append({"studio_id": studio_id, "kept": keep_id, "action": action, "handled": handled})
    db.commit()
    return results


def _ops(conn) -> Operations:
    return Operations(MigrationContext.configure(conn))


def drop_unique_index(engine: Engine) -> None:
    """Removes the unique index and restores the plain one (used by tests and by a manual downgrade)."""
    with engine.begin() as conn:
        names = {ix["name"] for ix in inspect(conn).get_indexes("admins")}
        ops = _ops(conn)
        if OLD_INDEX_NAME not in names:
            ops.create_index(OLD_INDEX_NAME, "admins", ["studio_id"], unique=False)
        if UNIQUE_INDEX_NAME in names:
            ops.drop_index(UNIQUE_INDEX_NAME, table_name="admins")


def ensure_unique_index(engine: Engine) -> str:
    """
    Makes the database enforce one login per studio. Returns "created", "exists" or
    "blocked" (some studio still has more than one account, so it cannot be created yet).
    """
    names = {ix["name"] for ix in inspect(engine).get_indexes("admins")}
    if UNIQUE_INDEX_NAME in names:
        return "exists"
    with DbSession(engine) as db:
        if find_duplicates(db):
            return "blocked"
    with engine.begin() as conn:
        ops = _ops(conn)
        # Created BEFORE the old index is dropped: MySQL needs an index on the foreign-key column at all times.
        ops.create_index(UNIQUE_INDEX_NAME, "admins", ["studio_id"], unique=True)
        if OLD_INDEX_NAME in names:
            ops.drop_index(OLD_INDEX_NAME, table_name="admins")
    return "created"
