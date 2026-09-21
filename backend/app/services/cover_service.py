"""
Automatic client cover image.

Every client gets exactly ONE cover (Client.cover_drive_file_id), generated
without any human choosing it: there is no upload/select/replace/delete for it
anywhere in the API or UI.

HOW IT FITS THE UPLOAD PIPELINE (Upload-Pipeline.md) - nothing about the
direct-to-Drive flow changes:

    POST /upload-session        response now also says `cover_needed`
                                (client has no cover AND file is an eligible photo)
    browser PUT -> Drive        unchanged
    browser thumbnail           unchanged
    POST /upload-complete       unchanged - the Media row is committed here
    POST /upload-session/{id}/cover     <- the only new step (this module)

The browser builds the cover (<= 1600px WebP) from the file the admin picked -
the server never downloads the original photo and never builds a cover from
one - and sends it AFTER /upload-complete has succeeded. That ordering is what
guarantees the requirement "cover failure must never break the upload": by the
time any cover code runs, the media is already stored, validated and committed,
so nothing in here can roll it back or fail it. A failed cover is logged, the
client simply still has no cover, and the next eligible upload tries again.

"First eligible photo" = the first eligible photo to finish uploading while the
client has no cover. Once cover_drive_file_id is set it is never replaced, so
the gallery hero can't change under the client. If several uploads of a brand
new client finish at the same moment, the compare-and-set below lets exactly
one of them win; the rest are no-ops.

The cover lives in a dedicated "Cover Images" folder directly under the client
folder (a sibling of the album folders, never inside one). The SAME folder
also holds every item thumbnail (video posters and photo thumbs - see
media_service._thumbnail_storage_folder): all "cover-like" images belong to
the client, not to any album, so they stay put when media moves between
albums. The cover itself is deliberately NOT recorded on any UploadSession
and is uploaded without an upload_id, so orphan reconciliation
(services/orphan_reconciliation.py) can never mistake it for an abandoned
upload.
"""

import logging
from io import BytesIO

from sqlalchemy.orm import Session as DbSession

from app.config.settings import Settings
from app.models.client import Client
from app.models.media import Media
from app.models.upload_session import UploadSession
from app.schemas.errors import ApiError, bad_request, not_found
from app.services.folder_naming import COVER_FILE_NAME, COVER_FOLDER_NAME
from app.services.media_validation import guess_mime_type, is_photo_filename
from app.services.storage_service import StorageError, StorageNotFoundError, StorageService
from app.services.upload_logging import log_event
from app.workers.thumbnail_worker import normalize_browser_cover

logger = logging.getLogger("gallery.cover")

COVER_MIME_TYPE = "image/webp"


# ---- eligibility ------------------------------------------------------------


def is_cover_eligible_filename(settings: Settings, filename: str) -> bool:
    """
    A photo the browser can reliably turn into a still hero image: any
    configured image type except GIF (animated / palette-limited - it would be
    a poor hero, and a canvas only ever captures its first frame anyway).
    Videos are never a cover source.
    """
    return is_photo_filename(settings, filename) and guess_mime_type(filename) != "image/gif"


def client_needs_cover(client: Client) -> bool:
    return not client.cover_drive_file_id


# ---- storing ----------------------------------------------------------------


def _claim_column(db: DbSession, client_id: int, column, value: str) -> bool:
    """
    Atomic compare-and-set: sets `column` to `value` only while it is still
    NULL, and reports whether THIS call was the one that set it. A single
    UPDATE ... WHERE col IS NULL statement, so it is race-safe on MySQL and
    SQLite alike without holding a row lock across a Drive round trip (the
    same "don't hold a lock over a Drive call" rule the thumbnail path
    follows).
    """
    updated = (
        db.query(Client)
        .filter(Client.id == client_id, column.is_(None))
        .update({column: value}, synchronize_session=False)
    )
    db.commit()
    return updated == 1


def _best_effort_delete_file(storage: StorageService, file_id: str, *, client_id: int) -> None:
    try:
        storage.delete(file_id)
    except Exception:  # noqa: BLE001 - cleanup of our own stray file must never mask the real outcome
        log_event(logger, "cover.cleanup_failed", logging.WARNING, client_id=client_id, file_id=file_id)


def _best_effort_delete_folder(storage: StorageService, folder_id: str, *, client_id: int) -> None:
    try:
        storage.delete_folder(folder_id)
    except Exception:  # noqa: BLE001
        log_event(logger, "cover.cleanup_failed", logging.WARNING, client_id=client_id, folder_id=folder_id)


def ensure_cover_folder(db: DbSession, storage: StorageService, client: Client) -> str:
    """
    The client's "Cover Images" folder, created on first use and remembered in
    Client.cover_folder_id so a retry after a failed cover upload reuses it
    rather than creating a second folder. Concurrent first-cover requests may
    each create a folder, but only one wins the compare-and-set; the losers
    delete theirs and use the winner's.

    Shared by the automatic cover and every item thumbnail (video poster /
    photo thumb): media_service calls this so thumbnails land in the same
    per-client folder as cover.webp.
    """
    if client.cover_folder_id:
        return client.cover_folder_id

    try:
        created_folder_id = storage.create_folder(COVER_FOLDER_NAME, parent_folder_id=client.drive_folder_id)
    except StorageError as exc:
        raise ApiError(502, "COVER_STORAGE_FAILED", "Could not prepare the cover folder.") from exc

    if _claim_column(db, client.id, Client.cover_folder_id, created_folder_id):
        db.refresh(client)
        return created_folder_id

    # Lost the race - somebody else recorded their folder first.
    _best_effort_delete_folder(storage, created_folder_id, client_id=client.id)
    db.refresh(client)
    if not client.cover_folder_id:  # pragma: no cover - defensive, the winner just set it
        raise ApiError(502, "COVER_STORAGE_FAILED", "Could not prepare the cover folder.")
    return client.cover_folder_id


