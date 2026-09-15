from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.database.connection import get_db
from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.api.presenters import album_to_response, media_to_response
from app.schemas.album import AlbumCreateRequest, AlbumResponse, AlbumUpdateRequest
from app.schemas.pagination import build_page
from app.services.album_service import (
    create_album,
    delete_album,
    get_album_media_count,
    get_album_or_404,
    list_albums_for_admin,
    update_album,
)
from app.services.media_service import get_album_media_selection_summary, list_media_for_album_admin
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/admin/albums", tags=["admin-albums"])


def _log(db: DbSession, admin_id: int, action: str, resource_id: int, request: Request) -> None:
    db.add(
        AuditLog(
            user_type="admin",
            user_id=admin_id,
            action=action,
            resource_type="album",
            resource_id=resource_id,
            ip_address=request.client.host if request.client else None,
        )
    )
    db.commit()


@router.get("")
def list_albums_route(
    client_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    items, total, page, limit = list_albums_for_admin(db, client_id, page, limit)
    return {
        "success": True,
        "data": build_page(items, page, limit, total),
    }


@router.get("/{album_id}")
def get_album_route(
    album_id: int,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    album = get_album_or_404(db, album_id)
    media_count = get_album_media_count(db, album_id)
    return {"success": True, "data": album_to_response(album, media_count)}


@router.get("/{album_id}/media")
def list_album_media_route(
    album_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=255),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    # Confirms the album itself exists before listing its media - admin
    # access isn't scoped to a single client, but a bogus album_id should
    # still 404 rather than silently returning an empty page.
    get_album_or_404(db, album_id)
    rows, total, page, limit = list_media_for_album_admin(db, album_id, page, limit, search)
    items = [media_to_response(m) for m in rows]
    return {"success": True, "data": build_page(items, page, limit, total)}


@router.get("/{album_id}/media/selection-summary")
def get_album_media_selection_summary_route(
    album_id: int,
    search: str | None = Query(default=None, max_length=255),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    get_album_or_404(db, album_id)
    summary = get_album_media_selection_summary(db, album_id, search)
    return {"success": True, "data": summary}


@router.post("")
def create_album_route(
    payload: AlbumCreateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    album = create_album(db, payload, storage)
    _log(db, admin.id, "album_created", album.id, request)
    return {"success": True, "data": album_to_response(album)}


@router.put("/{album_id}")
def update_album_route(
    album_id: int,
    payload: AlbumUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    album = get_album_or_404(db, album_id)
    album = update_album(db, album, payload, storage)
    _log(db, admin.id, "album_updated", album.id, request)
    return {"success": True, "data": album_to_response(album)}


@router.delete("/{album_id}")
def delete_album_route(
    album_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    album = get_album_or_404(db, album_id)
    delete_album(db, album, storage)
    _log(db, admin.id, "album_deleted", album_id, request)
    return {"success": True, "data": None}
