"""
Client wishlist ("favourites").

A wishlist entry is a plain database row (models/media_wishlist.py) linking a
client to a media item. Marking a photo NEVER touches Google Drive - nothing
is copied, moved or re-uploaded - so this module has no StorageService
dependency at all.

SECURITY MODEL
--------------
The client is always the one resolved from the authenticated session cookie
(api/deps.get_current_client); no function here accepts a client id that came
from a request body, query string or path. Before an entry is added OR removed
the media item is resolved through the full ownership chain

    authenticated client -> media -> album -> album.client == client

so Client A can never wishlist, un-wishlist or read Client B's media. A
mismatch - and "no such media" - both raise the same MEDIA_FORBIDDEN 403 the
rest of the client API uses (see media_service.get_media_for_client_or_403),
so probing ids reveals nothing about which ones exist. An expired album's
media is off-limits exactly like every other client route (ALBUM_EXPIRED).

QUERY SHAPE
-----------
Everything here is set-based. "Which of these 60 photos are wishlisted" is ONE
`IN` query for the whole page (get_wishlisted_media_ids), and the admin
wishlist filter is an SQL EXISTS clause (media_is_wishlisted_clause) - never a
per-photo lookup - so the query count does not grow with the number of photos.

This module deliberately does not import media_service (media_service imports
the helpers below for the admin filter); the shared album-expiry rule lives in
album_service for the same reason.
"""

import logging

from sqlalchemy import and_, case, exists, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.models.album import Album
from app.models.client import Client
from app.models.media import Media
from app.models.media_wishlist import MediaWishlist
from app.schemas.errors import bad_request, forbidden, not_found
from app.schemas.pagination import paginate_params
from app.services.album_service import album_not_expired_clause, check_album_not_expired

logger = logging.getLogger("gallery.wishlist")

# Admin album filter values (?wishlist=...).
WISHLIST_FILTER_ALL = "all"
WISHLIST_FILTER_WISHLISTED = "wishlisted"
WISHLIST_FILTER_NOT_WISHLISTED = "not_wishlisted"
WISHLIST_FILTERS = (WISHLIST_FILTER_ALL, WISHLIST_FILTER_WISHLISTED, WISHLIST_FILTER_NOT_WISHLISTED)


# ---- shared query helpers ---------------------------------------------------


def media_is_wishlisted_clause():
    """
    Correlated `EXISTS (... media_wishlists ...)` for the Media row of the
    enclosing query. Matching on client_id == Media.client_id as well as
    media_id keeps the lookup on the (client_id, media_id) unique index and
    means a stray row for some other client can never mark a media item as
    wishlisted by its owner.
    """
    return exists().where(
        and_(MediaWishlist.media_id == Media.id, MediaWishlist.client_id == Media.client_id)
    )


def apply_wishlist_filter(query, wishlist_filter: str):
    """Applies the admin ?wishlist= filter to a query over Media. Database-level, no per-row work."""
    if wishlist_filter == WISHLIST_FILTER_WISHLISTED:
        return query.filter(media_is_wishlisted_clause())
    if wishlist_filter == WISHLIST_FILTER_NOT_WISHLISTED:
        return query.filter(~media_is_wishlisted_clause())
    return query


def validate_wishlist_filter(value: str | None) -> str:
    value = value or WISHLIST_FILTER_ALL
    if value not in WISHLIST_FILTERS:
        raise bad_request(
            f"wishlist must be one of: {', '.join(WISHLIST_FILTERS)}.", code="INVALID_WISHLIST_FILTER"
        )
    return value


def get_wishlisted_media_ids(db: DbSession, client_id: int, media_ids: list[int]) -> set[int]:
    """
    Which of `media_ids` this client has wishlisted - ONE query for the whole
    list, however long it is. This is what lets a paginated media list carry
    an `is_wishlisted` flag per item without a query per photo.
    """
    if not media_ids:
        return set()
    rows = (
        db.query(MediaWishlist.media_id)
        .filter(MediaWishlist.client_id == client_id, MediaWishlist.media_id.in_(media_ids))
        .all()
    )
    return {r[0] for r in rows}


# ---- client: add / remove ---------------------------------------------------


def _resolve_media_for_client(db: DbSession, media_id: int, client_id: int) -> Media:
    """
    The ownership chain described in the module docstring, in ONE query
    (media JOIN album). Returns the Media only if the authenticated client
    owns both it and its album, and the album hasn't expired.
    """
    row = (
        db.query(Media, Album)
        .join(Album, Album.id == Media.album_id)
        .filter(Media.id == media_id)
        .first()
    )
    if row is None:
        raise forbidden("You do not have access to this media item.", code="MEDIA_FORBIDDEN")
    media, album = row
    if album.client_id != client_id or media.client_id != client_id:
        raise forbidden("You do not have access to this media item.", code="MEDIA_FORBIDDEN")
    check_album_not_expired(album)
    return media