def store_client_cover(
    db: DbSession,
    storage: StorageService,
    settings: Settings,
    client_id: int,
    image_bytes: bytes,
) -> bool:
    """
    Stores `image_bytes` (the browser-generated cover) as the client's cover,
    but ONLY if the client doesn't have one yet. Returns True if this call
    created the cover, False if the client already had one (nothing changes,
    nothing is uploaded).

    Raises ApiError for a bad image (400) or a storage failure (502). The
    caller treats both as non-fatal - see attach_cover_from_upload.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if client is None:
        raise not_found("Client not found.", code="CLIENT_NOT_FOUND")

    # Cheap exit for the overwhelmingly common case (every upload after the
    # first): no image decode, no Drive call.
    if client.cover_drive_file_id:
        return False

    if not client.drive_folder_id:
        raise ApiError(409, "CLIENT_STORAGE_NOT_PROVISIONED", "This client has no storage folder yet.")

    if not image_bytes or len(image_bytes) > settings.cover_upload_max_bytes:
        raise bad_request("Cover image is empty or too large.", code="COVER_INVALID")

    cover_bytes = normalize_browser_cover(image_bytes)
    if cover_bytes is None:
        raise bad_request("Cover image is not a usable image.", code="COVER_INVALID")

    folder_id = ensure_cover_folder(db, storage, client)

    try:
        stored = storage.upload(BytesIO(cover_bytes), COVER_FILE_NAME, COVER_MIME_TYPE, folder_id)
    except StorageNotFoundError as exc:
        # The recorded folder no longer exists in Drive (deleted by hand).
        # Forget it so the next attempt creates a fresh one, instead of
        # failing against the dead folder id forever.
        db.query(Client).filter(Client.id == client.id).update(
            {Client.cover_folder_id: None}, synchronize_session=False
        )
        db.commit()
        raise ApiError(502, "COVER_STORAGE_FAILED", "The cover folder is missing; it will be recreated.") from exc
    except StorageError as exc:
        raise ApiError(502, "COVER_STORAGE_FAILED", "Could not store the cover image.") from exc

    if _claim_column(db, client.id, Client.cover_drive_file_id, stored.provider_file_id):
        log_event(logger, "cover.created", client_id=client.id, drive_file_id=stored.provider_file_id)
        return True

    # Another upload set the cover between our check and now. Exactly one
    # cover may exist, so discard the file we just wrote.
    _best_effort_delete_file(storage, stored.provider_file_id, client_id=client.id)
    return False


# ---- the route-facing entry point -------------------------------------------


def attach_cover_from_upload(
    db: DbSession,
    storage: StorageService,
    settings: Settings,
    admin_id: int | None,
    upload_id: str,
    image_bytes: bytes,
) -> bool:
    """
    POST /upload-session/{upload_id}/cover. Returns True if a cover was
    created, False if the client already had one.

    The client is derived entirely server-side, from the admin's own COMPLETED
    upload session -> its Media -> that Media's client. Nothing about which
    client, album or photo this is comes from the request, so a cover can only
    ever be attached to the client whose photo this admin just uploaded, and
    only a stored, validated, committed photo can trigger one.
    """
    session = (
        db.query(UploadSession)
        .filter(UploadSession.admin_id == admin_id, UploadSession.upload_id == upload_id)
        .first()
    )
    if session is None:
        raise not_found("Upload session not found.", code="UPLOAD_NOT_FOUND")

    # Post-completion only - see the module docstring for why this ordering
    # is what makes "a cover failure can't break an upload" structurally true.
    if session.status != "completed" or session.media_id is None:
        raise ApiError(409, "UPLOAD_NOT_COMPLETED", "The upload must be completed before a cover can be attached.")

    media = db.query(Media).filter(Media.id == session.media_id).first()
    if media is None:
        raise not_found("Media not found.", code="MEDIA_NOT_FOUND")
    if media.file_type != "photo" or not is_cover_eligible_filename(settings, media.file_name):
        raise ApiError(409, "COVER_SOURCE_NOT_ELIGIBLE", "This file cannot be used as a cover.")

    try:
        return store_client_cover(db, storage, settings, media.client_id, image_bytes)
    except ApiError as exc:
        # The upload itself is long since committed; this only records that
        # the cover step didn't work. The client keeps working (default hero)
        # and the next eligible upload retries automatically.
        log_event(
            logger,
            "cover.failed",
            logging.WARNING,
            client_id=media.client_id,
            upload_id=upload_id,
            code=exc.detail.get("code") if isinstance(exc.detail, dict) else None,
        )
        raise
