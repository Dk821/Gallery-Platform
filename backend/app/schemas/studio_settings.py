import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class StudioSettingsResponse(BaseModel):
    studio_name: str | None
    contact_email: str | None
    min_client_password_length: int
    download_link_ttl_hours: int
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class StudioProfileUpdateRequest(BaseModel):
    studio_name: str | None = Field(default=None, max_length=255)
    contact_email: EmailStr | None = None

    @field_validator("studio_name")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class SecurityPolicyUpdateRequest(BaseModel):
    # Floors at 4 (the smallest length the client-login UI has ever
    # supported) rather than 1 - a "minimum" policy that's shorter than
    # what's already in use everywhere would be meaningless.
    min_client_password_length: int = Field(ge=4, le=32)
    # 1 hour to 30 days - generous ceiling for a studio that wants clients
    # to have a long-lived download link, a tight floor so a completed ZIP
    # is never held on disk indefinitely by an accidental huge value.
    download_link_ttl_hours: int = Field(ge=1, le=720)


class AdminChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=8, max_length=255)
