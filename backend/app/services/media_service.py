import datetime
import io
import logging
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.config.settings import Settings, get_settings
from app.models.album import Album
from app.models.client import Client
from app.models.media import Media
from app.models.media_wishlist import MediaWishlist
from app.models.upload_session import UploadSession
from app.schemas.errors import ApiError, bad_request, forbidden, not_found
from app.schemas.media import MediaUpdateRequest
from app.schemas.pagination import paginate_params
from app.services.album_service import album_not_expired_clause, check_album_not_expired
from app.services.folder_naming import THUMBNAIL_FOLDER_NAME
from app.services.media_aggregates import photo_count_column, total_bytes_column, video_count_column
from app.services.media_validation import (
    guess_mime_type,
    validate_upload,
    validate_upload_intent,
)
from app.services.storage_service import StorageError, StorageNotFoundError, StorageService, StoredFile
from app.services.upload_logging import log_event
from app.services.wishlist_service import WISHLIST_FILTER_ALL, apply_wishlist_filter
from app.workers.thumbnail_worker import generate_image_thumbnail, normalize_browser_thumbnail

logger = logging.getLogger("gallery.media")


def _not_expired_clause():
    # Delegates to album_service so the wishlist queries (which cannot import
    # this module without a cycle) share the exact same expiry rule.
    return album_not_expired_clause()


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


def get_client_media_totals(db: DbSession, client_id: int) -> dict:
    """
    Whole-gallery totals for the client landing page: how many files the
    client has been given, and how many bytes they add up to.

    A single grouped COUNT/SUM in the database rather than anything the
    frontend could work out for itself - the page used to derive its counts
    from one 50-row page of media per album, which silently undercounts any
    album larger than the page it had loaded (Section 13: no N+1s, and never
    report a number that isn't the real one).

    Scoped to the client's own rows only, never joined to anything the
    caller supplies, so it cannot widen past the authenticated client.
    """
    row = (
        db.query(
            func.count(Media.id),
            photo_count_column(),
            video_count_column(),
            total_bytes_column(),
        )
        .filter(Media.client_id == client_id)
        .one()
    )
    return {
        "total_files": row[0] or 0,
        "total_photos": int(row[1] or 0),
        "total_videos": int(row[2] or 0),
        "total_bytes": int(row[3] or 0),
    }


