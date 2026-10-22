from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_client
from app.api.presenters import album_comment_to_response
from app.database.connection import get_db
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.schemas.comment import AlbumCommentCreateRequest, AlbumCommentUpdateRequest
from app.services.album_service import get_album_for_client_or_403
from app.services.comment_service import (
    delete_comment_for_client,
    get_album_comment_for_client_or_403,
    list_comments_for_client,
    save_comment_for_client,
    update_comment_for_client,
)

router = APIRouter(prefix="/api/client", tags=["client-comments"])

# Every route here identifies the caller ONLY through get_current_client (the
# session cookie). No client id is accepted from the path, query or body, and
# every write verifies media -> album -> client ownership before touching the
# database - see services/comment_service.py.


def _log(db: DbSession, client_id: int, action: str, comment_id: int, request: Request) -> None:
    # Same AuditLog shape as every other route: who (user_type/user_id = this
    # client), what (action), on what (resource_type/resource_id = the note)
    # and when (created_at, server-set).
    db.add(
        AuditLog(
            user_type="client",
            user_id=client_id,
            action=action,
            resource_type="album_comment",
            resource_id=comment_id,
            ip_address=request.client.host if request.client else None,
        )
    )
    db.commit()


@router.get("/albums/{album_id}/comments")
def list_album_comments(
    album_id: int,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    """
    The notes this client wrote for this album, in book order.

    The album is resolved through get_album_for_client_or_403 first, which
    proves it belongs to this client AND enforces expiry - so this can only
    ever return the caller's own notes about their own, live album.
    """
    album = get_album_for_client_or_403(db, album_id, client.id)
    rows = list_comments_for_client(db, client.id, album.id)
    items = [album_comment_to_response(comment, media) for comment, media in rows]
    return {"success": True, "data": items}


@router.post("/albums/{album_id}/comments")
def save_album_comment(
    album_id: int,
    payload: AlbumCommentCreateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    """
    Adds (or edits) the client's note for one page of the book.

    There is at most one note per client per page, so submitting the same
    page twice edits the existing note instead of stacking duplicates. The
    response says which happened with `created`.
    """
    album = get_album_for_client_or_403(db, album_id, client.id)
    comment, media, created = save_comment_for_client(db, client, album, payload)
    _log(
        db,
        client.id,
        "comment_added" if created else "comment_updated",
        comment.id,
        request,
    )
    return {
        "success": True,
        "data": {**album_comment_to_response(comment, media).model_dump(), "created": created},
    }


@router.put("/comments/{comment_id}")
def update_album_comment(
    comment_id: int,
    payload: AlbumCommentUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    """Edits the text of one of the client's own notes."""
    comment = get_album_comment_for_client_or_403(db, comment_id, client.id)
    comment, media = update_comment_for_client(db, client, comment, payload)
    _log(db, client.id, "comment_updated", comment.id, request)
    return {"success": True, "data": album_comment_to_response(comment, media)}


@router.delete("/comments/{comment_id}")
def delete_album_comment(
    comment_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    """Removes one of the client's own notes."""
    comment = get_album_comment_for_client_or_403(db, comment_id, client.id)
    # The id is read BEFORE the delete: once the row is gone the ORM object
    # is expired and reading its id back would try to re-load a deleted row.
    deleted_id = comment.id
    delete_comment_for_client(db, comment)
    _log(db, client.id, "comment_deleted", deleted_id, request)
    return {"success": True, "data": None}
