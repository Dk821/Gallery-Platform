import datetime

from pydantic import BaseModel, Field, field_validator


class ClientCreateRequest(BaseModel):
    client_name: str = Field(min_length=1, max_length=255)
    # Floor of 4 matches the security policy's own floor (see
    # SecurityPolicyUpdateRequest) - the actual, possibly higher, minimum
    # is enforced in client_service.py against the studio's configured
    # min_client_password_length, which Pydantic has no DB access to check.
    password: str = Field(min_length=4, max_length=64)
    download_password: str | None = Field(default=None, min_length=4, max_length=64)

    @field_validator("client_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("client_name cannot be blank")
        return v


class ClientUpdateRequest(BaseModel):
    client_name: str | None = Field(default=None, min_length=1, max_length=255)


class ClientChangePasswordRequest(BaseModel):
    password: str = Field(min_length=4, max_length=64)


class ClientChangeDownloadPasswordRequest(BaseModel):
    password: str | None = Field(default=None, min_length=4, max_length=64)


class ClientResponse(BaseModel):
    id: int
    client_uuid: str
    client_name: str
    status: str
    has_download_password: bool
    created_at: datetime.datetime
    last_login_at: datetime.datetime | None
    gallery_url_path: str  # e.g. /gallery/<uuid> - frontend prepends its own domain

    model_config = {"from_attributes": True}


class ClientListItem(BaseModel):
    id: int
    client_uuid: str
    client_name: str
    status: str
    has_download_password: bool
    created_at: datetime.datetime
    album_count: int
    media_count: int

    model_config = {"from_attributes": True}
