import datetime

from pydantic import BaseModel, Field, field_validator


class ClientCreateRequest(BaseModel):
    client_name: str = Field(min_length=1, max_length=255)
    # OPTIONAL gallery password. When empty/None the gallery is created
    # without password protection and clients open it directly. When set,
    # the minimum (and policy-enforced) length check below applies - the
    # actual, possibly higher, minimum is enforced in client_service.py
    # against the studio's configured min_client_password_length, which
    # Pydantic has no DB access to check.
    password: str | None = Field(default=None, min_length=1, max_length=64)
    download_password: str | None = Field(default=None, min_length=4, max_length=64)

    @field_validator("client_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("client_name cannot be blank")
        return v

    @field_validator("password", mode="before")
    @classmethod
    def password_empty_to_none(cls, v):
        # An empty/missing password means "no gallery password".
        if v is None or v == "":
            return None
        return v


class ClientUpdateRequest(BaseModel):
    client_name: str | None = Field(default=None, min_length=1, max_length=255)


class ClientChangePasswordRequest(BaseModel):
    # None = remove the gallery password entirely (gallery becomes
    # passwordless), mirroring ClientChangeDownloadPasswordRequest.
    password: str | None = Field(default=None, min_length=4, max_length=64)


class ClientChangeDownloadPasswordRequest(BaseModel):
    password: str | None = Field(default=None, min_length=4, max_length=64)


class ClientResponse(BaseModel):
    id: int
    client_uuid: str
    client_name: str
    status: str
    has_password: bool
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
    has_password: bool
    has_download_password: bool
    created_at: datetime.datetime
    album_count: int
    media_count: int

    model_config = {"from_attributes": True}
