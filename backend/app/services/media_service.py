import datetime
import io
import logging
import time
import uuid
from typing import BinaryIO

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.config.settings import Settings, get_settings
from app.models.album import Album
from app.models.client import Client
from app.models.media import Media
from app.models.upload_session import UploadSession
from app.schemas.errors import ApiError, bad_request, forbidden, not_found
from app.schemas.media import MediaUpdateRequest
from app.schemas.pagination import paginate_params
from app.services.album_service import check_album_not_expired
from app.services.disk_service import InsufficientDiskSpaceError, get_disk_tracker
from app.services.media_validation import validate_upload
from app.services.storage_service import StorageError, StorageNotFoundError, StorageService, StorageTimeoutError
from app.services.upload_concurrency import UploadQueueTimeoutError, get_upload_limiter
from app.services.upload_logging import log_event
from app.workers.thumbnail_worker import generate_image_thumbnail, generate_video_poster

logger = logging.getLogger("gallery.media")


def _not_expired_clause():
    # A fresh clause per call, NOT a module-level constant - datetime.utcnow()
    # must be evaluated at query time, not once at import/server-startup time.
    return or_(Album.expires_at.is_(None), Album.expires_at > datetime.datetime.utcnow())


def get_media_for_client_or_403(db: DbSession, media_id: int, client_id: int) -> Media:
    # Same pattern as get_album_for_client_or_403: ownership mismatch and
    # "doesn't exist" are indistinguishable to the caller.
    media = db.query(Media).filter(Media.id == media_id).first()
    if media is None or media.client_id != client_id:
        raise forbidden("You do not have access to this media item.", code="MEDIA_FORBIDDEN")
    # A media item inherits its album's expiry - without this check, a
    # client could bypass an expired album entirely just by hitting
    # /media/{id} directly with an id they'd already seen before expiry.
    if media.album is not None:
        check_album_not_expired(media.album)
    return media


def get_media_or_404(db: DbSession, media_id: int) -> Media:
    media = db.query(Media).filter(Media.id == media_id).first()
    if media is None:
        raise not_found("Media not found.", code="MEDIA_NOT_FOUND")
    return media


