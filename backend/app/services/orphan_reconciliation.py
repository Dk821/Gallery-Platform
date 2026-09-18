"""
Finds and (optionally) cleans up Drive files that were successfully
uploaded but never got a matching Media row - e.g. the VPS process died
between "Drive accepted the file" and "we saved the DB record" (Section 9).

Detection doesn't rely on filenames or on listing everything in the whole
Drive account: `complete_direct_upload` durably records drive_file_id on
the UploadSession row (and commits it) the moment it learns the browser's
direct-to-Drive upload succeeded, before the Media row is created. That
ledger IS the "application-managed" record - an UploadSession that:
  - has a drive_file_id (so a Drive file really was created for it), and
  - never reached status="completed" (so no Media row was ever finalized
    for it), and
  - is older than the configured grace period (so we're not racing a
    request that's still legitimately in flight)
is a candidate orphan. Before actually deleting anything we re-check
against Media once more (a completion could have landed between the
candidate query and now), so a slow-but-still-succeeding upload is never
mistaken for one that's truly abandoned.

KNOWN GAP (direct browser -> Drive upload architecture): this ledger only
gains a drive_file_id once the browser calls POST /upload-complete after
its direct PUT to Drive finishes. If the browser's tab is closed/crashes
in the narrow window AFTER Drive has fully accepted the file but BEFORE
that finalize call reaches this server, the file exists in Drive with no
UploadSession.drive_file_id ever recorded for it - this scan will never
find it, since it only looks at rows that already have one. Such a file
is still tagged with appProperties (gallery_managed / gallery_upload_id)
at session-creation time (see GoogleDriveStorage.create_resumable_session),
so a future enhancement here would be to ALSO list Drive directly by that
appProperty and cross-reference against UploadSession.upload_id, rather
than relying solely on this table. Not implemented yet.
"""

import datetime
import logging

from sqlalchemy.orm import Session as DbSession

from app.models.media import Media
from app.models.upload_session import UploadSession
from app.services.storage_service import StorageError, StorageService
from app.services.upload_logging import log_event

logger = logging.getLogger("gallery.storage.orphan_reconciliation")


def find_orphan_candidates(db: DbSession, grace_period_hours: int) -> list[UploadSession]:
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=grace_period_hours)
    return (
        db.query(UploadSession)
        .filter(
            UploadSession.drive_file_id.isnot(None),
            UploadSession.status != "completed",
            UploadSession.created_at < cutoff,
        )
        .all()
    )


def count_orphan_candidates(db: DbSession, grace_period_hours: int) -> int:
    """
    Same query as find_orphan_candidates(), just a count instead of full
    rows - cheap enough (DB-only, no Drive API calls) to include in every
    admin Storage page load, so "N orphaned files found" is visible
    without an admin having to remember to run the reconcile action.
    """
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=grace_period_hours)
    return (
        db.query(UploadSession)
        .filter(
            UploadSession.drive_file_id.isnot(None),
            UploadSession.status != "completed",
            UploadSession.created_at < cutoff,
        )
        .count()
    )


def reconcile_orphans(
    db: DbSession, storage: StorageService, grace_period_hours: int, *, dry_run: bool = True
) -> dict:
    """
    Returns a summary dict: {"candidates": n, "confirmed": [...], "deleted": [...], "still_valid": [...]}.
    Never deletes anything when dry_run=True (the default) - candidates are
    only logged, exactly as Section 9 requires ("do not immediately
    delete").
    """
    candidates = find_orphan_candidates(db, grace_period_hours)
    confirmed: list[str] = []
    still_valid: list[str] = []
    deleted: list[str] = []
    cleanup_failed: list[str] = []

    for session in candidates:
        # Re-check immediately before acting: a Media row referencing this
        # exact Drive file id may have been created since the candidate
        # query ran (e.g. a slow request that was still legitimately
        # finishing).
        still_referenced = (
            db.query(Media.id).filter(Media.google_drive_file_id == session.drive_file_id).first()
        )
        if still_referenced is not None:
            still_valid.append(session.drive_file_id)
            continue

        confirmed.append(session.drive_file_id)
        log_event(
            logger,
            "upload_orphan_detected",
            level=logging.WARNING,
            upload_id=session.upload_id,
            drive_file_id_present=True,
            status=session.status,
            age_hours=round(
                (datetime.datetime.utcnow() - session.created_at).total_seconds() / 3600, 1
            ),
        )

        if dry_run:
            continue

        try:
            storage.delete(session.drive_file_id)
            if session.thumbnail_drive_file_id:
                storage.delete(session.thumbnail_drive_file_id)
            session.status = "cancelled"
            session.error_code = "ORPHAN_CLEANED_UP"
            session.error_message = "Drive file had no matching database record after the grace period."
            db.commit()
            deleted.append(session.drive_file_id)
            log_event(logger, "upload_reconciled", upload_id=session.upload_id, outcome="deleted")
        except StorageError as exc:
            db.rollback()
            cleanup_failed.append(session.drive_file_id)
            logger.critical(
                "Failed to clean up confirmed orphan Drive file for upload_id=%s: %s. "
                "Manual reconciliation required.",
                session.upload_id,
                exc,
            )

    return {
        "candidates": len(candidates),
        "confirmed": confirmed,
        "still_valid": still_valid,
        "deleted": deleted,
        "cleanup_failed": cleanup_failed,
        "dry_run": dry_run,
    }
