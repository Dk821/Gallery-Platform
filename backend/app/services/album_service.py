import datetime
import logging
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.models.album import Album
from app.models.media import Media
from app.schemas.album import AlbumCreateRequest, AlbumUpdateRequest
from app.schemas.errors import ApiError, forbidden, not_found
from app.schemas.pagination import paginate_params
from app.services.client_service import get_client_or_404
from app.services.folder_naming import build_album_folder_name, generate_folder_uid
from app.services.storage_service import StorageError, StorageService

logger = logging.getLogger("gallery.albums")


def is_album_expired(album: Album) -> bool:
    return album.expires_at is not None and album.expires_at <= datetime.datetime.utcnow()


def check_album_not_expired(album: Album) -> None:
    """
    The single enforcement point for expiry (Part 6): every client-facing
    route that resolves an album - directly or via a media item's album -
    must call this. Admin routes deliberately never call this; admins can
    still manage an expired album (Section: "Admin should still be able to
    manage the album").
    """
    if is_album_expired(album):
        raise ApiError(
            403,
            "ALBUM_EXPIRED",
            "This gallery has expired and is no longer accessible.",
        )


def create_album(db: DbSession, payload: AlbumCreateRequest, storage: StorageService) -> Album:
    # Ensures the target client actually exists before creating the album -
    # never trust a bare client_id from the request body.
    client = get_client_or_404(db, payload.client_id)

    album_uuid = str(uuid.uuid4())
    folder_uid = generate_folder_uid()
    folder_name = build_album_folder_name(payload.album_name, folder_uid)
    try:
        folder_id = storage.create_folder(folder_name, parent_folder_id=client.drive_folder_id)
    except StorageError as exc:
        logger.error("Failed to create Drive folder for new album: %s", exc)
        raise ApiError(502, "STORAGE_FOLDER_CREATE_FAILED", "Could not provision storage for this album.")

    album = Album(
        client_id=payload.client_id,
        album_uuid=album_uuid,
        album_name=payload.album_name,
        description=payload.description,
        status="active",
        drive_folder_id=folder_id,
        folder_uid=folder_uid,
        expires_at=payload.expires_at,
    )
    try:
        db.add(album)
        db.commit()
        db.refresh(album)
    except Exception:
        db.rollback()
        logger.critical(
            "DB save failed after creating Drive folder %s for a new album. Attempting cleanup.", folder_id
        )
        try:
            storage.delete_folder(folder_id)
        except StorageError as cleanup_exc:
            logger.critical(
                "FAILED to clean up orphaned Drive folder %s - manual reconciliation required: %s",
                folder_id,
                cleanup_exc,
            )
        raise ApiError(500, "ALBUM_SAVE_FAILED", "Creating the album failed. Please retry.")

    return album


def get_album_or_404(db: DbSession, album_id: int) -> Album:
    album = db.query(Album).filter(Album.id == album_id).first()
    if album is None:
        raise not_found("Album not found.", code="ALBUM_NOT_FOUND")
    return album


def get_album_media_count(db: DbSession, album_id: int) -> int:
    return db.query(Media).filter(Media.album_id == album_id).count()


def get_album_for_client_or_403(db: DbSession, album_id: int, client_id: int) -> Album:
    """
    The core authorization primitive for every client-facing album/media
    route: resolve the album, then verify it actually belongs to the
    session's authenticated client_id. A 404 here would leak whether the
    album id exists at all to someone probing IDs, so ownership mismatches
    return the same 403 as any other unauthorized access.

    Also enforces expiry (Part 6) - this is the one place every client
    route funnels through, so it's the one place that needs to check it.
    """
    album = db.query(Album).filter(Album.id == album_id).first()
    if album is None or album.client_id != client_id:
        raise forbidden("You do not have access to this album.", code="ALBUM_FORBIDDEN")
    check_album_not_expired(album)
    return album


def list_albums_for_admin(db: DbSession, client_id: int | None, page: int, limit: int):
    page, limit = paginate_params(page, limit)

    media_counts = (
        db.query(Media.album_id, func.count(Media.id).label("cnt")).group_by(Media.album_id).subquery()
    )

    query = db.query(Album, func.coalesce(media_counts.c.cnt, 0).label("media_count")).outerjoin(
        media_counts, media_counts.c.album_id == Album.id
    )
    if client_id is not None:
        query = query.filter(Album.client_id == client_id)
    query = query.order_by(Album.created_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()

    items = []
    for album, media_count in rows:
        items.append(
            {
                "id": album.id,
                "album_uuid": album.album_uuid,
                "client_id": album.client_id,
                "album_name": album.album_name,
                "description": album.description,
                "status": album.status,
                "expires_at": album.expires_at,
                "created_at": album.created_at,
                "media_count": media_count,
            }
        )
    return items, total, page, limit


def list_albums_for_client(db: DbSession, client_id: int, page: int, limit: int):
    # Client-facing equivalent of list_albums_for_admin, but hard-scoped to
    # the authenticated client - there is no code path where a client_id
    # from the request can widen this query.
    return list_albums_for_admin(db, client_id=client_id, page=page, limit=limit)


def update_album(
    db: DbSession, album: Album, payload: AlbumUpdateRequest, storage: StorageService
) -> Album:
    old_name = album.album_name
    name_changed = payload.album_name is not None and payload.album_name != old_name
    if payload.album_name is not None:
        album.album_name = payload.album_name
    if payload.description is not None:
        album.description = payload.description
    # expires_at is genuinely three-state (unset / explicit null to clear /
    # a real datetime), so we check whether the field was actually present
    # in the request body rather than treating None as "don't touch."
    if "expires_at" in payload.model_fields_set:
        album.expires_at = payload.expires_at

    # Keep the Drive folder's readable name in sync with the album name.
    # Only the readable portion changes - folder_uid (and drive_folder_id,
    # untouched here) stays exactly the same.
    if name_changed and album.drive_folder_id:
        new_folder_name = build_album_folder_name(album.album_name, album.folder_uid)
        try:
            storage.rename_folder(album.drive_folder_id, new_folder_name)
        except StorageError as exc:
            logger.error("Failed to rename Drive folder for album %s: %s", album.id, exc)
            raise ApiError(502, "STORAGE_RENAME_FAILED", "Could not rename album storage folder. Please retry.")

    try:
        db.commit()
        db.refresh(album)
    except Exception:
        db.rollback()
        logger.critical(
            "DB save failed after renaming Drive folder %s for album %s. Attempting to roll back the rename.",
            album.drive_folder_id,
            album.id,
        )
        if name_changed and album.drive_folder_id:
            try:
                storage.rename_folder(album.drive_folder_id, build_album_folder_name(old_name, album.folder_uid))
            except StorageError as rollback_exc:
                logger.critical(
                    "FAILED to roll back Drive folder rename for album %s - manual reconciliation "
                    "required: %s",
                    album.id,
                    rollback_exc,
                )
        raise ApiError(500, "ALBUM_SAVE_FAILED", "Updating the album failed. Please retry.")

    return album


def delete_album(db: DbSession, album: Album, storage: StorageService) -> None:
    # Same ordering rationale as delete_client: Drive deletion happens
    # first, and only proceeds to the DB delete on success.
    if album.drive_folder_id:
        try:
            storage.delete_folder(album.drive_folder_id)
        except StorageError as exc:
            logger.error("Failed to delete Drive folder for album %s: %s", album.id, exc)
            raise ApiError(502, "STORAGE_DELETE_FAILED", "Could not delete album storage. Please retry.")

    db.delete(album)
    db.commit()
