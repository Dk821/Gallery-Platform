"""
Storage quota accounting for the multi-studio platform.

Two ceilings are enforced for every upload:

  1. the studio's own `quota_bytes`            (set by a super admin)
  2. the platform's `platform_capacity_bytes`  (configuration, see settings)

Three numbers are tracked separately, on the studio row and on the single
`platform_storage` row:

  used      - bytes of verified, stored media
  reserved  - bytes promised to uploads still in flight
  remaining - derived: quota - used - reserved (never stored)

CONCURRENCY. Nothing here does read-modify-write in Python. Every change is a
conditional single-statement UPDATE whose WHERE clause carries the limit
check, e.g.

    UPDATE studios SET reserved_bytes = reserved_bytes + :n
    WHERE id = :id AND status = 'active'
      AND used_bytes + reserved_bytes + :n <= quota_bytes

The database applies it atomically under a row lock, so two uploads racing
for the last few bytes cannot both succeed. The platform check is a second
conditional UPDATE on the single platform row, which also serialises
reservations from different studios. Both run in ONE transaction: if either
fails the whole reservation rolls back.

STATE MACHINE (UploadSession.reservation_status), each edge a compare-and-set:

    none/released --reserve--> reserved --commit--> committed
                                   \\--release--> released

A duplicate completion, duplicate abandon or a retry therefore cannot apply an
edge twice: the second UPDATE matches zero rows and is a no-op.

None of these functions commit on success (the caller commits together with the
rest of its unit of work, e.g. the Media row), except `reserve`, which commits
because a reservation must be durable before storage is touched.

Thumbnails are not counted: Media.file_size is the original object only
(documented in docs/MULTI_STUDIO.md).
"""

import logging
import time

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session as DbSession

from app.config.settings import get_settings
from app.models.platform_storage import PlatformStorage
from app.models.studio import Studio
from app.models.upload_session import UploadSession
from app.schemas.errors import ApiError

logger = logging.getLogger("gallery.quota")

PLATFORM_ROW_ID = 1


class ReservationStateError(Exception):
    """The reservation was not in the state this operation requires (already committed/released)."""


def _clamped_sub(column, n: int):
    # used/reserved can never go below zero, even if an operator has been
    # editing rows by hand: GREATEST() is MySQL-only, CASE is portable.
    return case((column >= n, column - n), else_=0)


def ensure_platform_row(db: DbSession) -> None:
    """Creates the single platform_storage row if it doesn't exist yet (lazy, like StudioSettings)."""
    exists = db.execute(select(PlatformStorage.id).where(PlatformStorage.id == PLATFORM_ROW_ID)).first()
    if exists is not None:
        return
    try:
        db.add(PlatformStorage(id=PLATFORM_ROW_ID, used_bytes=0, reserved_bytes=0))
        db.commit()
    except Exception:  # noqa: BLE001 - another request created it first
        db.rollback()


_PROVIDER_CACHE_TTL_SECONDS = 300
_provider_cache: dict = {"at": 0.0, "value": None}


def get_provider_limit() -> dict | None:
    """
    Real storage limit/usage reported by the storage provider (Google Drive
    only), cached for a few minutes. Display-only: never used for enforcement.
    Returns None when unavailable or not applicable.
    """
    settings = get_settings()
    if (settings.storage_provider or "google_drive").strip().lower() != "google_drive":
        return None
    if not settings.google_drive_refresh_token:
        return None
    now = time.monotonic()
    if _provider_cache["at"] and now - _provider_cache["at"] < _PROVIDER_CACHE_TTL_SECONDS:
        return _provider_cache["value"]
    value = None
    try:
        from app.services.storage_provider import get_storage_service

        meta = get_storage_service().get_metadata()
        if meta.get("available") and meta.get("limit_bytes"):
            value = {"limit_bytes": int(meta["limit_bytes"]), "usage_bytes": int(meta.get("usage_bytes") or 0)}
    except Exception as exc:  # noqa: BLE001 - display-only, never break the dashboard
        logger.warning("Could not read provider storage limit: %s", exc)
    _provider_cache.update(at=now, value=value)
    return value


def get_platform_usage(db: DbSession) -> dict:
    ensure_platform_row(db)
    provider = get_provider_limit()
    capacity = get_settings().platform_capacity_bytes
    row = db.execute(
        select(PlatformStorage.used_bytes, PlatformStorage.reserved_bytes).where(
            PlatformStorage.id == PLATFORM_ROW_ID
        )
    ).one()
    used, reserved = int(row.used_bytes), int(row.reserved_bytes)
    allocated = int(db.execute(select(func.coalesce(func.sum(Studio.quota_bytes), 0))).scalar_one())
    return {
        "capacity_bytes": capacity,
        "provider_limit_bytes": provider["limit_bytes"] if provider else None,
        "provider_usage_bytes": provider["usage_bytes"] if provider else None,
        "used_bytes": used,
        "reserved_bytes": reserved,
        "remaining_bytes": max(capacity - used - reserved, 0),
        # Sum of studio quotas. May exceed capacity on purpose (overselling);
        # the platform ceiling above is what actually stops uploads.
        "allocated_quota_bytes": allocated,
    }