def list_media_for_client(
    db: DbSession, client_id: int, album_id: int | None, page: int, limit: int, search: str | None = None
):
    page, limit = paginate_params(page, limit)

    query = db.query(Media).join(Album, Media.album_id == Album.id).filter(Media.client_id == client_id)
    if album_id is not None:
        query = query.filter(Media.album_id == album_id)
    else:
        # No specific album requested (e.g. a cross-album "Find My Photos"
        # search) - exclude expired albums' media. When album_id IS given,
        # get_album_for_client_or_403 already enforced expiry for the whole
        # album before this function is ever called, so this filter would
        # be redundant (but harmless) there.
        query = query.filter(_not_expired_clause())
    if search:
        # Filename-only search (Part 3): case-insensitive, partial match,
        # against stored metadata - never opens/downloads a file just to
        # check its name.
        query = query.filter(Media.file_name.ilike(f"%{search.strip()}%"))
    query = query.order_by(Media.created_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return rows, total, page, limit


def get_media_selection_summary(
    db: DbSession, client_id: int, album_id: int | None, search: str | None = None
) -> dict:
    """
    Backs "Select All" (Part 4) and the size estimate (Part 7) without ever
    fetching full metadata for every matching row - just id + file_size,
    which stays cheap even for a gallery with tens of thousands of items
    (Section 13: avoid N+1s and avoid pulling more than what's needed).
    """
    query = (
        db.query(Media.id, Media.file_size)
        .join(Album, Media.album_id == Album.id)
        .filter(Media.client_id == client_id)
    )
    if album_id is not None:
        query = query.filter(Media.album_id == album_id)
    else:
        query = query.filter(_not_expired_clause())
    if search:
        query = query.filter(Media.file_name.ilike(f"%{search.strip()}%"))

    rows = query.all()
    ids = [r[0] for r in rows]
    total_bytes = sum(r[1] for r in rows)
    return {"ids": ids, "total_count": len(ids), "total_bytes": total_bytes}


def list_media_for_album_admin(
    db: DbSession, album_id: int, page: int, limit: int, search: str | None = None
):
    """
    Admin-facing equivalent of list_media_for_client, but scoped by album_id
    directly rather than by an authenticated client - the caller
    (api/admin_albums.py) is responsible for confirming the album itself
    exists via get_album_or_404 before calling this.
    """
    page, limit = paginate_params(page, limit)

    query = db.query(Media).filter(Media.album_id == album_id)
    if search:
        # .ilike() compiles to a case-insensitive comparison on every
        # dialect we target (SQLite in tests, MySQL in production), not
        # just Postgres-native ILIKE.
        query = query.filter(Media.file_name.ilike(f"%{search.strip()}%"))
    query = query.order_by(Media.created_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return rows, total, page, limit


def get_album_media_selection_summary(db: DbSession, album_id: int, search: str | None = None) -> dict:
    """
    Admin equivalent of get_media_selection_summary - backs "Select All"
    on the admin media grid so it selects every matching item across all
    pages, not just what's currently loaded (same id+size-only query shape,
    no full-metadata fetch for the whole album).
    """
    query = db.query(Media.id, Media.file_size).filter(Media.album_id == album_id)
    if search:
        query = query.filter(Media.file_name.ilike(f"%{search.strip()}%"))
    rows = query.all()
    ids = [r[0] for r in rows]
    total_bytes = sum(r[1] for r in rows)
    return {"ids": ids, "total_count": len(ids), "total_bytes": total_bytes}


def update_media_metadata(db: DbSession, media: Media, payload: MediaUpdateRequest) -> Media:
    if payload.file_name is not None:
        media.file_name = payload.file_name
    if payload.title is not None:
        media.title = payload.title
    if payload.description is not None:
        media.description = payload.description
    db.commit()
    db.refresh(media)
    return media


def move_media_to_album(db: DbSession, storage: StorageService, media: Media, target_album: Album) -> Media:
    """
    Reassigns a media item to a different album belonging to the SAME
    client, moving the underlying Drive file(s) via StorageService.move_file
    (a metadata-only operation at the provider - no re-upload). Follows the
    same "storage first, DB second, roll back storage on DB failure"
    reconciliation pattern used everywhere else in this file.
    """
    if target_album.client_id != media.client_id:
        # Never allow moving media across clients, regardless of what the
        # request body says - this is checked here, not just in the UI.
        raise bad_request(
            "Cannot move media to a different client's album.", code="CROSS_CLIENT_MOVE_NOT_ALLOWED"
        )

    if target_album.id == media.album_id:
        return media  # already there - idempotent no-op, not an error

    if not target_album.drive_folder_id:
        raise ApiError(
            409, "ALBUM_STORAGE_NOT_PROVISIONED", "Target album has no storage folder. Recreate the album."
        )

    old_album = db.query(Album).filter(Album.id == media.album_id).first()
    old_folder_id = old_album.drive_folder_id if old_album else None

    moved_thumbnail = False
    try:
        storage.move_file(media.google_drive_file_id, target_album.drive_folder_id, old_folder_id)
        if media.thumbnail_reference:
            storage.move_file(media.thumbnail_reference, target_album.drive_folder_id, old_folder_id)
            moved_thumbnail = True
    except StorageError as exc:
        logger.error("Failed to move media %s to album %s: %s", media.id, target_album.id, exc)
        raise ApiError(502, "STORAGE_MOVE_FAILED", "Could not move the file in storage. Please retry.")

    previous_album_id = media.album_id
    media.album_id = target_album.id
    try:
        db.commit()
        db.refresh(media)
    except Exception:
        db.rollback()
        logger.critical(
            "DB update failed after moving Drive file(s) for media %s from album %s to %s. "
            "Attempting to move the file(s) back.",
            media.id,
            previous_album_id,
            target_album.id,
        )
        try:
            storage.move_file(media.google_drive_file_id, old_folder_id, target_album.drive_folder_id)
            if moved_thumbnail:
                storage.move_file(media.thumbnail_reference, old_folder_id, target_album.drive_folder_id)
            logger.info("Rolled back Drive move for media %s after DB failure.", media.id)
        except StorageError as rollback_exc:
            logger.critical(
                "FAILED to roll back Drive move for media %s - manual reconciliation required "
                "(file may now be in album %s's folder while DB still points at album %s): %s",
                media.id,
                target_album.id,
                previous_album_id,
                rollback_exc,
            )
        raise ApiError(
            500, "MEDIA_MOVE_SAVE_FAILED", "Move succeeded in storage but saving the record failed. Please retry."
        )

    return media


UPLOAD_ID_MAX_LENGTH = 100  # must match UploadSession.upload_id's String(100) column


def _reserve_upload_session(
    db: DbSession, admin_id: int | None, upload_id: str, album: Album, filename: str, file_size: int
) -> tuple[UploadSession, Media | None]:
    """
    Implements the idempotency rules from Section 4:
      - first request                       -> new row, proceed
      - duplicate while uploading            -> 409, do not proceed
      - retry after timeout / lost response / server error, when the
        previous attempt failed              -> reuse the row, proceed
      - duplicate after successful completion -> return the SAME Media,
        no re-upload, no new DB row
      - two identical requests arriving simultaneously -> the DB's unique
        constraint on (admin_id, upload_id) lets exactly one insert win;
        the other treats the race as "already in progress"
    Returns (session, existing_media_or_None). A non-None second element
    means the caller should return that Media immediately without
    touching storage again.
    """
    # Validated here, not just trusted from the client: upload_id is
    # client-minted (see the module docstring on UploadSession), and a
    # value longer than the DB column previously reached db.commit()
    # unchecked - MySQL's strict mode then raised a raw DataError mid-flush
    # (1406 "Data too long for column 'upload_id'"), surfacing as an ugly
    # 500 with a full SQLAlchemy traceback instead of a clean 400. This is
    # exactly what happens if a client embeds a long filename directly
    # into the id it mints (the actual frontend bug that triggered this -
    # fixed there too, but this check is the backend's own safety net
    # regardless of what any client sends).
    if not upload_id or len(upload_id) > UPLOAD_ID_MAX_LENGTH:
        raise ApiError(
            400,
            "INVALID_UPLOAD_ID",
            f"upload_id must be 1-{UPLOAD_ID_MAX_LENGTH} characters (got {len(upload_id)}).",
        )

    session = (
        db.query(UploadSession)
        .filter(UploadSession.admin_id == admin_id, UploadSession.upload_id == upload_id)
        .first()
    )

    if session is not None:
        if session.status == "completed" and session.media_id:
            media = db.query(Media).filter(Media.id == session.media_id).first()
            if media is not None:
                log_event(logger, "upload_completed", upload_id=upload_id, note="idempotent_replay")
                return session, media
            # Session says completed but the Media row is gone (e.g.
            # deleted since) - fall through and treat as a fresh retry.
        if session.status == "uploading":
            raise ApiError(
                409, "UPLOAD_ALREADY_IN_PROGRESS", "This upload is already being processed. Please wait."
            )
        session.album_id = album.id
        session.filename = filename
        session.total_bytes = file_size
        session.bytes_uploaded = 0
        session.status = "uploading"
        session.error_code = None
        session.error_message = None
        db.commit()
        return session, None

    session = UploadSession(
        upload_id=upload_id,
        admin_id=admin_id,
        album_id=album.id,
        filename=filename,
        total_bytes=file_size,
        bytes_uploaded=0,
        status="uploading",
    )
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(UploadSession)
            .filter(UploadSession.admin_id == admin_id, UploadSession.upload_id == upload_id)
            .first()
        )
        if existing is not None and existing.status == "completed" and existing.media_id:
            media = db.query(Media).filter(Media.id == existing.media_id).first()
            if media is not None:
                return existing, media
        raise ApiError(
            409, "UPLOAD_ALREADY_IN_PROGRESS", "This upload is already being processed. Please wait."
        )
    db.refresh(session)
    log_event(logger, "upload_started", upload_id=upload_id, album_id=album.id, filename=filename, file_size=file_size)
    return session, None


def create_upload_session(
    db: DbSession, admin_id: int | None, upload_id: str, album_id: int, filename: str, file_size: int
) -> UploadSession:
    """
    Pre-creates an UploadSession with status='queued' before the actual
    file upload begins (POST /upload-session).  This eliminates the race
    condition where the frontend starts polling /upload-status before
    FastAPI has finished buffering the large multipart body and the
    handler has created the session.

    The session stays 'queued' until upload_media_to_album() picks it up
    via _reserve_upload_session() and flips it to 'uploading'.  Creating
    it as 'uploading' here would cause _reserve_upload_session() to
    reject it as a duplicate (409 UPLOAD_ALREADY_IN_PROGRESS).
    """
    if not upload_id or len(upload_id) > UPLOAD_ID_MAX_LENGTH:
        raise ApiError(
            400,
            "INVALID_UPLOAD_ID",
            f"upload_id must be 1-{UPLOAD_ID_MAX_LENGTH} characters (got {len(upload_id)}).",
        )

    session = (
        db.query(UploadSession)
        .filter(UploadSession.admin_id == admin_id, UploadSession.upload_id == upload_id)
        .first()
    )

    if session is not None:
        if session.status == "completed" and session.media_id:
            # Already finished — return it so the caller can short-circuit
            # (the idempotent-replay path in upload_media_to_album).
            return session
        if session.status in ("uploading", "queued"):
            raise ApiError(
                409,
                "UPLOAD_ALREADY_IN_PROGRESS",
                "This upload is already being processed. Please wait.",
            )
        # Failed / cancelled — reset for retry.
        session.album_id = album_id
        session.filename = filename
        session.total_bytes = file_size
        session.bytes_uploaded = 0
        session.status = "queued"
        session.error_code = None
        session.error_message = None
        db.commit()
        db.refresh(session)
        log_event(
            logger,
            "upload_session_created",
            upload_id=upload_id,
            album_id=album_id,
            filename=filename,
            file_size=file_size,
        )
        return session

    session = UploadSession(
        upload_id=upload_id,
        admin_id=admin_id,
        album_id=album_id,
        filename=filename,
        total_bytes=file_size,
        bytes_uploaded=0,
        status="queued",
    )
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(UploadSession)
            .filter(UploadSession.admin_id == admin_id, UploadSession.upload_id == upload_id)
            .first()
        )
        if existing is not None:
            return existing
        raise ApiError(
            409, "UPLOAD_IN_PROGRESS", "This upload is already being processed."
        )
    db.refresh(session)
    log_event(
        logger,
        "upload_session_created",
        upload_id=upload_id,
        album_id=album_id,
        filename=filename,
        file_size=file_size,
    )
    return session


