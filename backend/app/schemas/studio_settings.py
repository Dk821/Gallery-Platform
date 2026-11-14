import datetime
import re

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
    # Omitted = unchanged; blank clears it.
    contact_phone: str | None = Field(default=None, max_length=50)

    @field_validator("contact_phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        from app.schemas.studio import _clean_phone

        return _clean_phone(v)

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
    new_password: str = Field(min_length=4, max_length=255)


class SuperAdminAccountUpdateRequest(BaseModel):
    """Edit the signed-in super admin's own name and/or sign-in email. Omitted fields stay unchanged."""

    name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    # Required only when the email changes (it is the sign-in name).
    current_password: str | None = Field(default=None, max_length=255)
    # Platform profile. Omitted = unchanged; an empty value clears it.
    company_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=50)

    @field_validator("company_name", "contact_phone")
    @classmethod
    def strip_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None  # blank clears the value

    @field_validator("contact_phone")
    @classmethod
    def phone_chars(cls, v: str | None) -> str | None:
        if v is not None and (
            not re.fullmatch(r"\+?[0-9()\-.\s]+", v) or not 7 <= len(re.sub(r"\D", "", v)) <= 15
        ):
            raise ValueError("enter a phone number (7-15 digits; digits, spaces and + - ( ) only)")
        return v

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v
