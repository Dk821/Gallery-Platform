import datetime
import logging
import uuid

from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DbSession

from app.models.album import Album
from app.models.media import Media
from app.schemas.album import AlbumCreateRequest, AlbumUpdateRequest
from app.schemas.errors import ApiError, forbidden, not_found
from app.schemas.pagination import paginate_params
from app.services.client_service import get_client_or_404
from app.services.folder_naming import build_album_folder_name, generate_folder_uid
from app.services.media_aggregates import photo_count_column, total_bytes_column, video_count_column
from app.services.storage_service import StorageError, StorageService

logger = logging.getLogger("gallery.albums")


def is_album_expired(album: Album) -> bool:
    return album.expires_at is not None and album.expires_at <= datetime.datetime.utcnow()


def album_not_expired_clause():
    """
    SQL equivalent of `not is_album_expired(album)`, for queries that join
    Album. A fresh clause per call, NOT a module-level constant -
    datetime.utcnow() must be evaluated at query time, not once at
    import/server-startup time.
    """
    return or_(Album.expires_at.is_(None), Album.expires_at > datetime.datetime.utcnow())


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


def get_album_media_stats(db: DbSession, album_id: int) -> dict:
    """
    The album card's numbers (total files, the photo/video split, total
    bytes) straight from the database, in one pass.

    Same reason as list_albums_for_admin's aggregate: the client gallery
    page used to invent these by counting a single page of loaded media
    rows, which undercounts any album bigger than that page.
    """
    row = (
        db.query(
            func.count(Media.id),
            photo_count_column(),
            video_count_column(),
            total_bytes_column(),
        )
        .filter(Media.album_id == album_id)
        .one()
    )
    return {
        "media_count": row[0] or 0,
        "photo_count": int(row[1] or 0),
        "video_count": int(row[2] or 0),
        "total_bytes": int(row[3] or 0),
    }


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

    # One grouped pass over Media for the whole page of albums, carrying the
    # count, the photo/video split and the byte total together - the album
    # cards need all four, and asking per album would be an N+1 (Section 13).
    # The count/split/sum expressions come from media_aggregates so they stay
    # valid on MySQL, which has no FILTER (WHERE ...) clause.
    media_stats = (
        db.query(
            Media.album_id,
            func.count(Media.id).label("cnt"),
            photo_count_column().label("photo_cnt"),
            video_count_column().label("video_cnt"),
            total_bytes_column().label("total_bytes"),
        )
        .group_by(Media.album_id)
        .subquery()
    )

    query = db.query(
        Album,
        func.coalesce(media_stats.c.cnt, 0).label("media_count"),
        func.coalesce(media_stats.c.photo_cnt, 0).label("photo_count"),
        func.coalesce(media_stats.c.video_cnt, 0).label("video_count"),
        func.coalesce(media_stats.c.total_bytes, 0).label("total_bytes"),
    ).outerjoin(media_stats, media_stats.c.album_id == Album.id)
    if client_id is not None:
        query = query.filter(Album.client_id == client_id)
    query = query.order_by(Album.created_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()

    items = []
    for album, media_count, photo_count, video_count, total_bytes in rows:
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
                "photo_count": photo_count,
                "video_count": video_count,
                "total_bytes": total_bytes,
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