def _fail_upload_session(db: DbSession, session: UploadSession, code: str, message: str) -> None:
    try:
        session.status = "failed"
        session.error_code = code
        session.error_message = message[:2000]
        db.commit()
    except Exception:  # noqa: BLE001 - never let bookkeeping failure mask the real error
        db.rollback()
        logger.error("Failed to persist failure state for upload_id=%s", session.upload_id)
    log_event(logger, "upload_failed", upload_id=session.upload_id, error_code=code)


def _make_progress_updater(db: DbSession, session: UploadSession):
    state = {"last_commit": 0.0}

    def _update(bytes_uploaded: int, total_bytes: int) -> None:
        now = time.monotonic()
        is_final = total_bytes > 0 and bytes_uploaded >= total_bytes
        # Throttle DB writes to roughly once a second (plus always on the
        # final chunk) - a multi-GB upload can have hundreds of chunks and
        # committing on every single one would be wasteful.
        if not is_final and now - state["last_commit"] < 1.0:
            return
        state["last_commit"] = now
        session.bytes_uploaded = min(bytes_uploaded, total_bytes) if total_bytes else bytes_uploaded
        try:
            db.commit()
        except Exception:  # noqa: BLE001 - progress reporting must never break the upload itself
            db.rollback()
        log_event(
            logger,
            "upload_progress",
            upload_id=session.upload_id,
            bytes_uploaded=bytes_uploaded,
            total_bytes=total_bytes,
        )

    return _update


