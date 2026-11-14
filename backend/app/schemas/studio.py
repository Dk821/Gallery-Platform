import datetime
import re

from pydantic import BaseModel, EmailStr, Field, field_validator

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

# Hard ceiling for a single studio quota (100 TB decimal). Keeps a typo like an
# extra zero from allocating the whole platform and keeps values in BIGINT range.
MAX_QUOTA_BYTES = 100_000_000_000_000


def _clean_phone(v: str | None) -> str | None:
    """Blank -> None; otherwise an optional leading +, then 7-15 digits with ( ) - . and spaces as separators."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not re.fullmatch(r"\+?[0-9()\-.\s]+", v) or not 7 <= len(re.sub(r"\D", "", v)) <= 15:
        raise ValueError("enter a valid phone number (7-15 digits; digits, spaces and + - ( ) only)")
    return v


def _clean_logo_url(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    v = v.strip()
    # https only: a logo URL is rendered by browsers, so javascript:/data:
    # schemes must never be storable.
    if not v.lower().startswith("https://"):
        raise ValueError("logo_url must be an https:// URL")
    return v


class _BrandingMixin(BaseModel):
    logo_url: str | None = Field(default=None, max_length=1000)
    brand_color: str | None = Field(default=None, max_length=20)

    @field_validator("logo_url")
    @classmethod
    def _logo(cls, v):
        return _clean_logo_url(v)

    @field_validator("brand_color")
    @classmethod
    def _color(cls, v):
        if v is None or v == "":
            return None
        if not _HEX_COLOR.match(v):
            raise ValueError("brand_color must look like #1a2b3c")
        return v


class StudioCreateRequest(_BrandingMixin):
    name: str = Field(min_length=1, max_length=255)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)

    @field_validator("contact_phone")
    @classmethod
    def _phone(cls, v):
        return _clean_phone(v)
    # Omitted -> DEFAULT_STUDIO_QUOTA_BYTES from configuration.
    quota_bytes: int | None = Field(default=None, gt=0, le=MAX_QUOTA_BYTES)
    # The studio's first admin login.
    admin_name: str = Field(min_length=1, max_length=255)
    admin_email: EmailStr
    # Omitted -> a random temporary password is generated and returned ONCE.
    admin_password: str | None = Field(default=None, min_length=4, max_length=128)

    @field_validator("name", "admin_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class StudioUpdateRequest(_BrandingMixin):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)

    @field_validator("contact_phone")
    @classmethod
    def _phone(cls, v):
        return _clean_phone(v)

    @field_validator("name")
    @classmethod
    def _strip(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class StudioQuotaRequest(BaseModel):
    quota_bytes: int = Field(gt=0, le=MAX_QUOTA_BYTES)


class StudioStatusRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class StudioAdminCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str | None = Field(default=None, min_length=4, max_length=128)


class StudioAdminUpdateRequest(BaseModel):
    """Edit a studio admin's profile. Omitted fields are left unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class AdminPasswordResetRequest(BaseModel):
    # Omitted -> a random temporary password is generated and returned once.
    new_password: str | None = Field(default=None, min_length=4, max_length=128)


class StudioUsage(BaseModel):
    quota_bytes: int
    used_bytes: int
    reserved_bytes: int
    remaining_bytes: int


class StudioResponse(BaseModel):
    id: int
    name: str
    contact_email: str | None
    contact_phone: str | None
    logo_url: str | None
    brand_color: str | None
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    usage: StudioUsage