def studio_usage(studio: Studio) -> dict:
    used, reserved, quota = int(studio.used_bytes), int(studio.reserved_bytes), int(studio.quota_bytes)
    return {
        "quota_bytes": quota,
        "used_bytes": used,
        "reserved_bytes": reserved,
        "remaining_bytes": max(quota - used - reserved, 0),
    }


def _raise_for_failed_studio_reservation(db: DbSession, studio_id: int, nbytes: int) -> None:
    studio = db.get(Studio, studio_id)
    if studio is None:
        raise ApiError(404, "STUDIO_NOT_FOUND", "Studio not found.")
    if studio.status != "active":
        raise ApiError(403, "STUDIO_SUSPENDED", "This studio is suspended.")
    usage = studio_usage(studio)
    raise ApiError(
        413,
        "STUDIO_QUOTA_EXCEEDED",
        f"This upload ({nbytes} bytes) exceeds the studio's storage quota "
        f"({usage['remaining_bytes']} bytes remaining).",
    )


def reserve(db: DbSession, session: UploadSession, studio_id: int, nbytes: int) -> None:
    """
    Atomically reserve `nbytes` against the studio quota AND platform capacity
    for `session`. Commits on success. Raises ApiError (413/507/403) and leaves
    NO partial reservation on failure. Idempotent: reserving a session that
    already holds a reservation is a no-op.
    """
    if nbytes <= 0:
        raise ApiError(400, "INVALID_SIZE", "Upload size must be greater than zero.")
    ensure_platform_row(db)
    capacity = get_settings().platform_capacity_bytes
    session_id = session.id

    # 1) Claim the reservation slot on the ledger row (compare-and-set).
    claimed = db.execute(
        update(UploadSession)
        .where(UploadSession.id == session_id, UploadSession.reservation_status.in_(("none", "released")))
        .values(reserved_bytes=nbytes, reservation_status="reserved", studio_id=studio_id)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.rollback()
        return  # already reserved (duplicate/concurrent start) or committed - nothing to do

    # 2) Studio ceiling.
    res = db.execute(
        update(Studio)
        .where(
            Studio.id == studio_id,
            Studio.status == "active",
            Studio.used_bytes + Studio.reserved_bytes + nbytes <= Studio.quota_bytes,
        )
        .values(reserved_bytes=Studio.reserved_bytes + nbytes)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        db.rollback()
        _raise_for_failed_studio_reservation(db, studio_id, nbytes)

    # 3) Platform ceiling (capacity comes from config, compared in SQL).
    res = db.execute(
        update(PlatformStorage)
        .where(
            PlatformStorage.id == PLATFORM_ROW_ID,
            PlatformStorage.used_bytes + PlatformStorage.reserved_bytes + nbytes <= capacity,
        )
        .values(reserved_bytes=PlatformStorage.reserved_bytes + nbytes)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        db.rollback()  # also undoes the studio reservation above
        raise ApiError(
            507,
            "PLATFORM_CAPACITY_EXCEEDED",
            "The platform has no capacity left for this upload. Please contact support.",
        )

    db.commit()
    db.expire_all()


def release(db: DbSession, session_id: int) -> int:
    """
    Release a held reservation (upload failed / cancelled / abandoned / stale).
    Does NOT commit. Returns the number of bytes released (0 if there was
    nothing to release - e.g. already released or already committed).
    """
    row = db.execute(
        select(UploadSession.reserved_bytes, UploadSession.studio_id).where(UploadSession.id == session_id)
    ).first()
    if row is None:
        return 0
    n, studio_id = int(row.reserved_bytes or 0), row.studio_id

    claimed = db.execute(
        update(UploadSession)
        .where(UploadSession.id == session_id, UploadSession.reservation_status == "reserved")
        .values(reservation_status="released")
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1 or n <= 0 or studio_id is None:
        return 0

    db.execute(
        update(Studio)
        .where(Studio.id == studio_id)
        .values(reserved_bytes=_clamped_sub(Studio.reserved_bytes, n))
        .execution_options(synchronize_session=False)
    )
    db.execute(
        update(PlatformStorage)
        .where(PlatformStorage.id == PLATFORM_ROW_ID)
        .values(reserved_bytes=_clamped_sub(PlatformStorage.reserved_bytes, n))
        .execution_options(synchronize_session=False)
    )
    return n


def release_admin_reservations(db: DbSession, *, admin_id: int) -> int:
    """
    Releases every held reservation for upload sessions started by one admin.
    Used right before that admin (and so, via the FK cascade, their
    upload_sessions rows) is deleted, so reserved bytes don't leak.
    Does NOT commit.
    """
    ids = [
        row.id
        for row in db.execute(
            select(UploadSession.id).where(
                UploadSession.admin_id == admin_id, UploadSession.reservation_status == "reserved"
            )
        )
    ]
    for session_id in ids:
        release(db, session_id)
    return len(ids)


def commit_reservation(db: DbSession, session: UploadSession, actual_bytes: int) -> None:
    """
    Convert a reservation into real usage after the object was VERIFIED in
    storage: reserved -= r, used += actual (the provider-reported size, never
    the browser's claim). Does NOT commit - call it in the same transaction as
    the Media insert so usage and media rows can never disagree.

    If the real object is larger than what was reserved, the difference is
    reserved on the spot under the same limit checks; if that is refused the
    transaction is rolled back (the reservation stays 'reserved' so the caller
    can fail the session and release it) and the quota error is raised.

    Raises ReservationStateError if the reservation was already committed or
    released (duplicate completion): the caller must roll back and not create
    a second Media row.
    """
    session_id = session.id
    row = db.execute(
        select(UploadSession.reserved_bytes, UploadSession.studio_id).where(UploadSession.id == session_id)
    ).first()
    if row is None or row.studio_id is None:
        raise ReservationStateError("upload session has no studio reservation")
    r, studio_id = int(row.reserved_bytes or 0), int(row.studio_id)
    delta = actual_bytes - r
    capacity = get_settings().platform_capacity_bytes

    claimed = db.execute(
        update(UploadSession)
        .where(UploadSession.id == session_id, UploadSession.reservation_status == "reserved")
        .values(reservation_status="committed", reserved_bytes=actual_bytes)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        raise ReservationStateError("reservation is not in the 'reserved' state")

    studio_where = [Studio.id == studio_id]
    platform_where = [PlatformStorage.id == PLATFORM_ROW_ID]
    if delta > 0:
        studio_where += [Studio.used_bytes + Studio.reserved_bytes + delta <= Studio.quota_bytes]
        platform_where += [PlatformStorage.used_bytes + PlatformStorage.reserved_bytes + delta <= capacity]

    res = db.execute(
        update(Studio)
        .where(*studio_where)
        .values(
            reserved_bytes=_clamped_sub(Studio.reserved_bytes, r),
            used_bytes=Studio.used_bytes + actual_bytes,
        )
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        db.rollback()
        raise ApiError(
            413,
            "STUDIO_QUOTA_EXCEEDED",
            "The uploaded file is larger than the size declared at the start of the upload and "
            "does not fit in the studio's remaining storage.",
        )
    res = db.execute(
        update(PlatformStorage)
        .where(*platform_where)
        .values(
            reserved_bytes=_clamped_sub(PlatformStorage.reserved_bytes, r),
            used_bytes=PlatformStorage.used_bytes + actual_bytes,
        )
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        db.rollback()
        raise ApiError(
            507,
            "PLATFORM_CAPACITY_EXCEEDED",
            "The platform has no capacity left for this upload. Please contact support.",
        )


def decrease_used(db: DbSession, studio_id: int | None, nbytes: int) -> None:
    """
    Give back usage after media was successfully deleted from storage. Does
    NOT commit (same transaction as the row deletion). `studio_id=None`
    (legacy, unmapped media) is not tracked and is ignored.
    """
    if studio_id is None or nbytes <= 0:
        return
    db.execute(
        update(Studio)
        .where(Studio.id == studio_id)
        .values(used_bytes=_clamped_sub(Studio.used_bytes, nbytes))
        .execution_options(synchronize_session=False)
    )
    ensure_platform_row(db)
    db.execute(
        update(PlatformStorage)
        .where(PlatformStorage.id == PLATFORM_ROW_ID)
        .values(used_bytes=_clamped_sub(PlatformStorage.used_bytes, nbytes))
        .execution_options(synchronize_session=False)
    )


def release_orphaned_reservations(db: DbSession) -> int:
    """
    Releases reservations still 'reserved' on sessions that are already
    terminal (failed/cancelled). Runs at startup after the stale-session sweep
    and from the reconciliation command, so a crash between "mark failed" and
    "release" can never leak reserved bytes forever. Commits. Returns the
    number of reservations released.
    """
    ids = [
        row.id
        for row in db.execute(
            select(UploadSession.id).where(
                UploadSession.reservation_status == "reserved",
                UploadSession.status.in_(("failed", "cancelled")),
            )
        )
    ]
    for session_id in ids:
        release(db, session_id)
    if ids:
        db.commit()
    return len(ids)


def release_reserved_sessions(db: DbSession, *, album_ids: list[int]) -> int:
    """
    Releases every held reservation for upload sessions of the given albums.
    Used right before an album/client (and so its upload_sessions rows) is
    deleted, so the reserved bytes don't leak. Does NOT commit.
    """
    if not album_ids:
        return 0
    ids = [
        row.id
        for row in db.execute(
            select(UploadSession.id).where(
                UploadSession.album_id.in_(album_ids), UploadSession.reservation_status == "reserved"
            )
        )
    ]
    for session_id in ids:
        release(db, session_id)
    return len(ids)
