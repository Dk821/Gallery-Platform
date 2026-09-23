import logging
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.models.album import Album
from app.models.client import Client
from app.models.media import Media
from app.models.session import ClientSession
from app.schemas.client import ClientCreateRequest, ClientUpdateRequest
from app.schemas.errors import ApiError, bad_request, not_found
from app.schemas.pagination import paginate_params
from app.security.encryption import decrypt_password, encrypt_password
from app.security.password import hash_password
from app.services.folder_naming import build_client_folder_name, generate_folder_uid
from app.services.storage_service import StorageError, StorageService
from app.services.studio_settings_service import get_studio_settings

logger = logging.getLogger("gallery.clients")


def _check_password_policy(db: DbSession, password: str | None) -> None:
    if password is None:
        return
    min_length = get_studio_settings(db).min_client_password_length
    if len(password) < min_length:
        raise bad_request(
            f"Password must be at least {min_length} characters.", code="PASSWORD_TOO_SHORT"
        )


def create_client(db: DbSession, payload: ClientCreateRequest, storage: StorageService) -> Client:
    password = payload.password or None
    _check_password_policy(db, password)
    _check_password_policy(db, payload.download_password)
    client_uuid = str(uuid.uuid4())
    folder_uid = generate_folder_uid()
    folder_name = build_client_folder_name(payload.client_name, folder_uid)

    try:
        folder_id = storage.create_folder(folder_name)
    except StorageError as exc:
        logger.error("Failed to create Drive folder for new client: %s", exc)
        raise ApiError(502, "STORAGE_FOLDER_CREATE_FAILED", "Could not provision storage for this client.")

    client = Client(
        client_uuid=client_uuid,
        client_name=payload.client_name,
        password_hash=hash_password(password) if password else None,
        password_encrypted=encrypt_password(password) if password else None,
        download_password_hash=hash_password(payload.download_password) if payload.download_password else None,
        download_password_encrypted=encrypt_password(payload.download_password)
        if payload.download_password
        else None,
        status="active",
        drive_folder_id=folder_id,
        folder_uid=folder_uid,
    )
    try:
        db.add(client)
        db.commit()
        db.refresh(client)
    except Exception:
        db.rollback()
        logger.critical(
            "DB save failed after creating Drive folder %s for a new client. Attempting cleanup.", folder_id
        )
        try:
            storage.delete_folder(folder_id)
        except StorageError as cleanup_exc:
            logger.critical(
                "FAILED to clean up orphaned Drive folder %s - manual reconciliation required: %s",
                folder_id,
                cleanup_exc,
            )
        raise ApiError(500, "CLIENT_SAVE_FAILED", "Creating the client failed. Please retry.")

    return client


def get_client_or_404(db: DbSession, client_id: int) -> Client:
    client = db.query(Client).filter(Client.id == client_id).first()
    if client is None:
        raise not_found("Client not found.", code="CLIENT_NOT_FOUND")
    return client


def list_clients(db: DbSession, page: int, limit: int):
    page, limit = paginate_params(page, limit)

    album_counts = (
        db.query(Album.client_id, func.count(Album.id).label("cnt"))
        .group_by(Album.client_id)
        .subquery()
    )
    media_counts = (
        db.query(Media.client_id, func.count(Media.id).label("cnt"))
        .group_by(Media.client_id)
        .subquery()
    )

    query = (
        db.query(
            Client,
            func.coalesce(album_counts.c.cnt, 0).label("album_count"),
            func.coalesce(media_counts.c.cnt, 0).label("media_count"),
        )
        .outerjoin(album_counts, album_counts.c.client_id == Client.id)
        .outerjoin(media_counts, media_counts.c.client_id == Client.id)
        .order_by(Client.created_at.desc())
    )

    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()

    items = []
    for client, album_count, media_count in rows:
        items.append(
            {
                "id": client.id,
                "client_uuid": client.client_uuid,
                "client_name": client.client_name,
                "status": client.status,
                "has_password": bool(client.password_hash),
                "has_download_password": bool(client.download_password_hash),
                "created_at": client.created_at,
                "album_count": album_count,
                "media_count": media_count,
            }
        )
    return items, total, page, limit


