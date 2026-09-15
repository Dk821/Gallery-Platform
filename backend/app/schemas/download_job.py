import datetime

from pydantic import BaseModel, Field


class DownloadJobCreateRequest(BaseModel):
    # Omitted/empty = "download the whole album" (Part 8). A non-empty list
    # = "download just these" (Part 7, the selection the user made).
    media_ids: list[int] | None = Field(default=None, max_length=5000)


class DownloadJobVerifyPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class DownloadJobResponse(BaseModel):
    """
    Deliberately excludes zip_path (internal disk path) - the client only
    ever gets a job id and downloads the finished file through
    /download-jobs/{id}/file, same principle as never exposing a Drive id.
    """

    id: int
    status: str
    total_files: int
    completed_files: int
    total_bytes: int
    completed_bytes: int
    error_message: str | None
    has_password: bool
    created_at: datetime.datetime
    completed_at: datetime.datetime | None
    expires_at: datetime.datetime | None

    model_config = {"from_attributes": True}
