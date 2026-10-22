"""
Client page notes for the Book View ("comments").

A page note is a plain database row (models/album_comment.py) linking a
client, an album and ONE page (spread) of that album's Book View to the text
the client wrote about that page. Writing a note NEVER touches Google Drive -
nothing is copied, moved or re-uploaded - so this module has no StorageService
dependency at all.

SECURITY MODEL
--------------
The client is always the one resolved from the authenticated session cookie
(api/deps.get_current_client); no function here accepts a client id that came
from a request body, query string or path. Before a note is written the media
item on that page is resolved through the full ownership chain

    authenticated client -> media -> album -> album.client == client

so Client A can never write, read, edit or delete a note on Client B's book.
A mismatch - and "no such media" - both raise the same MEDIA_FORBIDDEN 403 the
rest of the client API uses, so probing ids reveals nothing about which ones
exist. The album itself is resolved through get_album_for_client_or_403, which
also enforces expiry: an expired album's notes are off-limits exactly like
every other client route (ALBUM_EXPIRED).

ONE NOTE PER PAGE
-----------------
A client has at most ONE note per page (the unique constraint on
(client_id, album_id, page_number)). Saving a page again EDITS that note
rather than stacking duplicates, which is what makes the Book View's
"submit, then turn to the next page" flow safe to retry.

ADMIN SIDE
----------
Admins can read every note of an album (including for expired albums -
expiry is a client-facing rule only, see ARCHITECTURE.md), resolve/reopen a
note, correct its text and delete it. Those routes live in api/admin_comments.py.
"""

import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.models.album import Album
from app.models.album_comment import AlbumComment
from app.models.client import Client
from app.models.media import Media
from app.schemas.comment import (
    AdminAlbumCommentUpdateRequest,
    AlbumCommentCreateRequest,
    AlbumCommentUpdateRequest,
    COMMENT_STATUS_OPEN,
)
from app.schemas.errors import forbidden, not_found

logger = logging.getLogger("gallery.comments")


# ---- shared helpers ---------------------------------------------------------


def _resolve_media_for_client(db: DbSession, media_id: int, album: Album, client_id: int) -> Media:
    """
    The ownership chain described in the module docstring. The album has
    already been resolved (and its expiry checked) by the caller, so all that
    is left is to prove the media really is an item of THAT album owned by
    THIS client.
    """
    media = db.query(Media).filter(Media.id == media_id).first()
    if media is None or media.client_id != client_id or media.album_id != album.id:
        raise forbidden("You do not have access to this media item.", code="MEDIA_FORBIDDEN")
    return media


def get_album_comment_or_404(db: DbSession, comment_id: int) -> AlbumComment:
    """Admin-side lookup. A note that doesn't exist is a plain 404."""
    comment = db.query(AlbumComment).filter(AlbumComment.id == comment_id).first()
    if comment is None:
        raise not_found("Comment not found.", code="COMMENT_NOT_FOUND")
    return comment


def get_album_comment_for_client_or_403(
    db: DbSession, comment_id: int, client_id: int
) -> AlbumComment:
    """
    Client-side lookup. A note belonging to somebody else is reported exactly
    like a note that doesn't exist (404 COMMENT_NOT_FOUND), so a client can
    never confirm that another client's note id is real.
    """
    comment = db.query(AlbumComment).filter(AlbumComment.id == comment_id).first()
    if comment is None or comment.client_id != client_id:
        raise not_found("Comment not found.", code="COMMENT_NOT_FOUND")
    return comment


def get_album_comment_count(db: DbSession, album_id: int, client_id: int | None = None) -> int:
    """
    How many notes one album has - ONE aggregate query.

    Pass client_id to count only that client's notes (the client-facing
    view); leave it out for the studio's view, which counts every note on
    the album.
    """
    query = db.query(func.count(AlbumComment.id)).filter(AlbumComment.album_id == album_id)
    if client_id is not None:
        query = query.filter(AlbumComment.client_id == client_id)
    return int(query.scalar() or 0)


def get_album_comment_counts(db: DbSession, album_ids: list[int]) -> dict[int, int]:
    """
    How many notes each of these albums has - ONE grouped query for the whole
    page of albums (never a count per album, which would be an N+1).

    Used by the album list to badge the albums that have client feedback on
    them. The count is the studio's own view of feedback, so it is the
    number of notes regardless of their resolved/open status.
    """
    if not album_ids:
        return {}
    rows = (
        db.query(AlbumComment.album_id, func.count(AlbumComment.id))
        .filter(AlbumComment.album_id.in_(album_ids))
        .group_by(AlbumComment.album_id)
        .all()
    )
    return {album_id: int(count) for album_id, count in rows}


# ---- client: read ------------------------------------------------------------


