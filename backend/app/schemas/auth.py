from pydantic import BaseModel, EmailStr, Field


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=255)


class ClientLoginRequest(BaseModel):
    gallery_id: str = Field(min_length=1, max_length=36)
    # Optional: galleries without a password accept login without one. When a
    # gallery IS password-protected, service-side verification still rejects
    # an empty/missing password.
    password: str | None = Field(default=None, max_length=255)


class CurrentUser(BaseModel):
    user_type: str  # "admin" | "client"
    id: int
    name: str
    # Additive (multi-studio). Present for admins: "super_admin" | "studio_admin".
    role: str | None = None
    studio_id: int | None = None
    studio_name: str | None = None
    studio_status: str | None = None
    # Super admins only: the company name and logo shown in the console sidebar.
    company_name: str | None = None
    logo_url: str | None = None

    model_config = {"from_attributes": True}
