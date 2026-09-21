from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_client
from app.api.presenters import media_to_response
from app.database.connection import get_db
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.schemas.pagination import build_page
from app.services.album_service import get_album_for_client_or_403
from app.services.wishlist_service import add_to_wishlist, list_wishlist_for_client, remove_from_wishlist

router = APIRouter(prefix="/api/client/wishlist", tags=["client-wishlist"])

# Every route here identifies the caller ONLY through get_current_client (the
# session cookie). No client id is accepted from the path, query or body, and
# add/remove verify media -> album -> client ownership in wishlist_service
# before touching anything - see that module's docstring.


def _log(db: DbSession, client_id: int, action: str, media_id: int, request: Request) -> None:
    # Same AuditLog shape as every other route: who (user_type/user_id = this
    # client), what (action), on what (resource_type/resource_id = the media
    # item; its album is media.album_id) and when (created_at, server-set).
    db.add(
        AuditLog(
            user_type="client",
            user_id=client_id,
            action=action,
            resource_type="media",
            resource_id=media_id,
            ip_address=request.client.host if request.client else None,
        )
    )
    db.commit()


@router.get("")
def list_wishlist(
    album_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    if album_id is not None:
        # Same guard as GET /api/client/media: the album filter must belong
        # to this client (and not be expired) before it may be used.
        get_album_for_client_or_403(db, album_id, client.id)

    rows, total, page, limit = list_wishlist_for_client(db, client.id, album_id, page, limit)
    # Everything in this listing is wishlisted by definition.
    items = [media_to_response(m, is_wishlisted=True) for m in rows]
    return {"success": True, "data": build_page(items, page, limit, total)}


@router.post("/{media_id}")
def add_media_to_wishlist(
    media_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    media, created = add_to_wishlist(db, client, media_id)
    if created:
        # Only a real change is audited - re-adding something already on the
        # wishlist (double click, retry) writes neither a row nor a log line.
        _log(db, client.id, "wishlist_added", media.id, request)
    return {"success": True, "data": {"media_id": media.id, "is_wishlisted": True}}


@router.delete("/{media_id}")
def remove_media_from_wishlist(
    media_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    media, removed = remove_from_wishlist(db, client, media_id)
    if removed:
        _log(db, client.id, "wishlist_removed", media.id, request)
    return {"success": True, "data": {"media_id": media.id, "is_wishlisted": False}}
