from sqlalchemy.orm import Session as DbSession

from app.models.admin import Admin
from app.schemas.errors import bad_request
from app.security.password import hash_password, verify_password


def change_admin_password(db: DbSession, admin: Admin, current_password: str, new_password: str) -> Admin:
    """
    Admin self-service password change - requires the CURRENT password,
    unlike an admin resetting a client's password (client_service.
    change_client_password), which is an operator action on someone
    else's account and rightly doesn't require the client's old password.
    """
    if not verify_password(current_password, admin.password_hash):
        raise bad_request("Current password is incorrect.", code="INVALID_CURRENT_PASSWORD")

    admin.password_hash = hash_password(new_password)
    db.commit()
    db.refresh(admin)
    return admin