def _db_utcnow(db: DbSession) -> datetime.datetime:
    # updated_at is written by func.now() using the DATABASE server's own
    # clock/timezone, NOT Python's. Computing staleness cutoffs in Python
    # (datetime.utcnow()) and comparing them against those rows mixes two
    # separate clocks - on a server in +5:30/+8 timezone the rows look
    # hours "in the future" and a dead session is never detected (the
    # frontend polls it forever). Always measure "now" from the same clock
    # that stamps the rows.
    value = db.execute(select(func.now())).scalar_one()
    if isinstance(value, str):
        # SQLite's CURRENT_TIMESTAMP comes back as text; MySQL returns a
        # bound datetime. Normalize to a datetime for arithmetic.
        value = datetime.datetime.fromisoformat(value)
    return value


def _fail_stale_upload_sessions(db: DbSession, admin_id: int | None) -> None:
    """
    Lazily cleans up sessions that will NEVER finish: a server restart /
    crash leaves rows stuck in 'uploading' or 'queued' with no thread
    behind them. The frontend polls upload-status every ~1s while a
    session looks in-flight, so without this every stuck row would be
    polled forever, hammering the DB. A session is stale when it hasn't
    been touched in *longer than* the maximum a live upload can possibly
    exist - upload_session_timeout covers the sum of queue wait (the row
    is created as 'uploading' before the concurrency limiter grants a
    slot) plus every chunk transfer (progress commits keep updated_at
    fresh), so any row older than that is guaranteed orphaned and never a
    false-positive. The cutoff is derived from the DATABASE's own now()
    because updated_at itself is stamped by the DB's clock (MySQL local
    server time), not Python's.
    """
    idle = get_settings().upload_session_timeout
    cutoff = _db_utcnow(db) - datetime.timedelta(seconds=idle)
    stale = (
        db.query(UploadSession)
        .filter(
            UploadSession.admin_id == admin_id,
            UploadSession.status.in_(("uploading", "queued")),
            UploadSession.updated_at < cutoff,
        )
        .all()
    )
    for session in stale:
        _fail_upload_session(
            db,
            session,
            "UPLOAD_STALE",
            "This upload was interrupted (server restart or process crash) and will not resume.",
        )


