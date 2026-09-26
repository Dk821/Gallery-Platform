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
    get_album_media_stats,
    get_album_or_404,
    list_albums_for_admin,
    update_album,
)
from app.services.media_service import get_album_media_selection_summary, list_media_for_album_admin
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService
from app.services.wishlist_service import (
    get_album_wishlist_counts,
    get_wishlisted_media_ids,
    validate_wishlist_filter,
)

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
    return {"success": True, "data": album_to_response(album, **get_album_media_stats(db, album.id))}


@router.get("/{album_id}/media")
def list_album_media_route(
    album_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=255),
    wishlist: str = Query(default="all", description="all | wishlisted | not_wishlisted"),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    # Confirms the album itself exists before listing its media - admin
    # access isn't scoped to a single client, but a bogus album_id should
    # still 404 rather than silently returning an empty page.
    album = get_album_or_404(db, album_id)
    wishlist_filter = validate_wishlist_filter(wishlist)
    rows, total, page, limit = list_media_for_album_admin(db, album_id, page, limit, search, wishlist_filter)
    # The wishlist filter is an SQL EXISTS in the query above; the per-item
    # flag is ONE batched lookup for the page (never one query per photo).
    # "Wishlisted" always means: by the client who owns this album.
    wishlisted = get_wishlisted_media_ids(db, album.client_id, [m.id for m in rows])
    items = [media_to_response(m, is_wishlisted=m.id in wishlisted) for m in rows]
    return {"success": True, "data": build_page(items, page, limit, total)}


@router.get("/{album_id}/media/selection-summary")
def get_album_media_selection_summary_route(
    album_id: int,
    search: str | None = Query(default=None, max_length=255),
    wishlist: str = Query(default="all", description="all | wishlisted | not_wishlisted"),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    get_album_or_404(db, album_id)
    # Must mirror the grid's filter: "Select All" feeds bulk delete/move, so
    # under the Wishlist tab it may only ever select the wishlisted items.
    summary = get_album_media_selection_summary(db, album_id, search, validate_wishlist_filter(wishlist))
    return {"success": True, "data": summary}


@router.get("/{album_id}/media/wishlist-counts")
def get_album_wishlist_counts_route(
    album_id: int,
    search: str | None = Query(default=None, max_length=255),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    # Backs the filter tabs' counts ("All 250 / Wishlist 38 / Not wishlisted
    # 212") - a single aggregate query, not one count per tab.
    get_album_or_404(db, album_id)
    return {"success": True, "data": get_album_wishlist_counts(db, album_id, search)}


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