def list_comments_for_client(
    db: DbSession, client_id: int, album_id: int
) -> list[tuple[AlbumComment, Media | None]]:
    """
    Every note this client wrote for this album, in book order (page number
    ascending), together with the item the note is about (None when that
    photo has since been deleted - the note survives, it just loses its
    picture).

    ONE query: the join is an outer join so a note whose media is gone still
    comes back. The query is keyed on the note's own client_id, so it can
    only ever return the caller's own rows.
    """
    return (
        db.query(AlbumComment, Media)
        .outerjoin(Media, Media.id == AlbumComment.media_id)
        .filter(AlbumComment.client_id == client_id, AlbumComment.album_id == album_id)
        .order_by(AlbumComment.page_number.asc(), AlbumComment.id.asc())
        .all()
    )


# ---- client: write ----------------------------------------------------------


def save_comment_for_client(
    db: DbSession,
    client: Client,
    album: Album,
    payload: AlbumCommentCreateRequest,
) -> tuple[AlbumComment, Media, bool]:
    """
    Adds OR edits the client's note for one page. Returns (comment, media,
    created).

    `created` is False when the page already had a note and its text was
    updated instead - the route only writes an audit-log line for a real
    change.

    Editing a note re-opens it: the studio marked it resolved against the
    previous wording, and new wording is new feedback that needs their
    attention again.
    """
    media = _resolve_media_for_client(db, payload.media_id, album, client.id)

    comment = (
        db.query(AlbumComment)
        .filter(
            AlbumComment.client_id == client.id,
            AlbumComment.album_id == album.id,
            AlbumComment.page_number == payload.page_number,
        )
        .first()
    )

    if comment is None:
        comment = AlbumComment(
            album_id=album.id,
            client_id=client.id,
            media_id=media.id,
            page_number=payload.page_number,
            comment=payload.comment,
            status=COMMENT_STATUS_OPEN,
        )
        db.add(comment)
        created = True
    else:
        comment.comment = payload.comment
        comment.media_id = media.id
        comment.status = COMMENT_STATUS_OPEN
        created = False

    try:
        db.commit()
    except IntegrityError:
        # Two submissions for the same page raced past the lookup above; the
        # unique constraint let exactly one of them win. The loser becomes an
        # edit of the winning row instead of a duplicate.
        db.rollback()
        comment = (
            db.query(AlbumComment)
            .filter(
                AlbumComment.client_id == client.id,
                AlbumComment.album_id == album.id,
                AlbumComment.page_number == payload.page_number,
            )
            .first()
        )
        if comment is None:
            raise
        comment.comment = payload.comment
        comment.media_id = media.id
        comment.status = COMMENT_STATUS_OPEN
        db.commit()
        created = False

    db.refresh(comment)
    return comment, media, created


def update_comment_for_client(
    db: DbSession, client: Client, comment: AlbumComment, payload: AlbumCommentUpdateRequest
) -> tuple[AlbumComment, Media | None]:
    """
    Edits the text of the client's own note. The page never moves.

    Re-opens the note: new wording is new feedback for the studio.
    """
    comment.comment = payload.comment
    comment.status = COMMENT_STATUS_OPEN
    db.commit()
    db.refresh(comment)
    media = (
        db.query(Media).filter(Media.id == comment.media_id).first()
        if comment.media_id is not None
        else None
    )
    return comment, media


def delete_comment_for_client(db: DbSession, comment: AlbumComment) -> None:
    """Removes the client's own note from a page."""
    db.delete(comment)
    db.commit()


# ---- admin: read / write ----------------------------------------------------


def list_comments_for_album_admin(db: DbSession, album_id: int) -> list[tuple[AlbumComment, Media | None]]:
    """
    Every note on an album, in book order, with the media item each one is
    about (None when that photo has since been deleted - the note survives,
    it just loses its picture).

    ONE query: the join is an outer join so a note whose media is gone still
    comes back.
    """
    return (
        db.query(AlbumComment, Media)
        .outerjoin(Media, Media.id == AlbumComment.media_id)
        .filter(AlbumComment.album_id == album_id)
        .order_by(AlbumComment.page_number.asc(), AlbumComment.id.asc())
        .all()
    )


def update_comment_admin(
    db: DbSession, comment: AlbumComment, payload: AdminAlbumCommentUpdateRequest
) -> tuple[AlbumComment, Media | None]:
    """
    Admin-side edit (resolve / reopen, and optionally fix the text). Both
    fields are optional - a field left out of the request is not touched.
    """
    if "status" in payload.model_fields_set and payload.status is not None:
        comment.status = payload.status
    if "comment" in payload.model_fields_set and payload.comment is not None:
        comment.comment = payload.comment
    db.commit()
    db.refresh(comment)
    media = (
        db.query(Media).filter(Media.id == comment.media_id).first()
        if comment.media_id is not None
        else None
    )
    return comment, media


def delete_comment_admin(db: DbSession, comment: AlbumComment) -> None:
    """Admin-side delete of a note."""
    db.delete(comment)
    db.commit()
