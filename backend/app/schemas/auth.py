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

    model_config = {"from_attributes": True}
