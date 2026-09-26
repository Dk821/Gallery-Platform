import datetime

from pydantic import BaseModel, Field, field_validator


class MediaResponse(BaseModel):
    id: int
    file_uuid: str
    album_id: int
    file_name: str
    title: str | None
    description: str | None
    file_type: str
    mime_type: str
    file_size: int
    # Deliberately a boolean, not the raw Drive file id - the client never
    # needs the internal provider reference, only whether a thumbnail
    # exists, since it always fetches the image via our own
    # /media/{id}/thumbnail endpoint (keyed by our own id).
    has_thumbnail: bool
    status: str
    created_at: datetime.datetime
    # Whether the OWNING client has wishlisted this item. Filled in by the
    # list/detail routes from one batched lookup per page (never a query per
    # item - see wishlist_service.get_wishlisted_media_ids). Defaults to False
    # so every place that builds a MediaResponse without wishlist context
    # (e.g. right after an upload/edit) stays valid.
    is_wishlisted: bool = False

    model_config = {"from_attributes": True}


class MediaUpdateRequest(BaseModel):
    """
    All fields optional - PATCH semantics. Following the same convention
    already used by AlbumUpdateRequest: a field left out (None) means
    "don't change it"; an empty string is a valid value and clears a
    nullable field like title/description.
    """

    file_name: str | None = Field(default=None, min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("file_name")
    @classmethod
    def strip_file_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("file_name cannot be blank")
        return v


class MediaMoveRequest(BaseModel):
    target_album_id: int


class BulkDeleteRequest(BaseModel):
    media_ids: list[int] = Field(min_length=1, max_length=500)


class BulkMoveRequest(BaseModel):
    media_ids: list[int] = Field(min_length=1, max_length=500)
    target_album_id: int


class CreateUploadSessionRequest(BaseModel):
    """
    Pre-creates an UploadSession before the browser starts sending the
    multipart file (POST /upload-session).  Eliminates the race condition
    where the frontend polls /upload-status before the backend has
    buffered the upload and created the session row.
    """

    album_id: int
    upload_id: str
    filename: str
    file_size: int


class CompleteUploadRequest(BaseModel):
    """
    Sent by the browser once it has finished PUTting the file's bytes
    directly to the Google Drive resumable session URL it got back from
    POST /upload-session. This server never saw those bytes - it
    re-confirms the file with Drive itself (storage.get_file /
    storage.download for a signature check) rather than trusting these
    client-reported values for the actual Media record.
    """

    upload_id: str
    drive_file_id: str
    # What the browser observed Drive's own final response say - used only
    # to detect a badly mismatched client, never written to the DB as-is;
    # the authoritative size/mime always come from storage.get_file().
    reported_size: int
    reported_mime_type: str | None = None


class UploadProgressRequest(BaseModel):
    """
    Periodic, best-effort progress ping from the browser while it's
    PUTting bytes directly to Drive (Section 8) - this server is no
    longer in that data path, so it can only know real progress if the
    browser tells it. Never trusted for anything beyond display (the
    authoritative "did this file actually land in Drive" check happens in
    complete_direct_upload, independent of whatever progress was reported
    here).
    """

    bytes_uploaded: int


class UploadStatusResponse(BaseModel):
    """
    Polled by the frontend to show real Drive-transfer progress
    (Section 8) - separate from the browser's own upload progress, which
    only reflects bytes sent to OUR server, not bytes actually confirmed
    by Google Drive. Never includes google_drive_file_id or any other
    internal storage reference (Section 13).
    """

    upload_id: str
    status: str
    total_bytes: int
    bytes_uploaded: int
    percentage: int
    media_id: int | None
    error_code: str | None
    error_message: str | None


class DirectUploadSessionResponse(UploadStatusResponse):
    """
    Response for POST /upload-session: everything UploadStatusResponse
    already carries, plus the Drive resumable session URL the browser
    PUTs its bytes to directly. `upload_url` is None whenever it isn't
    the browser's turn to have one (e.g. an idempotent replay of an
    already-completed upload) - the frontend should treat a missing url
    as "nothing to upload, check status/media_id instead."
    """

    upload_url: str | None


class UploadSessionListItem(BaseModel):
    """
    One row of the "recent uploads" list the Uploads page restores after a
    page refresh (the server persists every upload in upload_sessions, but
    without this the frontend's in-memory list would be gone forever).
    Includes enough album/client context to display the item without the
    in-memory File object that a pre-refresh session no longer has.
    """

    upload_id: str
    filename: str
    album_id: int
    album_name: str
    client_name: str
    status: str
    total_bytes: int
    bytes_uploaded: int
    percentage: int
    media_id: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime.datetime
