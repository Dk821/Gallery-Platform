"""
Quota reconciliation: compares the counters kept on `studios` /
`platform_storage` with what the database and the storage provider actually
hold, reports drift, and (only with apply=True) repairs it.

Why drift can exist at all: counters are updated by conditional UPDATEs inside
the same transactions as the rows they describe, so they should always agree.
This is the safety net for everything outside that - a crash between storage
and DB, manual SQL, a bug, an operator restoring a backup, or media that
existed before quota tracking was introduced.

Sources of truth
  used_bytes      = SUM(media.file_size)                      per studio
  reserved_bytes  = SUM(upload_sessions.reserved_bytes)       for reservation_status = 'reserved'
  platform totals = SUM over studios

Object verification (optional, makes provider calls) compares each media row's
recorded size with the size the provider reports.

Safe to re-run any number of times (idempotent). The repair statements are
single UPDATEs with correlated subqueries, so each counter is rewritten from
the current rows in one atomic statement.
"""

import datetime
import logging

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session as DbSession

from app.config.settings import get_settings
from app.models.media import Media
from app.models.platform_storage import PlatformStorage
from app.models.studio import Studio
from app.models.upload_session import UploadSession
from app.services import quota_service
from app.services.storage_service import StorageError, StorageNotFoundError, StorageService

logger = logging.getLogger("gallery.quota.reconcile")


def _actual_used(db: DbSession) -> dict[int, int]:
    rows = db.execute(
        select(Media.studio_id, func.coalesce(func.sum(Media.file_size), 0))
        .where(Media.studio_id.isnot(None))
        .group_by(Media.studio_id)
    ).all()
    return {int(sid): int(total) for sid, total in rows}


def _actual_reserved(db: DbSession) -> dict[int, int]:
    rows = db.execute(
        select(UploadSession.studio_id, func.coalesce(func.sum(UploadSession.reserved_bytes), 0))
        .where(UploadSession.studio_id.isnot(None), UploadSession.reservation_status == "reserved")
        .group_by(UploadSession.studio_id)
    ).all()
    return {int(sid): int(total) for sid, total in rows}


def release_stale_reservations(db: DbSession, *, apply: bool) -> dict:
    """
    Reservations that will never convert: the session is terminal
    (failed/cancelled) but still holds bytes, or it has sat in
    queued/uploading for longer than UPLOAD_RESERVATION_TTL_MINUTES.
    """
    ttl = get_settings().upload_reservation_ttl_minutes
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=ttl)
    terminal = [
        r.id
        for r in db.execute(
            select(UploadSession.id).where(
                UploadSession.reservation_status == "reserved",
                UploadSession.status.in_(("failed", "cancelled")),
            )
        )
    ]
    expired = [
        r.id
        for r in db.execute(
            select(UploadSession.id).where(
                UploadSession.reservation_status == "reserved",
                UploadSession.status.in_(("queued", "uploading")),
                UploadSession.updated_at < cutoff,
            )
        )
    ]
    if apply:
        for session_id in terminal + expired:
            quota_service.release(db, session_id)
        for session_id in expired:
            db.execute(
                update(UploadSession)
                .where(UploadSession.id == session_id, UploadSession.status.in_(("queued", "uploading")))
                .values(
                    status="failed",
                    error_code="UPLOAD_RESERVATION_EXPIRED",
                    error_message="The upload did not finish before its storage reservation expired.",
                )
                .execution_options(synchronize_session=False)
            )
        db.commit()
    return {"terminal_sessions": len(terminal), "expired_sessions": len(expired), "applied": apply}