def get_upload_session_status(db: DbSession, admin_id: int | None, upload_id: str) -> UploadSession:
    session = (
        db.query(UploadSession)
        .filter(UploadSession.admin_id == admin_id, UploadSession.upload_id == upload_id)
        .first()
    )
    if session is None:
        raise not_found("Upload not found.", code="UPLOAD_NOT_FOUND")
    # Flips dead-but-never-failed rows to 'failed' so the frontend's
    # poll loop terminates instead of running forever (each poll costs DB
    # round-trips).
    if session.status in ("uploading", "queued"):
        _fail_stale_upload_sessions(db, admin_id)
        db.refresh(session)
    return session


def list_recent_upload_sessions(
    db: DbSession, admin_id: int | None, limit: int = 50
) -> list[dict]:
    """
    The server ALWAYS persists every upload attempt in upload_sessions
    (idempotency ledger, Section 4), so a page refresh doesn't have to
    lose sight of in-flight or just-finished uploads - the frontend can
    rebuild its list from here. Returns dicts (session + album/client
    labels) ordered newest-first; callers present them via
    upload_session_list_item(). Scoped to the requesting admin so one
    admin never sees another's uploads.
    """
    # Sweep dead-but-never-failed rows FIRST so a refresh never re-hydrates
    # a stale "uploading" session as if it were still transferring (which
    # would start another frontend poll loop over a session with no thread
    # behind it).
    _fail_stale_upload_sessions(db, admin_id)
    db.expire_all()
    sessions = (
        db.query(UploadSession)
        .filter(UploadSession.admin_id == admin_id)
        .order_by(UploadSession.created_at.desc())
        .limit(limit)
        .all()
    )
    if not sessions:
        return []

    album_ids = {s.album_id for s in sessions}
    albums = {
        a.id: a for a in db.query(Album).filter(Album.id.in_(album_ids)).all()
    }
    client_ids = {a.client_id for a in albums.values()}
    clients = {c.id: c for c in db.query(Client).filter(Client.id.in_(client_ids)).all()}

    return [
        {
            "session": s,
            "album_name": albums[s.album_id].album_name if s.album_id in albums else "",
            "client_name": clients[albums[s.album_id].client_id].client_name
            if s.album_id in albums
            and albums[s.album_id].client_id in clients
            else "",
        }
        for s in sessions
    ]


