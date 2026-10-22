import datetime

from pydantic import BaseModel, Field, field_validator

# A page note is feedback about a page of the book, not a document. 2000
# characters is generous for a caption-style note and still keeps a single
# row (and the admin modal) small.
MAX_COMMENT_LENGTH = 2000

# The two states a note can be in. "open" = the studio hasn't dealt with it
# yet; "resolved" = it has. Kept in sync with the DB enum in
# models/album_comment.py.
COMMENT_STATUS_OPEN = "open"
COMMENT_STATUS_RESOLVED = "resolved"
COMMENT_STATUSES = (COMMENT_STATUS_OPEN, COMMENT_STATUS_RESOLVED)


def _strip_and_validate_comment(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("comment cannot be blank")
    return value


class AlbumCommentCreateRequest(BaseModel):
    """
    A client adding/editing their note for ONE page of the Book View.

    client_id is deliberately NOT part of this payload - the server always
    takes it from the authenticated session (see api/deps.get_current_client),
    never from the request body.

    media_id identifies the item shown on the page (so the studio can see
    which photo the note is about) and page_number is the 1-based page
    (spread) number in the book's front-to-back order. The server verifies
    that the media really belongs to the album and to the caller before
    storing anything.
    """

    media_id: int
    page_number: int = Field(ge=1, le=100000)
    comment: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, v: str) -> str:
        return _strip_and_validate_comment(v)


class AlbumCommentUpdateRequest(BaseModel):
    """Editing the text of a note. The page itself never moves."""

    comment: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, v: str) -> str:
        return _strip_and_validate_comment(v)


class AdminAlbumCommentUpdateRequest(BaseModel):
    """
    Admin-side update. Both fields are optional (PATCH semantics): omit a
    field to leave it alone. The studio can resolve/reopen a note and, if
    the client wrote something confusing, correct the text themselves.
    """

    status: str | None = Field(default=None)
    comment: str | None = Field(default=None, min_length=1, max_length=MAX_COMMENT_LENGTH)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in COMMENT_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(COMMENT_STATUSES)}")
        return v

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _strip_and_validate_comment(v)


class AlbumCommentResponse(BaseModel):
    """
    One page note.

    media_id / media_file_name / media_file_type / has_thumbnail describe the
    item the note is about. They are NULL when the photo has since been
    deleted - the note survives that (ON DELETE SET NULL) and simply loses
    its picture. has_thumbnail is a boolean, never the raw provider file id.
    """

    id: int
    album_id: int
    client_id: int
    media_id: int | None
    page_number: int
    comment: str
    status: str
    media_file_name: str | None
    media_file_type: str | None
    has_thumbnail: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}
