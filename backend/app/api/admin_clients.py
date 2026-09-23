from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.database.connection import get_db
from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.api.presenters import media_to_response
from app.schemas.client import (
    ClientChangeDownloadPasswordRequest,
    ClientChangePasswordRequest,
    ClientCreateRequest,
    ClientResponse,
    ClientUpdateRequest,
)
from app.schemas.pagination import build_page
from app.services.client_service import (
    change_client_download_password,
    change_client_password,
    create_client,
    delete_client,
    get_client_or_404,
    get_client_password_plaintexts,
    list_clients,
    regenerate_gallery_id,
    set_client_status,
    update_client,
)
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService
from app.services.wishlist_service import get_album_of_client_or_404, list_wishlist_for_admin

router = APIRouter(prefix="/api/admin/clients", tags=["admin-clients"])


def _log(db: DbSession, admin_id: int, action: str, resource_id: int, request: Request) -> None:
    db.add(
        AuditLog(
            user_type="admin",
            user_id=admin_id,
            action=action,
            resource_type="client",
            resource_id=resource_id,
            ip_address=request.client.host if request.client else None,
        )
    )
    db.commit()


def _to_response(client) -> ClientResponse:
    return ClientResponse(
        id=client.id,
        client_uuid=client.client_uuid,
        client_name=client.client_name,
        status=client.status,
        has_password=bool(client.password_hash),
        has_download_password=bool(client.download_password_hash),
        created_at=client.created_at,
        last_login_at=client.last_login_at,
        gallery_url_path=f"/gallery/{client.client_uuid}",
    )


@router.get("")
def list_clients_route(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    items, total, page, limit = list_clients(db, page, limit)
    return {
        "success": True,
        "data": build_page(items, page, limit, total),
    }


@router.post("")
def create_client_route(
    payload: ClientCreateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    client = create_client(db, payload, storage)
    _log(db, admin.id, "client_created", client.id, request)
    return {"success": True, "data": _to_response(client)}


@router.get("/{client_id}")
def get_client_route(
    client_id: int,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    client = get_client_or_404(db, client_id)
    return {"success": True, "data": _to_response(client)}


@router.get("/{client_id}/wishlist")
def get_client_wishlist_route(
    client_id: int,
    album_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    # What this client has wishlisted, optionally narrowed to one album.
    # Read-only and admin-only (get_current_admin): admins see the client's
    # selections but cannot change them. A bogus client is a 404, and an
    # album_id must belong to THIS client - otherwise it 404s rather than
    # quietly returning another client's album's data.
    get_client_or_404(db, client_id)
    if album_id is not None:
        get_album_of_client_or_404(db, album_id, client_id)
    rows, total, page, limit = list_wishlist_for_admin(db, client_id, album_id, page, limit)
    items = [media_to_response(m, is_wishlisted=True) for m in rows]
    return {"success": True, "data": build_page(items, page, limit, total)}


@router.put("/{client_id}")
def update_client_route(
    client_id: int,
    payload: ClientUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    client = get_client_or_404(db, client_id)
    client = update_client(db, client, payload, storage)
    _log(db, admin.id, "client_updated", client.id, request)
    return {"success": True, "data": _to_response(client)}


@router.delete("/{client_id}")
def delete_client_route(
    client_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    client = get_client_or_404(db, client_id)
    delete_client(db, client, storage)
    _log(db, admin.id, "client_deleted", client_id, request)
    return {"success": True, "data": None}


@router.get("/{client_id}/passwords")
def get_client_passwords_route(
    client_id: int,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    client = get_client_or_404(db, client_id)
    return {"success": True, "data": get_client_password_plaintexts(client)}


@router.post("/{client_id}/change-password")
def change_password_route(
    client_id: int,
    payload: ClientChangePasswordRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    client = get_client_or_404(db, client_id)
    client = change_client_password(db, client, payload.password)
    _log(db, admin.id, "client_password_removed" if payload.password is None else "client_password_changed", client.id, request)
    return {"success": True, "data": _to_response(client)}


@router.post("/{client_id}/change-download-password")
def change_download_password_route(
    client_id: int,
    payload: ClientChangeDownloadPasswordRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    client = get_client_or_404(db, client_id)
    client = change_client_download_password(db, client, payload.password)
    _log(db, admin.id, "client_download_password_changed", client.id, request)
    return {"success": True, "data": _to_response(client)}


@router.post("/{client_id}/disable")
def disable_client_route(
    client_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    client = get_client_or_404(db, client_id)
    client = set_client_status(db, client, "disabled")
    _log(db, admin.id, "client_disabled", client.id, request)
    return {"success": True, "data": _to_response(client)}


@router.post("/{client_id}/enable")
def enable_client_route(
    client_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    client = get_client_or_404(db, client_id)
    client = set_client_status(db, client, "active")
    _log(db, admin.id, "client_enabled", client.id, request)
    return {"success": True, "data": _to_response(client)}


@router.post("/{client_id}/regenerate-gallery-id")
def regenerate_gallery_id_route(
    client_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    client = get_client_or_404(db, client_id)
    client = regenerate_gallery_id(db, client)
    _log(db, admin.id, "client_gallery_id_regenerated", client.id, request)
    return {"success": True, "data": _to_response(client)}