def update_client(
    db: DbSession, client: Client, payload: ClientUpdateRequest, storage: StorageService
) -> Client:
    old_name = client.client_name
    name_changed = payload.client_name is not None and payload.client_name != old_name
    if payload.client_name is not None:
        client.client_name = payload.client_name

    # Keep the Drive folder's readable name in sync with the client name.
    # Only the readable portion changes - folder_uid (and therefore
    # drive_folder_id, which we never touch here) stays exactly the same.
    if name_changed and client.drive_folder_id:
        new_folder_name = build_client_folder_name(client.client_name, client.folder_uid)
        try:
            storage.rename_folder(client.drive_folder_id, new_folder_name)
        except StorageError as exc:
            logger.error("Failed to rename Drive folder for client %s: %s", client.id, exc)
            raise ApiError(502, "STORAGE_RENAME_FAILED", "Could not rename client storage folder. Please retry.")

    try:
        db.commit()
        db.refresh(client)
    except Exception:
        db.rollback()
        logger.critical(
            "DB save failed after renaming Drive folder %s for client %s. Attempting to roll back the rename.",
            client.drive_folder_id,
            client.id,
        )
        if name_changed and client.drive_folder_id:
            try:
                storage.rename_folder(client.drive_folder_id, build_client_folder_name(old_name, client.folder_uid))
            except StorageError as rollback_exc:
                logger.critical(
                    "FAILED to roll back Drive folder rename for client %s - manual reconciliation "
                    "required: %s",
                    client.id,
                    rollback_exc,
                )
        raise ApiError(500, "CLIENT_SAVE_FAILED", "Updating the client failed. Please retry.")

    return client


def change_client_password(db: DbSession, client: Client, new_password: str | None) -> Client:
    # None removes the gallery password entirely - password_hash/encrypted go
    # back to NULL and the gallery becomes passwordless again.
    _check_password_policy(db, new_password)
    client.password_hash = hash_password(new_password) if new_password else None
    client.password_encrypted = encrypt_password(new_password) if new_password else None
    db.commit()
    db.refresh(client)
    return client


def change_client_download_password(db: DbSession, client: Client, new_password: str | None) -> Client:
    _check_password_policy(db, new_password)
    client.download_password_hash = hash_password(new_password) if new_password else None
    client.download_password_encrypted = encrypt_password(new_password) if new_password else None
    # A changed or removed password invalidates previous download approvals.
    db.query(ClientSession).filter(ClientSession.client_id == client.id).update(
        {ClientSession.download_password_verified_at: None}, synchronize_session=False
    )
    db.commit()
    db.refresh(client)
    return client


def get_client_password_plaintexts(client: Client) -> dict[str, str | None]:
    """Decrypt the admin-viewable copies of the client's passwords.

    Clients created before encryption was introduced have no encrypted copy
    and will report None until an admin resets the password.
    """
    return {
        "gallery_password": decrypt_password(client.password_encrypted) if client.password_encrypted else None,
        "download_password": decrypt_password(client.download_password_encrypted)
        if client.download_password_encrypted
        else None,
    }


def set_client_status(db: DbSession, client: Client, status: str) -> Client:
    if status not in ("active", "disabled"):
        raise bad_request("Invalid status value.")
    client.status = status
    db.commit()
    db.refresh(client)
    return client


def regenerate_gallery_id(db: DbSession, client: Client) -> Client:
    client.client_uuid = str(uuid.uuid4())
    db.commit()
    db.refresh(client)
    return client


def delete_client(db: DbSession, client: Client, storage: StorageService) -> None:
    # Delete the Drive folder tree BEFORE the DB row: if Drive deletion
    # fails, we abort and keep the DB row so nothing is silently lost - the
    # admin can retry. Deleting the DB row first and failing on Drive after
    # would leave an orphaned folder with no record pointing at it.
    if client.drive_folder_id:
        try:
            storage.delete_folder(client.drive_folder_id)
        except StorageError as exc:
            logger.error("Failed to delete Drive folder for client %s: %s", client.id, exc)
            raise ApiError(502, "STORAGE_DELETE_FAILED", "Could not delete client storage. Please retry.")

    # Cascades to albums, media rows, and sessions via FK ondelete=CASCADE.
    db.delete(client)
    db.commit()