def add_to_wishlist(db: DbSession, client: Client, media_id: int) -> tuple[Media, bool]:
    """
    Idempotent. Returns (media, created): created is False when the media was
    already wishlisted (no duplicate row, nothing to audit-log).
    """
    media = _resolve_media_for_client(db, media_id, client.id)

    already = (
        db.query(MediaWishlist.id)
        .filter(MediaWishlist.client_id == client.id, MediaWishlist.media_id == media.id)
        .first()
    )
    if already is not None:
        return media, False

    db.add(MediaWishlist(client_id=client.id, media_id=media.id))
    try:
        db.commit()
    except IntegrityError:
        # Two identical requests raced past the check above; the unique
        # constraint let exactly one of them win. The loser is a no-op.
        db.rollback()
        return media, False
    return media, True


def remove_from_wishlist(db: DbSession, client: Client, media_id: int) -> tuple[Media, bool]:
    """Idempotent. Returns (media, removed): removed is False if it wasn't wishlisted."""
    media = _resolve_media_for_client(db, media_id, client.id)
    deleted = (
        db.query(MediaWishlist)
        .filter(MediaWishlist.client_id == client.id, MediaWishlist.media_id == media.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return media, deleted > 0


# ---- listings ---------------------------------------------------------------


def _wishlisted_media_query(db: DbSession, client_id: int, album_id: int | None):
    """
    Media this client has wishlisted, newest wishlist entry first. The join is
    keyed on the wishlist row's own client_id, and Media.client_id is checked
    as well - two independent ownership conditions, both from the server side.
    """
    query = (
        db.query(Media)
        .join(
            MediaWishlist,
            and_(MediaWishlist.media_id == Media.id, MediaWishlist.client_id == client_id),
        )
        .filter(Media.client_id == client_id)
    )
    if album_id is not None:
        query = query.filter(Media.album_id == album_id)
    return query.order_by(MediaWishlist.created_at.desc(), MediaWishlist.id.desc())


def list_wishlist_for_client(
    db: DbSession, client_id: int, album_id: int | None, page: int, limit: int
):
    """
    GET /api/client/wishlist. Media in an EXPIRED album is excluded, like every
    other cross-album client listing. If album_id is given the caller has
    already verified it belongs to this client (get_album_for_client_or_403).
    """
    page, limit = paginate_params(page, limit)
    query = _wishlisted_media_query(db, client_id, album_id).join(Album, Album.id == Media.album_id)
    query = query.filter(album_not_expired_clause())
    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return rows, total, page, limit


def list_wishlist_for_admin(
    db: DbSession, client_id: int, album_id: int | None, page: int, limit: int
):
    """
    GET /api/admin/clients/{client_id}/wishlist. Admins see every wishlisted
    item, including ones in expired albums (expiry is a client-facing rule
    only - see ARCHITECTURE.md). The caller has already 404'd an unknown
    client, and an album_id that doesn't belong to that client.
    """
    page, limit = paginate_params(page, limit)
    query = _wishlisted_media_query(db, client_id, album_id)
    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return rows, total, page, limit


def get_album_wishlist_counts(db: DbSession, album_id: int, search: str | None = None) -> dict:
    """
    Backs the admin filter's counts ("All 250 / Wishlist 38 / Not wishlisted
    212") in ONE aggregate query - not a count per filter, and never a scan of
    Python objects.
    """
    query = db.query(
        func.count(Media.id),
        func.coalesce(func.sum(case((media_is_wishlisted_clause(), 1), else_=0)), 0),
    ).filter(Media.album_id == album_id)
    if search:
        query = query.filter(Media.file_name.ilike(f"%{search.strip()}%"))
    total, wishlisted = query.one()
    total, wishlisted = int(total or 0), int(wishlisted or 0)
    return {
        WISHLIST_FILTER_ALL: total,
        WISHLIST_FILTER_WISHLISTED: wishlisted,
        WISHLIST_FILTER_NOT_WISHLISTED: total - wishlisted,
    }


def get_album_of_client_or_404(db: DbSession, album_id: int, client_id: int) -> Album:
    """Admin-side: an album_id filter must belong to the client being queried."""
    album = db.query(Album).filter(Album.id == album_id, Album.client_id == client_id).first()
    if album is None:
        raise not_found("Album not found for this client.", code="ALBUM_NOT_FOUND")
    return album