def upload_media_to_album(
    db: DbSession,
    storage: StorageService,
    settings: Settings,
    album: Album,
    filename: str,
    declared_content_type: str,
    file_obj: BinaryIO,
    file_size: int,
    header_bytes: bytes,
    *,
    upload_id: str | None = None,
    admin_id: int | None = None,
) -> Media:
    """
    Validates, uploads to Drive, then saves metadata. If the DB save fails
    after a successful Drive upload, attempts to delete the now-orphaned
    Drive file rather than silently losing track of it (Section 7).

    upload_id + admin_id drive the idempotency ledger (Section 4): the
    same (admin_id, upload_id) pair always represents the same logical
    upload, so a browser retry after a lost response, a timeout, or a
    5xx never produces a duplicate Drive file or a duplicate Media row.
    """
    file_type, mime_type = validate_upload(settings, filename, declared_content_type, file_size, header_bytes)

    if not album.drive_folder_id:
        # Should be impossible for an album created through create_album(),
        # but guards against pre-Phase-3 albums or manual DB edits.
        raise ApiError(
            409, "ALBUM_STORAGE_NOT_PROVISIONED", "This album has no storage folder. Recreate the album."
        )

    upload_id = upload_id or str(uuid.uuid4())
    session, existing_media = _reserve_upload_session(db, admin_id, upload_id, album, filename, file_size)
    if existing_media is not None:
        return existing_media

    # Section 3 (outer gate): caps how many uploads may be in the
    # reserve-disk -> transfer-to-storage pipeline at once, server-wide.
    # Protects against a burst of many files selected at once (e.g. a
    # whole shoot uploaded in one go) all landing on the server
    # simultaneously. This wraps a STRICTER, separate limiter further
    # inside (storage.upload() itself only allows upload_max_concurrent
    # transfers to Drive at a time) - waiting here just means "your disk
    # reservation is held, your turn to actually transfer is coming."
    limiter = get_upload_limiter(settings.upload_max_concurrent_requests)
    try:
        with limiter.slot(timeout=settings.upload_queue_wait_seconds):
            # Section 5: disk-space protection. Reserved for the lifetime of
            # this upload attempt and always released below, on every exit path.
            tracker = get_disk_tracker()
            reservation_key = f"upload:{admin_id}:{upload_id}"
            try:
                tracker.try_reserve(reservation_key, file_size, min_free_bytes=settings.upload_min_free_disk_bytes)
            except InsufficientDiskSpaceError as exc:
                _fail_upload_session(db, session, "INSUFFICIENT_DISK_SPACE", str(exc))
                raise ApiError(
                    507,
                    "INSUFFICIENT_DISK_SPACE",
                    "Not enough disk space is available to accept this upload right now. Please retry shortly.",
                )

            progress_cb = _make_progress_updater(db, session)

            try:
                stored = storage.upload(
                    file_obj,
                    filename,
                    mime_type,
                    album.drive_folder_id,
                    progress_callback=progress_cb,
                    upload_id=upload_id,
                )
            except StorageTimeoutError as exc:
                logger.error("Drive upload timed out for album %s upload_id=%s: %s", album.id, upload_id, exc)
                _fail_upload_session(db, session, "UPLOAD_TIMEOUT", str(exc))
                raise ApiError(504, "UPLOAD_TIMEOUT", "The upload timed out. Please retry.")
            except StorageError as exc:
                logger.error("Drive upload failed for album %s: %s", album.id, exc)
                _fail_upload_session(db, session, "STORAGE_UPLOAD_FAILED", str(exc))
                raise ApiError(502, "STORAGE_UPLOAD_FAILED", "Upload to storage failed. Please retry.")
            finally:
                tracker.release(reservation_key)
    except UploadQueueTimeoutError as exc:
        logger.warning("Upload queue timed out for album %s upload_id=%s: %s", album.id, upload_id, exc)
        _fail_upload_session(db, session, "SERVER_BUSY", str(exc))
        raise ApiError(
            503,
            "SERVER_BUSY",
            "The server is processing too many uploads right now. Please retry in a moment.",
        )

    # Durable checkpoint (Section 9): committed BEFORE the Media row is
    # created, specifically so a crash in the next few lines still leaves
    # evidence an orphan-reconciliation pass can find and safely clean up.
    session.drive_file_id = stored.provider_file_id
    session.bytes_uploaded = stored.size or file_size
    db.commit()

    # Thumbnail/poster generation is best-effort and non-fatal: a failure
    # here means the gallery grid falls back to a placeholder icon for this
    # item, not a failed upload (Section 15 wants thumbnails, but the
    # original file existing safely in storage matters more).
    thumbnail_file_id = None
    try:
        file_uuid = str(uuid.uuid4())
        thumb_bytes = None
        if file_type == "photo":
            thumb_bytes = generate_image_thumbnail(file_obj)
        elif file_type == "video":
            thumb_bytes = generate_video_poster(file_obj, filename)

        if thumb_bytes:
            thumb_stream = io.BytesIO(thumb_bytes)
            thumb_stored = storage.upload(
                thumb_stream, f"thumb_{file_uuid}.jpg", "image/jpeg", album.drive_folder_id, upload_id=upload_id
            )
            thumbnail_file_id = thumb_stored.provider_file_id
            session.thumbnail_drive_file_id = thumbnail_file_id
            db.commit()
    except Exception as exc:  # noqa: BLE001 - thumbnail failures must never fail the upload
        logger.warning("Thumbnail generation/upload failed for album %s: %s", album.id, exc)
        thumbnail_file_id = None

    try:
        media = Media(
            client_id=album.client_id,
            album_id=album.id,
            file_uuid=file_uuid,
            file_name=filename,
            file_type=file_type,
            mime_type=mime_type,
            file_size=stored.size or file_size,
            google_drive_file_id=stored.provider_file_id,
            thumbnail_reference=thumbnail_file_id,
            status="ready",
        )
        db.add(media)
        db.commit()
        db.refresh(media)
    except Exception:
        db.rollback()
        logger.critical(
            "DB save failed after successful Drive upload - orphaned file %s in album %s. Attempting cleanup.",
            stored.provider_file_id,
            album.id,
        )
        try:
            storage.delete(stored.provider_file_id)
            logger.info("Cleaned up orphaned Drive file %s after DB failure.", stored.provider_file_id)
        except StorageError as cleanup_exc:
            logger.critical(
                "FAILED to clean up orphaned Drive file %s - manual reconciliation required: %s",
                stored.provider_file_id,
                cleanup_exc,
            )
        if thumbnail_file_id:
            try:
                storage.delete(thumbnail_file_id)
            except StorageError as cleanup_exc:
                logger.critical(
                    "FAILED to clean up orphaned thumbnail %s - manual reconciliation required: %s",
                    thumbnail_file_id,
                    cleanup_exc,
                )
        _fail_upload_session(db, session, "MEDIA_SAVE_FAILED", "DB save failed after successful Drive upload.")
        raise ApiError(500, "MEDIA_SAVE_FAILED", "Upload succeeded but saving the record failed. Please retry.")

    session.status = "completed"
    session.media_id = media.id
    session.bytes_uploaded = file_size
    db.commit()
    log_event(logger, "upload_completed", upload_id=upload_id, media_id=media.id, file_size=file_size)

    return media