def list_media_for_album_admin(
    db: DbSession,
    album_id: int,
    page: int,
    limit: int,
    search: str | None = None,
    wishlist_filter: str = WISHLIST_FILTER_ALL,
):
    """
    Admin-facing equivalent of list_media_for_client, but scoped by album_id
    directly rather than by an authenticated client - the caller
    (api/admin_albums.py) is responsible for confirming the album itself
    exists via get_album_or_404 before calling this.

    wishlist_filter narrows to the items the album's client has (or hasn't)
    wishlisted, as an SQL EXISTS - see wishlist_service.apply_wishlist_filter.
    """
    page, limit = paginate_params(page, limit)

    query = db.query(Media).filter(Media.album_id == album_id)
    if search:
        # .ilike() compiles to a case-insensitive comparison on every
        # dialect we target (SQLite in tests, MySQL in production), not
        # just Postgres-native ILIKE.
        query = query.filter(Media.file_name.ilike(f"%{search.strip()}%"))
    query = apply_wishlist_filter(query, wishlist_filter)
    query = query.order_by(Media.created_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return rows, total, page, limit


def get_album_media_selection_summary(
    db: DbSession,
    album_id: int,
    search: str | None = None,
    wishlist_filter: str = WISHLIST_FILTER_ALL,
) -> dict:
    """
    Admin equivalent of get_media_selection_summary - backs "Select All"
    on the admin media grid so it selects every matching item across all
    pages, not just what's currently loaded (same id+size-only query shape,
    no full-metadata fetch for the whole album).

    MUST honour the same wishlist filter as the grid it backs: "Select All"
    feeds bulk delete / move / download, so with the Wishlist tab open it has
    to select exactly the visible wishlisted items - never the whole album.
    """
    query = db.query(Media.id, Media.file_size).filter(Media.album_id == album_id)
    if search:
        query = query.filter(Media.file_name.ilike(f"%{search.strip()}%"))
    query = apply_wishlist_filter(query, wishlist_filter)
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

    # Only the ORIGINAL file moves with the media. The thumbnail does NOT:
    # thumbnails live in the client's Thumbnails folder (see
    # _thumbnail_storage_folder), which is per-client and shared across the
    # client's albums, so it must not be dragged from one album folder to
    # another.
    try:
        storage.move_file(media.google_drive_file_id, target_album.drive_folder_id, old_folder_id)
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

# Bytes read back from Drive (a ranged download, never the whole file) to
# run the same magic-byte signature check the old byte-relaying flow ran
# against locally-spooled bytes (Section 16). Matches the header size the
# old /upload route read from its SpooledTemporaryFile.
HEADER_SIGNATURE_BYTES = 4096

# A browser's direct PUT to a Drive resumable session can take a moment to
# finalize on Google's side before the file shows up for a follow-up
# metadata lookup. complete_direct_upload confirms the file right after that
# PUT, so give the lookup a few short retries before burning the session as
# failed - a 404 here is usually transient propagation, not a lost file, and
# on a multi-file batch the session would otherwise be condemned over a
# sub-second race (surfacing to the user as an impossible-to-retry "This
# upload session is 'failed', not awaiting completion." on the next attempt).
# Genuine quota/5xx statuses on the lookup itself are still covered by the
# storage layer's own retry-with-backoff; this only pads the 404-not-vis (yet)
# gap.
UPLOAD_CONFIRM_404_RETRIES = 3
UPLOAD_CONFIRM_404_DELAY_SECONDS = 1.5


def _validate_upload_id(upload_id: str) -> None:
    # Validated here, not just trusted from the client: upload_id is
    # client-minted (see the module docstring on UploadSession), and a
    # value longer than the DB column previously reached db.commit()
    # unchecked - MySQL's strict mode then raised a raw DataError mid-flush
    # (1406 "Data too long for column 'upload_id'"), surfacing as an ugly
    # 500 with a full SQLAlchemy traceback instead of a clean 400.
    if not upload_id or len(upload_id) > UPLOAD_ID_MAX_LENGTH:
        length = len(upload_id) if upload_id else 0
        raise ApiError(
            400, "INVALID_UPLOAD_ID", f"upload_id must be 1-{UPLOAD_ID_MAX_LENGTH} characters (got {length})."
        )


def _delete_from_storage_best_effort(storage: StorageService, provider_file_id: str) -> None:
    try:
        storage.delete(provider_file_id)
    except StorageError as exc:
        logger.critical(
            "FAILED to clean up orphaned Drive file %s - manual reconciliation required: %s",
            provider_file_id,
            exc,
        )


def _open_drive_session(
    db: DbSession,
    storage: StorageService,
    session: UploadSession,
    admin_id: int | None,
    upload_id: str,
    album: Album,
    filename: str,
    file_size: int,
    origin: str | None,
) -> str:
    """
    Asks Drive to open a resumable upload session and returns its URL.
    Any failure here fails the session the same way a failed transfer
    used to (Section 9) - the caller never gets a session back in a state
    that claims to be 'uploading' without a real Drive session behind it.
    """
    mime_type = guess_mime_type(filename)
    try:
        return storage.create_resumable_session(
            filename, mime_type, file_size, album.drive_folder_id, upload_id=upload_id, origin=origin
        )
    except StorageError as exc:
        logger.error("Failed to open Drive resumable session for upload_id=%s: %s", upload_id, exc)
        _fail_upload_session(db, session, "STORAGE_SESSION_FAILED", str(exc))
        raise ApiError(502, "STORAGE_SESSION_FAILED", "Could not start the upload with storage. Please retry.")


def start_direct_upload(
    db: DbSession,
    storage: StorageService,
    settings: Settings,
    admin_id: int | None,
    upload_id: str,
    album: Album,
    filename: str,
    file_size: int,
    origin: str | None = None,
) -> tuple[UploadSession, str | None, Media | None]:
    """
    Browser -> Drive direct upload, step 1 of 2 (POST /upload-session).

    origin is the browser's Origin header, ALREADY validated by the caller
    against the application's own CORS allowlist (see admin_media.py) -
    forwarded to Drive so the resumable session it opens actually allows
    that origin's direct PUT (see create_resumable_session's docstring;
    without this, Drive issues a session with no CORS allowance and the
    browser's own subsequent PUT is blocked client-side).

    This server never receives the file's bytes at all: it validates the
    request's shape (extension/declared size only - nothing deeper is
    possible yet, since no bytes exist here to sniff), reserves the same
    idempotency-ledger row the old byte-relaying flow used (Section 4),
    then asks Drive to open a resumable upload session and hands its URL
    back for the BROWSER to PUT its bytes to directly from this point on.

    Returns (session, upload_url, existing_media):
      - existing_media is non-None only on an idempotent replay of an
        already-completed upload - callers should return it as-is;
        upload_url is None in that case (nothing left to upload).
      - Otherwise upload_url is the fresh Drive resumable session URL the
        browser should PUT to.
    """
    _validate_upload_id(upload_id)
    validate_upload_intent(settings, filename, file_size)

    if not album.drive_folder_id:
        # Should be impossible for an album created through create_album(),
        # but guards against pre-Phase-3 albums or manual DB edits.
        raise ApiError(
            409, "ALBUM_STORAGE_NOT_PROVISIONED", "This album has no storage folder. Recreate the album."
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
                return session, None, media
            # Session says completed but the Media row is gone (e.g.
            # deleted since) - fall through and treat as a fresh retry.
        if session.status == "uploading":
            raise ApiError(
                409, "UPLOAD_ALREADY_IN_PROGRESS", "This upload is already being processed. Please wait."
            )

        upload_url = _open_drive_session(
            db, storage, session, admin_id, upload_id, album, filename, file_size, origin
        )
        session.album_id = album.id
        session.filename = filename
        session.total_bytes = file_size
        session.bytes_uploaded = 0
        session.status = "uploading"
        session.error_code = None
        session.error_message = None
        session.drive_file_id = None
        if session.thumbnail_drive_file_id:
            # A browser-generated poster the PREVIOUS (failed/abandoned)
            # attempt already uploaded. This attempt regenerates its own, so
            # forgetting the id here without deleting the file would strand
            # it in Drive with nothing left pointing at it.
            _delete_from_storage_best_effort(storage, session.thumbnail_drive_file_id)
        session.thumbnail_drive_file_id = None
        session.drive_resumable_upload_url = upload_url
        db.commit()
        return session, upload_url, None

    session = UploadSession(
        upload_id=upload_id,
        admin_id=admin_id,
        album_id=album.id,
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
        if existing is not None and existing.status == "completed" and existing.media_id:
            media = db.query(Media).filter(Media.id == existing.media_id).first()
            if media is not None:
                return existing, None, media
        raise ApiError(
            409, "UPLOAD_ALREADY_IN_PROGRESS", "This upload is already being processed. Please wait."
        )
    db.refresh(session)

    upload_url = _open_drive_session(
        db, storage, session, admin_id, upload_id, album, filename, file_size, origin
    )
    session.status = "uploading"
    session.drive_resumable_upload_url = upload_url
    db.commit()

    log_event(logger, "upload_started", upload_id=upload_id, album_id=album.id, filename=filename, file_size=file_size)
    return session, upload_url, None


def report_upload_progress(db: DbSession, admin_id: int | None, upload_id: str, bytes_uploaded: int) -> UploadSession:
    """
    Best-effort progress ping sent by the browser while it PUTs bytes
    directly to Drive (Section 8) - the only way this server can reflect
    real transfer progress now that it isn't the one relaying the bytes.
    Purely cosmetic: never trusted for anything beyond display. A session
    that isn't currently 'uploading' silently ignores a late/stray ping
    (a race with completion/failure, not a bug) rather than erroring.
    """
    session = (
        db.query(UploadSession)
        .filter(UploadSession.admin_id == admin_id, UploadSession.upload_id == upload_id)
        .first()
    )
    if session is None:
        raise not_found("Upload not found.", code="UPLOAD_NOT_FOUND")
    if session.status != "uploading":
        return session

    capped = max(0, bytes_uploaded)
    if session.total_bytes:
        capped = min(capped, session.total_bytes)
    session.bytes_uploaded = capped
    db.commit()
    return session


def _fail_upload_session(db: DbSession, session: UploadSession, code: str, message: str) -> None:
    try:
        session.status = "failed"
        session.error_code = code
        session.error_message = message[:2000]
        # A failed session's Drive resumable URL is either already
        # unusable (session expired/aborted) or must not be handed out
        # again - clearing it means a stray late browser retry against
        # the OLD url fails cleanly at Drive rather than silently landing
        # bytes for a session this server has already given up on.
        session.drive_resumable_upload_url = None
        db.commit()
    except Exception:  # noqa: BLE001 - never let bookkeeping failure mask the real error
        db.rollback()
        logger.error("Failed to persist failure state for upload_id=%s", session.upload_id)
    log_event(logger, "upload_failed", upload_id=session.upload_id, error_code=code)


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
    Lazily cleans up sessions that will NEVER finish. Two ways a row gets
    stuck now that the browser talks to Drive directly: a server restart
    with rows created moments before (rare, since starting a session is
    now a single fast round trip rather than a multi-minute transfer), or
    - more commonly in this architecture - a browser that opened a
    session and then never finished (or never reported finishing) its
    direct PUT to Drive: closed tab, lost network, etc. The frontend polls
    upload-status every ~1s while a session looks in-flight, so without
    this every abandoned row would be polled forever. A session is stale
    when it hasn't been touched in *longer than* upload_session_timeout -
    generous enough to cover a genuinely large direct-to-Drive transfer
    plus its progress pings, so this never false-positives on a real
    upload still in flight. The cutoff is derived from the DATABASE's own
    now() because updated_at itself is stamped by the DB's clock (MySQL
    local server time), not Python's.
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
            "This upload was interrupted (browser closed, lost connection, or server restart) and will not resume.",
        )


def abandon_direct_upload(db: DbSession, admin_id: int | None, upload_id: str) -> None:
    """
    Called by the browser when its own direct-to-Drive PUT fails or is
    cancelled, so a subsequent retry with the SAME upload_id isn't
    rejected as "already in progress" (Section 4/9's idempotency check) -
    this server has no other way to learn a direct browser<->Drive
    transfer failed, since it was never in that data path to observe the
    failure itself. A no-op if the session has already reached a terminal
    state - this must never be able to undo a genuine completion.
    """
    session = (
        db.query(UploadSession)
        .filter(UploadSession.admin_id == admin_id, UploadSession.upload_id == upload_id)
        .first()
    )
    if session is None or session.status not in ("queued", "uploading"):
        return
    _fail_upload_session(db, session, "UPLOAD_ABANDONED", "Upload attempt was abandoned by the browser.")


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


def _best_effort_delete_folder(storage: StorageService, folder_id: str, *, client_id: int) -> None:
    try:
        storage.delete_folder(folder_id)
    except Exception:  # noqa: BLE001
        log_event(logger, "thumbnail.cleanup_failed", logging.WARNING, client_id=client_id, folder_id=folder_id)


def _ensure_thumbnail_folder(db: DbSession, storage: StorageService, client: Client) -> str:
    """
    The client's ONE "Thumbnails" folder, created on first use and remembered in
    Client.thumbnail_folder_id so a retry after a failed thumbnail upload reuses
    it rather than creating a second folder. Concurrent first-thumbnail requests
    may each create a folder, but only one wins the compare-and-set; the losers
    delete theirs and use the winner's.

    A single atomic UPDATE ... WHERE col IS NULL (no row lock held across the
    Drive round trip), so it is race-safe on MySQL and SQLite alike.
    """
    if client.thumbnail_folder_id:
        return client.thumbnail_folder_id

    try:
        created_folder_id = storage.create_folder(THUMBNAIL_FOLDER_NAME, parent_folder_id=client.drive_folder_id)
    except StorageError as exc:
        # The underlying cause is logged HERE, and deliberately not left to the
        # caller: this ApiError subclasses HTTPException, NOT StorageError, so
        # it passes straight through the `except StorageError` handler in
        # attach_direct_upload_thumbnail - meaning that handler's "Browser
        # thumbnail upload to storage failed" warning never runs for a folder
        # -creation failure. Without this line a Drive-side problem (403
        # insufficientFilePermissions on the client folder, 429 quota, a
        # revoked token) reached the client as a bare 502 in the access log
        # with nothing at all in the application log explaining it.
        log_event(
            logger,
            "thumbnail_folder.create_failed",
            logging.ERROR,
            client_id=client.id,
            parent_folder_id=client.drive_folder_id,
            error=str(exc),
        )
        # A distinct code from the upload failure below, so "couldn't create
        # the folder" is distinguishable from "couldn't store the file in it".
        raise ApiError(502, "THUMBNAIL_FOLDER_FAILED", "Could not prepare the thumbnail folder.") from exc

    updated = (
        db.query(Client)
        .filter(Client.id == client.id, Client.thumbnail_folder_id.is_(None))
        .update({Client.thumbnail_folder_id: created_folder_id}, synchronize_session=False)
    )
    db.commit()

    if updated == 1:
        db.refresh(client)
        return created_folder_id

    # Lost the race - somebody else recorded their folder first.
    _best_effort_delete_folder(storage, created_folder_id, client_id=client.id)
    db.refresh(client)
    if not client.thumbnail_folder_id:  # pragma: no cover - defensive, the winner just set it
        log_event(
            logger,
            "thumbnail_folder.create_failed",
            logging.ERROR,
            client_id=client.id,
            note="lost_race_and_winner_unreadable",
        )
        raise ApiError(502, "THUMBNAIL_FOLDER_FAILED", "Could not prepare the thumbnail folder.")
    return client.thumbnail_folder_id


def _thumbnail_storage_folder(db: DbSession, storage: StorageService, album: Album) -> str:
    """
    The folder every item thumbnail (video poster or photo thumb) is stored in:
    the client's ONE "Thumbnails" folder. Thumbnails belong to the CLIENT, not to
    an album, so they stay put when media moves between albums and each client
    has exactly one imagery folder. Falls back to the album folder only if the
    client has no Drive folder at all (shouldn't happen - albums are provisioned
    inside the client's folder).
    """
    client = db.query(Client).filter(Client.id == album.client_id).first()
    if client is None or not client.drive_folder_id:
        return album.drive_folder_id
    return _ensure_thumbnail_folder(db, storage, client)


def _forget_thumbnail_folder(db: DbSession, client_id: int, folder_id: str) -> bool:
    """
    Drop a recorded imagery-folder id that Drive says no longer exists, so the
    next _ensure_thumbnail_folder() call creates a fresh, correctly-named one
    instead of handing back the same dead id forever.

    Compare-and-set on the id we actually tried, so a concurrent request that
    already recorded a NEW folder isn't clobbered by our stale-id cleanup.
    """
    updated = (
        db.query(Client)
        .filter(Client.id == client_id, Client.thumbnail_folder_id == folder_id)
        .update({Client.thumbnail_folder_id: None}, synchronize_session=False)
    )
    db.commit()
    return updated == 1


def _upload_thumbnail_to_client_folder(
    db: DbSession, storage: StorageService, album: Album, thumb_bytes: bytes, upload_id: str
) -> StoredFile:
    """
    Stores a thumbnail in the client's imagery folder, SELF-HEALING the one
    failure that would otherwise be permanent.

    Client.thumbnail_folder_id is a recorded id, never re-validated against
    Drive, and _ensure_thumbnail_folder() returns it without an existence
    check. So if that folder is ever deleted or trashed in Drive - by hand, by
    a Drive-side cleanup, or because it was created under a client folder that
    has since gone - every subsequent thumbnail upload 404s with
    "File not found: <id>" (reason notFound, location fileId, i.e. the PARENT
    folder) and can never recover on its own. The client is left permanently
    unable to store a thumbnail: no imagery folder in Drive, every item falling
    back to a placeholder tile, and a 502 on every attempt no matter how many
    times it is retried.

    So on a not-found, forget the dead id and retry once against a freshly
    created folder. This is the same self-healing the album-folder guard
    already does for a stale Album.drive_folder_id (see start_direct_upload's
    ALBUM_STORAGE_NOT_PROVISIONED check).

    A genuine permission/quota failure is a different exception and is NOT
    retried or swallowed here - it propagates to the caller.
    """
    for attempt in (1, 2):
        folder_id = _thumbnail_storage_folder(db, storage, album)
        try:
            return storage.upload(
                io.BytesIO(thumb_bytes),
                f"thumb_{uuid.uuid4()}.webp",
                "image/webp",
                folder_id,
                upload_id=upload_id,
            )
        except StorageNotFoundError:
            if attempt == 2:
                # A folder we created ourselves is already gone - something
                # far more serious than a stale id. Give up and let the caller
                # report it rather than looping.
                log_event(
                    logger,
                    "thumbnail_folder.still_missing_after_recreate",
                    logging.ERROR,
                    album_id=album.id,
                    client_id=album.client_id,
                    folder_id=folder_id,
                )
                raise
            if _forget_thumbnail_folder(db, album.client_id, folder_id):
                log_event(
                    logger,
                    "thumbnail_folder.stale_id_cleared",
                    logging.WARNING,
                    album_id=album.id,
                    client_id=album.client_id,
                    folder_id=folder_id,
                    note="recreating",
                )


def _generate_thumbnail_from_storage(
    storage: StorageService,
    settings: Settings,
    drive_file_id: str,
    file_type: str,
    file_size: int,
    filename: str,
) -> bytes | None:
    """
    PHOTOS ONLY. FALLBACK path: reads back a bounded copy of the
    just-uploaded image from Drive to generate its grid thumbnail
    (Section 15/22), used only when the browser produced no thumbnail
    itself during the upload. Photos are small (capped by
    thumbnail_image_source_max_mb), so the read-back is cheap.

    Videos deliberately never come through here: reading a multi-GB video
    back from Drive to grab one frame is exactly the slow "finalizing" step
    this replaced. A video's poster is extracted by the BROWSER and uploaded
    separately (see attach_direct_upload_thumbnail); complete_direct_upload
    just picks it up from the session. Returns None (no thumbnail - already
    a non-fatal, best-effort feature) for anything that isn't an in-cap
    photo.
    """
    if file_type != "photo":
        return None
    if file_size > settings.thumbnail_image_source_max_bytes:
        logger.info("Skipping thumbnail for %s - image exceeds thumbnail_image_source_max_mb.", filename)
        return None
    # Images are small enough (Section 16's allowed types) to hold entirely
    # in memory - no VPS disk touched for this path at all.
    buffer = io.BytesIO()
    for chunk in storage.download(drive_file_id):
        buffer.write(chunk)
    buffer.seek(0)
    return generate_image_thumbnail(buffer)


def attach_direct_upload_thumbnail(
    db: DbSession,
    storage: StorageService,
    settings: Settings,
    admin_id: int | None,
    upload_id: str,
    image_bytes: bytes,
) -> UploadSession:
    """
    Browser-generated thumbnail (VIDEO poster or PHOTO thumb), called by POST
    /upload-session/{upload_id}/thumbnail after the browser's direct PUT of
    the file to Drive has finished and BEFORE POST /upload-complete.

    The thumbnail is a small image the browser produced locally from the
    file (a <video>+<canvas> poster frame, or a <img>+<canvas> downscale) -
    this server never sees, and never needs to download from Drive, the
    original file to make it. It is validated, normalized to WebP, stored in
    the CLIENT's "Thumbnails" folder (see _thumbnail_storage_folder), and its
    Drive id is recorded on
    UploadSession.thumbnail_drive_file_id - a server-side ledger, so the id
    is never taken from the browser and complete_direct_upload needs no new
    request fields to find it.

    Deliberately idempotent and non-fatal in spirit: a repeated call for a
    session that already has a thumbnail is a no-op (a client retrying after
    a lost response never creates a second Drive file), and if the session
    reaches a terminal state while the Drive upload is in flight the newly
    stored file is deleted again rather than orphaned.
    """
    session = (
        db.query(UploadSession)
        .filter(UploadSession.admin_id == admin_id, UploadSession.upload_id == upload_id)
        .first()
    )
    if session is None:
        raise not_found("Upload not found.", code="UPLOAD_NOT_FOUND")
    if session.status != "uploading":
        raise ApiError(
            409,
            "UPLOAD_NOT_IN_PROGRESS",
            f"This upload session is '{session.status}', not accepting a thumbnail.",
        )
    if session.thumbnail_drive_file_id:
        return session  # idempotent: already has one

    if not image_bytes or len(image_bytes) > settings.video_thumbnail_upload_max_bytes:
        raise bad_request("Thumbnail is empty or too large.", code="THUMBNAIL_INVALID")
    thumb_bytes = normalize_browser_thumbnail(image_bytes)
    if thumb_bytes is None:
        raise bad_request("Thumbnail is not a valid image.", code="THUMBNAIL_INVALID")

    album = db.query(Album).filter(Album.id == session.album_id).first()
    if album is None or not album.drive_folder_id:
        raise not_found("Album not found.", code="ALBUM_NOT_FOUND")

    try:
        stored = _upload_thumbnail_to_client_folder(db, storage, album, thumb_bytes, upload_id)
    except StorageError as exc:
        logger.warning("Browser thumbnail upload to storage failed for upload_id=%s: %s", upload_id, exc)
        raise ApiError(502, "THUMBNAIL_STORAGE_FAILED", "Could not store the thumbnail.")

    # Re-read UNDER A ROW LOCK before recording it. The Drive upload above
    # took a moment, during which /upload-complete may have started or
    # finished, or a duplicate request may have won. FOR UPDATE makes
    # complete_direct_upload's own status write wait for this short
    # transaction (see the matching re-check at the end of that function),
    # so the thumbnail is either recorded before completion reads it or
    # rejected here - never silently lost in between.
    locked = (
        db.query(UploadSession)
        .filter(UploadSession.id == session.id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is None or locked.status != "uploading" or locked.thumbnail_drive_file_id:
        db.rollback()  # release the row lock before the (slow) cleanup call
        _delete_from_storage_best_effort(storage, stored.provider_file_id)
        return locked if locked is not None else session

    locked.thumbnail_drive_file_id = stored.provider_file_id
    db.commit()
    log_event(logger, "thumbnail_attached", upload_id=upload_id, thumbnail_bytes=len(thumb_bytes))
    return locked


def _adopt_late_thumbnail(db: DbSession, session: UploadSession, media: Media) -> None:
    """
    Attaches a thumbnail that raced /upload-complete: the browser gave up
    waiting for the browser-generated thumb to be stored and completed the
    upload while its request was still in flight. attach_direct_upload_thumbnail
    records the id under a row lock on the session, so complete_direct_upload's
    status write waits for it - meaning that if a thumbnail landed, it is
    visible on a fresh read of the session here. Adopt it rather than leaving
    a stored thumbnail that nothing points at (a completed session is never
    picked up by orphan reconciliation).
    """
    db.refresh(session)
    if session.thumbnail_drive_file_id:
        media.thumbnail_reference = session.thumbnail_drive_file_id
        media.thumbnail_mime_type = "image/webp"  # browser thumbnails are always normalized to WebP
        db.commit()
        db.refresh(media)


def complete_direct_upload(
    db: DbSession,
    storage: StorageService,
    settings: Settings,
    admin_id: int | None,
    upload_id: str,
    drive_file_id: str,
    reported_size: int,
    reported_mime_type: str | None,
) -> Media:
    """
    Browser -> Drive direct upload, step 2 of 2 (POST /upload-complete),
    called once the browser's direct PUT to the Drive resumable session
    URL has finished. This server never received the file's bytes - what
    it does here instead:
      1. re-confirms the file actually exists in Drive and reads its
         AUTHORITATIVE size/mime straight from the provider (Section 13:
         never trust what the browser reports for the DB record itself),
      2. reads back a small header slice (a ranged download, never the
         whole file) to run the same magic-byte signature check the old
         byte-relaying flow ran against locally-spooled bytes (Section 16),
      3. picks the thumbnail:
           - VIDEO: the poster the browser already extracted and uploaded
             (attach_direct_upload_thumbnail) - NOTHING is downloaded from
             Drive for it, however large the video is.
           - PHOTO: the downscaled thumb the BROWSER uploaded the same way,
             so the bounded read-back (Section 15/22) only runs as a
             fallback when the browser produced none (undecodable file,
             million-pixel image, or its upload failed).
           Either way a missing thumbnail means no thumbnail: the gallery
           shows its placeholder tile and the upload still succeeds.
      4. creates the Media row, with the same orphan-safe durable
         checkpoint and cleanup-on-DB-failure behavior as before
         (Section 7/9).
    """
    session = (
        db.query(UploadSession)
        .filter(UploadSession.admin_id == admin_id, UploadSession.upload_id == upload_id)
        .first()
    )
    if session is None:
        raise not_found("Upload not found.", code="UPLOAD_NOT_FOUND")

    if session.status == "completed" and session.media_id:
        media = db.query(Media).filter(Media.id == session.media_id).first()
        if media is not None:
            log_event(logger, "upload_completed", upload_id=upload_id, note="idempotent_replay")
            return media

    if session.status != "uploading":
        raise ApiError(
            409,
            "UPLOAD_NOT_IN_PROGRESS",
            f"This upload session is '{session.status}', not awaiting completion.",
        )

    album = db.query(Album).filter(Album.id == session.album_id).first()
    if album is None:
        _fail_upload_session(db, session, "ALBUM_NOT_FOUND", "The target album no longer exists.")
        raise not_found("Album not found.", code="ALBUM_NOT_FOUND")

    # Durable checkpoint (Section 9): recorded as soon as we're told a
    # Drive file id exists at all, BEFORE any further validation - so a
    # crash (or a signature-mismatch deletion) after this point still
    # leaves evidence an orphan-reconciliation pass can find, exactly the
    # same guarantee the old flow gave right after storage.upload()
    # returned.
    session.drive_file_id = drive_file_id
    db.commit()

    try:
        for attempt in range(1, UPLOAD_CONFIRM_404_RETRIES + 1):
            try:
                stored = storage.get_file(drive_file_id)
                break
            except StorageNotFoundError:
                if attempt >= UPLOAD_CONFIRM_404_RETRIES:
                    raise
                log_event(
                    logger,
                    "upload_confirm_retry",
                    upload_id=upload_id,
                    attempt=attempt,
                    reason="drive_file_not_visible",
                )
                time.sleep(UPLOAD_CONFIRM_404_DELAY_SECONDS)
    except StorageNotFoundError:
        _fail_upload_session(
            db,
            session,
            "UPLOAD_NOT_FOUND_IN_STORAGE",
            "The browser reported a completed upload, but storage has no matching file.",
        )
        raise ApiError(
            409,
            "UPLOAD_NOT_FOUND_IN_STORAGE",
            "Could not confirm the upload with storage. Please retry.",
        )
    except StorageError as exc:
        logger.error("Could not confirm direct upload for upload_id=%s: %s", upload_id, exc)
        _fail_upload_session(db, session, "STORAGE_CONFIRM_FAILED", str(exc))
        raise ApiError(502, "STORAGE_CONFIRM_FAILED", "Could not confirm the upload with storage. Please retry.")

    # Authoritative size comes from Drive, never from the browser's report
    # (Section 13) - reported_size only ever mattered for the pre-flight
    # sanity check the frontend/backend already did before minting the
    # Drive session in the first place.
    file_size = stored.size or reported_size
    if file_size <= 0:
        _delete_from_storage_best_effort(storage, drive_file_id)
        _fail_upload_session(db, session, "EMPTY_FILE", "Uploaded file is empty.")
        raise ApiError(400, "EMPTY_FILE", "Uploaded file is empty.")
    if file_size > settings.effective_max_upload_bytes:
        _delete_from_storage_best_effort(storage, drive_file_id)
        _fail_upload_session(db, session, "FILE_TOO_LARGE", "File exceeds the maximum allowed upload size.")
        raise ApiError(400, "FILE_TOO_LARGE", "File exceeds the maximum allowed upload size.")

    # A small ranged read-back, NOT the whole file (Section 16) - the one
    # place besides thumbnail generation below that this server touches
    # the uploaded file's actual bytes, and it's bounded to a few KB
    # regardless of the file's real size.
    try:
        header_bytes = b"".join(
            storage.download(drive_file_id, range_start=0, range_end=HEADER_SIGNATURE_BYTES - 1)
        )
    except StorageError as exc:
        logger.error("Could not read back header bytes for upload_id=%s: %s", upload_id, exc)
        _fail_upload_session(db, session, "STORAGE_CONFIRM_FAILED", str(exc))
        raise ApiError(502, "STORAGE_CONFIRM_FAILED", "Could not confirm the upload with storage. Please retry.")

    try:
        file_type, mime_type = validate_upload(
            settings, session.filename, reported_mime_type or "", file_size, header_bytes
        )
    except ApiError:
        logger.warning("Signature validation failed for upload_id=%s - deleting Drive file.", upload_id)
        _delete_from_storage_best_effort(storage, drive_file_id)
        _fail_upload_session(
            db, session, "FILE_SIGNATURE_MISMATCH", "File contents did not match the declared type."
        )
        raise

    session.bytes_uploaded = file_size
    session.total_bytes = file_size
    db.commit()

    # Thumbnail selection is best-effort and non-fatal: a missing thumbnail
    # means the gallery grid falls back to a placeholder tile for this item,
    # not a failed upload (Section 15 wants thumbnails, but the original
    # file existing safely in storage matters more).
    thumbnail_file_id = None
    file_uuid = str(uuid.uuid4())
    if file_type in ("video", "photo"):
        # Already stored by attach_direct_upload_thumbnail (server-side
        # ledger, not a browser-supplied id).
        thumbnail_file_id = session.thumbnail_drive_file_id or None

    # FALLBACK, PHOTOS ONLY. The browser decodes the file locally and gives up
    # SILENTLY whenever it can't - a HEIC the platform won't decode into a
    # canvas, a tainted canvas, a source over photoThumbnail's
    # MAX_SOURCE_PIXELS guard, or the 15s overall deadline - in which case no
    # thumbnail request is ever sent. Without this branch such an upload ended
    # with no thumbnail at all, because the browser path was the ONLY caller of
    # _thumbnail_storage_folder(): the client's "Thumbnails" folder was never
    # created in Drive for a client whose every photo defeated the browser.
    #
    # Videos deliberately never come through here: reading a multi-GB video
    # back from Drive to grab one frame is exactly the slow "finalizing" step
    # the browser-generated poster replaced. A video with no poster keeps its
    # placeholder tile. Non-media types have no visual to show either.
    if not thumbnail_file_id and file_type == "photo":
        try:
            thumb_bytes = _generate_thumbnail_from_storage(
                storage, settings, drive_file_id, file_type, file_size, session.filename
            )
            if thumb_bytes:
                thumbnail_file_id = _upload_thumbnail_to_client_folder(
                    db, storage, album, thumb_bytes, upload_id
                ).provider_file_id
                session.thumbnail_drive_file_id = thumbnail_file_id
                db.commit()
        except Exception as exc:  # noqa: BLE001 - thumbnail failures must never fail the upload
            logger.warning("Thumbnail generation/upload failed for album %s: %s", album.id, exc)
            thumbnail_file_id = None

    if not thumbnail_file_id:
        log_event(logger, "thumbnail_missing", upload_id=upload_id, note="placeholder_will_be_used")

    try:
        media = Media(
            client_id=album.client_id,
            album_id=album.id,
            file_uuid=file_uuid,
            file_name=session.filename,
            file_type=file_type,
            mime_type=mime_type,
            file_size=file_size,
            google_drive_file_id=drive_file_id,
            thumbnail_reference=thumbnail_file_id,
            thumbnail_mime_type="image/webp" if thumbnail_file_id else None,
            status="ready",
        )
        db.add(media)
        db.commit()
        db.refresh(media)
    except Exception:
        db.rollback()
        logger.critical(
            "DB save failed after successful direct Drive upload - orphaned file %s in album %s. Attempting cleanup.",
            drive_file_id,
            album.id,
        )
        _delete_from_storage_best_effort(storage, drive_file_id)
        if thumbnail_file_id:
            _delete_from_storage_best_effort(storage, thumbnail_file_id)
        _fail_upload_session(db, session, "MEDIA_SAVE_FAILED", "DB save failed after successful Drive upload.")
        raise ApiError(500, "MEDIA_SAVE_FAILED", "Upload succeeded but saving the record failed. Please retry.")

    session.status = "completed"
    session.media_id = media.id
    session.drive_resumable_upload_url = None
    db.commit()

    if not media.thumbnail_reference:
        _adopt_late_thumbnail(db, session, media)

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

    # ON DELETE CASCADE on media_wishlists.media_id does this in MySQL, but
    # SQLite (the test database) doesn't enforce foreign keys by default and
    # relying on it here would leave dangling rows there. One indexed DELETE
    # in the same transaction as the media row makes the behaviour identical
    # everywhere.
    db.query(MediaWishlist).filter(MediaWishlist.media_id == media.id).delete(synchronize_session=False)
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