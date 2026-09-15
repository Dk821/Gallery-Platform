import datetime

from pydantic import BaseModel, Field, field_validator


class AlbumCreateRequest(BaseModel):
    client_id: int
    album_name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    expires_at: datetime.datetime | None = None

    @field_validator("album_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("album_name cannot be blank")
        return v


class AlbumUpdateRequest(BaseModel):
    album_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    # Three-state: omit the field entirely = don't touch it; explicit null =
    # clear the expiry (album never expires); a datetime = set/change it.
    # Pydantic can't distinguish "field absent" from "field explicitly None"
    # with a plain Optional default, so callers use model_fields_set (see
    # album_service.update_album) to tell the two apart.
    expires_at: datetime.datetime | None = None


class AlbumResponse(BaseModel):
    id: int
    album_uuid: str
    client_id: int
    album_name: str
    description: str | None
    status: str
    expires_at: datetime.datetime | None
    created_at: datetime.datetime
    media_count: int = 0

    model_config = {"from_attributes": True}