def delete_media(db: DbSession, storage: StorageService, media: Media) -> None:
    for file_id in filter(None, [media.google_drive_file_id, media.thumbnail_reference]):
        try:
            storage.delete(file_id)
        except StorageNotFoundError:
            pass  # already gone at the provider - fine to proceed
        except StorageError as exc:
            logger.error("Failed to delete Drive file %s: %s", file_id, exc)
            raise ApiError(502, "STORAGE_DELETE_FAILED", "Could not delete the file from storage. Please retry.")

    db.delete(media)
    db.commit()


def bulk_delete_media(db: DbSession, storage: StorageService, media_ids: list[int]) -> dict:
    """
    Deletes each id independently through the same delete_media() used by
    the single-item endpoint - no separate bulk-specific deletion logic to
    keep in sync. A failure on one item never aborts the rest; the caller
    gets a per-item breakdown so the UI can show "138 deleted, 2 failed"
    rather than an all-or-nothing result.
    """
    deleted: list[int] = []
    failed: list[dict] = []
    for media_id in media_ids:
        media = db.query(Media).filter(Media.id == media_id).first()
        if media is None:
            failed.append({"id": media_id, "code": "MEDIA_NOT_FOUND", "message": "Media not found."})
            continue
        try:
            delete_media(db, storage, media)
            deleted.append(media_id)
        except ApiError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            failed.append(
                {
                    "id": media_id,
                    "code": detail.get("code", "DELETE_FAILED"),
                    "message": detail.get("message", "Delete failed."),
                }
            )
    return {"deleted": deleted, "failed": failed}


def bulk_move_media(db: DbSession, storage: StorageService, media_ids: list[int], target_album: Album) -> dict:
    """
    Same reuse pattern as bulk_delete_media: each id goes through the
    existing move_media_to_album(), so cross-client protection and the
    storage-first/DB-second reconciliation logic apply per item exactly as
    they do for a single move - a batch that mixes clients simply fails
    those specific items rather than failing (or silently allowing) the
    whole batch.
    """
    moved: list[int] = []
    failed: list[dict] = []
    for media_id in media_ids:
        media = db.query(Media).filter(Media.id == media_id).first()
        if media is None:
            failed.append({"id": media_id, "code": "MEDIA_NOT_FOUND", "message": "Media not found."})
            continue
        try:
            move_media_to_album(db, storage, media, target_album)
            moved.append(media_id)
        except ApiError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            failed.append(
                {
                    "id": media_id,
                    "code": detail.get("code", "MOVE_FAILED"),
                    "message": detail.get("message", "Move failed."),
                }
            )
    return {"moved": moved, "failed": failed}