def reconcile_quota(db: DbSession, *, apply: bool = False, studio_id: int | None = None) -> dict:
    """Returns a per-studio drift report; with apply=True also repairs the counters."""
    quota_service.ensure_platform_row(db)
    stale = release_stale_reservations(db, apply=apply)

    used = _actual_used(db)
    reserved = _actual_reserved(db)
    query = select(Studio)
    if studio_id is not None:
        query = query.where(Studio.id == studio_id)
    studios = db.execute(query).scalars().all()

    report = []
    for studio in studios:
        want_used, want_reserved = used.get(studio.id, 0), reserved.get(studio.id, 0)
        drift_used = int(studio.used_bytes) - want_used
        drift_reserved = int(studio.reserved_bytes) - want_reserved
        report.append(
            {
                "studio_id": studio.id,
                "name": studio.name,
                "recorded_used_bytes": int(studio.used_bytes),
                "actual_used_bytes": want_used,
                "recorded_reserved_bytes": int(studio.reserved_bytes),
                "actual_reserved_bytes": want_reserved,
                "quota_bytes": int(studio.quota_bytes),
                "used_drift_bytes": drift_used,
                "reserved_drift_bytes": drift_reserved,
                "over_quota": want_used + want_reserved > int(studio.quota_bytes),
                "in_sync": drift_used == 0 and drift_reserved == 0,
            }
        )

    if apply:
        for row in report:
            if row["in_sync"]:
                continue
            db.execute(
                text(
                    "UPDATE studios SET "
                    "used_bytes = (SELECT COALESCE(SUM(file_size), 0) FROM media WHERE media.studio_id = studios.id), "
                    "reserved_bytes = (SELECT COALESCE(SUM(reserved_bytes), 0) FROM upload_sessions "
                    "WHERE upload_sessions.studio_id = studios.id AND upload_sessions.reservation_status = 'reserved') "
                    "WHERE id = :id"
                ),
                {"id": row["studio_id"]},
            )
            logger.warning(
                "Quota counters repaired for studio %s (used drift %s, reserved drift %s).",
                row["studio_id"],
                row["used_drift_bytes"],
                row["reserved_drift_bytes"],
            )
        # The platform row is always rewritten from the studio rows - the
        # studio-level repair above may have changed them.
        db.execute(
            text(
                "UPDATE platform_storage SET "
                "used_bytes = (SELECT COALESCE(SUM(used_bytes), 0) FROM studios), "
                "reserved_bytes = (SELECT COALESCE(SUM(reserved_bytes), 0) FROM studios) "
                "WHERE id = :pid"
            ),
            {"pid": quota_service.PLATFORM_ROW_ID},
        )
        db.commit()

    platform = db.execute(
        select(PlatformStorage.used_bytes, PlatformStorage.reserved_bytes).where(
            PlatformStorage.id == quota_service.PLATFORM_ROW_ID
        )
    ).one()
    sum_used = int(db.execute(select(func.coalesce(func.sum(Studio.used_bytes), 0))).scalar_one())
    sum_reserved = int(db.execute(select(func.coalesce(func.sum(Studio.reserved_bytes), 0))).scalar_one())
    return {
        "applied": apply,
        "stale_reservations": stale,
        "studios": report,
        "studios_out_of_sync": sum(1 for r in report if not r["in_sync"]),
        "platform": {
            "recorded_used_bytes": int(platform.used_bytes),
            "recorded_reserved_bytes": int(platform.reserved_bytes),
            "sum_of_studios_used_bytes": sum_used,
            "sum_of_studios_reserved_bytes": sum_reserved,
            "in_sync": int(platform.used_bytes) == sum_used and int(platform.reserved_bytes) == sum_reserved,
            "capacity_bytes": get_settings().platform_capacity_bytes,
        },
    }


def verify_objects(
    db: DbSession, storage: StorageService, *, studio_id: int | None = None, limit: int = 1000
) -> dict:
    """
    Compares Media.file_size with the size the PROVIDER reports for the same
    object. Report-only: a mismatch needs a human decision (which side is
    right?). Where a provider cannot report sizes, rows are counted as unverified.
    """
    query = select(Media).order_by(Media.id.asc()).limit(limit)
    if studio_id is not None:
        query = query.where(Media.studio_id == studio_id)
    checked = mismatched = missing = errors = 0
    problems: list[dict] = []
    for media in db.execute(query).scalars():
        checked += 1
        try:
            stored = storage.get_file(media.google_drive_file_id)
        except StorageNotFoundError:
            missing += 1
            problems.append({"media_id": media.id, "studio_id": media.studio_id, "problem": "missing_in_storage"})
            continue
        except StorageError:
            errors += 1
            continue
        if stored.size and int(stored.size) != int(media.file_size):
            mismatched += 1
            problems.append(
                {
                    "media_id": media.id,
                    "studio_id": media.studio_id,
                    "problem": "size_mismatch",
                    "recorded_bytes": int(media.file_size),
                    "storage_bytes": int(stored.size),
                }
            )
    return {
        "checked": checked,
        "mismatched": mismatched,
        "missing_in_storage": missing,
        "storage_errors": errors,
        "problems": problems[:200],
    }
