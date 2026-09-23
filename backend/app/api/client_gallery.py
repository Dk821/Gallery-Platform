from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session as DbSession

from app.api.client_download_jobs import require_download_permission
from app.api.deps import get_current_client, get_current_client_session
from app.database.connection import get_db
from app.models.client import Client
from app.models.session import ClientSession
from app.api.media_streaming import stream_client_cover, stream_media_file, stream_media_thumbnail
from app.api.presenters import album_to_response, media_to_response
from app.schemas.errors import not_found
from app.schemas.pagination import build_page
from app.services.album_service import get_album_for_client_or_403, list_albums_for_client
from app.services.media_service import (
    get_media_for_client_or_403,
    get_media_selection_summary,
    list_media_for_client,
)
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService
from app.services.wishlist_service import get_wishlisted_media_ids

router = APIRouter(prefix="/api/client", tags=["client-gallery"])


@router.get("/gallery/access/{gallery_id}")
def get_gallery_access(
    gallery_id: str,
    db: DbSession = Depends(get_db),
):
    # PUBLIC "is there a door here?" check for the gallery landing flow.
    # Returns whether the gallery (identified by its unguessable link id)
    # requires a password before entrance. Security-neutral: it only ever
    # answers yes/no for a UUID the visitor already holds, never any other
    # client data. The frontend uses it to decide between showing the
    # password page and opening the gallery directly. Galleries without a
    # password (password_hash NULL) are opened straight away.
    client = db.query(Client).filter(Client.client_uuid == gallery_id).first()
    if client is None:
        raise not_found("Gallery not found.", code="GALLERY_NOT_FOUND")
    return {
        "success": True,
        "data": {
            "requires_password": client.password_hash is not None,
            "client_name": client.client_name,
        },
    }


@router.get("/gallery")
def get_gallery(
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    # High-level gallery info for the header of the client view. Deliberately
    # thin - album/media detail come from their own endpoints below.
    return {
        "success": True,
        "data": {
            "client_name": client.client_name,
            "client_uuid": client.client_uuid,
            "has_download_password": bool(client.download_password_hash),
            # Boolean only - never the Drive file id. The landing page uses it
            # to decide whether to request /gallery/cover or keep its default
            # hero, without firing a request that would just 404.
            "has_cover": bool(client.cover_drive_file_id),
        },
    }


@router.get("/gallery/cover")
def get_gallery_cover(
    request: Request,
    client: Client = Depends(get_current_client),
    storage: StorageService = Depends(get_storage_service),
):
    # The automatic cover of THE AUTHENTICATED client's gallery. No client or
    # gallery id is accepted anywhere in this request - the client is the one
    # the session cookie resolves to (get_current_client), so there is nothing
    # to tamper with and no way to ask for another client's cover. Read-only:
    # covers are generated automatically and have no manual management.
    return stream_client_cover(client, storage, request.headers.get("if-none-match"))


@router.get("/albums")
def list_albums(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    items, total, page, limit = list_albums_for_client(db, client.id, page, limit)
    return {
        "success": True,
        "data": build_page(items, page, limit, total),
    }


@router.get("/albums/{album_id}")
def get_album(
    album_id: int,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    # This 403-on-mismatch check is the load-bearing line for the platform's
    # core promise: "Client A cannot access Client B's album."
    album = get_album_for_client_or_403(db, album_id, client.id)
    return {"success": True, "data": album_to_response(album)}


@router.get("/media")
def list_media(
    album_id: int | None = Query(default=None),
    search: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    if album_id is not None:
        # Confirms the album itself belongs to this client before allowing
        # the album_id filter to be used - otherwise a client could pass any
        # album_id and learn whether it exists via an empty vs. non-empty result.
        # Also enforces expiry - an expired album's media isn't listable
        # even with a matching search term.
        get_album_for_client_or_403(db, album_id, client.id)

    rows, total, page, limit = list_media_for_client(db, client.id, album_id, page, limit, search)
    # ONE query for the whole page, however many photos it holds - never a
    # wishlist lookup per photo.
    wishlisted = get_wishlisted_media_ids(db, client.id, [m.id for m in rows])
    items = [media_to_response(m, is_wishlisted=m.id in wishlisted) for m in rows]
    return {
        "success": True,
        "data": build_page(items, page, limit, total),
    }


@router.get("/media/selection-summary")
def get_media_selection_summary_route(
    album_id: int | None = Query(default=None),
    search: str | None = Query(default=None, max_length=255),
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    """
    Backs "Select All" and the "~1.4 GB" size estimate: returns every
    matching media id + the total byte size, without ever pulling full
    metadata for items outside the current page (Part 4/7).
    """
    if album_id is not None:
        get_album_for_client_or_403(db, album_id, client.id)

    summary = get_media_selection_summary(db, client.id, album_id, search)
    return {"success": True, "data": summary}


@router.get("/media/{media_id}")
def get_media(
    media_id: int,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    media = get_media_for_client_or_403(db, media_id, client.id)
    wishlisted = get_wishlisted_media_ids(db, client.id, [media.id])
    return {"success": True, "data": media_to_response(media, is_wishlisted=media.id in wishlisted)}


@router.get("/media/{media_id}/thumbnail")
def get_media_thumbnail(
    media_id: int,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
    storage: StorageService = Depends(get_storage_service),
):
    media = get_media_for_client_or_403(db, media_id, client.id)
    return stream_media_thumbnail(media, storage)


@router.get("/media/{media_id}/view")
def view_media(
    media_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
    storage: StorageService = Depends(get_storage_service),
):
    # Used by the fullscreen photo viewer <img> and the <video> player src -
    # inline disposition so the browser renders it rather than downloading.
    # range_header lets <video> seek/scrub and is required for Safari to
    # play video at all.
    media = get_media_for_client_or_403(db, media_id, client.id)
    return stream_media_file(media, storage, disposition="inline", range_header=request.headers.get("range"))


@router.get("/media/{media_id}/download")
def download_media(
    media_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
    session: ClientSession = Depends(get_current_client_session),
    storage: StorageService = Depends(get_storage_service),
):
    media = get_media_for_client_or_403(db, media_id, client.id)
    require_download_permission(client, session)
    return stream_media_file(media, storage, disposition="attachment", range_header=request.headers.get("range"))
