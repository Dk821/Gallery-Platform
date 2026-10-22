from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.api.presenters import album_comment_to_response
from app.database.connection import get_db
from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.schemas.comment import AdminAlbumCommentUpdateRequest
from app.services.album_service import get_album_or_404
from app.services.comment_service import (
    delete_comment_admin,
    get_album_comment_or_404,
    list_comments_for_album_admin,
    update_comment_admin,
)

router = APIRouter(prefix="/api/admin", tags=["admin-comments"])

# Admin routes never enforce album expiry (an expired album is still
# manageable by the studio - see ARCHITECTURE.md), but they DO always confirm
# the album exists so a bogus id 404s instead of silently returning an empty
# list.


def _log(db: DbSession, admin_id: int, action: str, comment_id: int, request: Request) -> None:
    db.add(
        AuditLog(
            user_type="admin",
            user_id=admin_id,
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
    admin: Admin = Depends(get_current_admin),
):
    """
    Every client note on this album, in book order, with the photo each note
    is about so the studio can see the page the client was looking at.
    """
    album = get_album_or_404(db, album_id)
    rows = list_comments_for_album_admin(db, album.id)
    items = [album_comment_to_response(comment, media) for comment, media in rows]
    return {"success": True, "data": items}


@router.patch("/comments/{comment_id}")
def update_album_comment(
    comment_id: int,
    payload: AdminAlbumCommentUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    """Resolve / reopen a note, and optionally correct its text."""
    comment = get_album_comment_or_404(db, comment_id)
    comment, media = update_comment_admin(db, comment, payload)
    _log(db, admin.id, "comment_updated", comment.id, request)
    return {"success": True, "data": album_comment_to_response(comment, media)}


@router.delete("/comments/{comment_id}")
def delete_album_comment(
    comment_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    """Deletes a note outright."""
    comment = get_album_comment_or_404(db, comment_id)
    # The id is read BEFORE the delete: once the row is gone the ORM object
    # is expired and reading its id back would try to re-load a deleted row.
    deleted_id = comment.id
    delete_comment_admin(db, comment)
    _log(db, admin.id, "comment_deleted", deleted_id, request)
    return {"success": True, "data": None}
