from sqlalchemy.orm import Session as DbSession

from app.models.admin import Admin
from app.schemas.errors import ApiError, bad_request
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
    # Invalidate every other session cookie issued before this change.
    admin.session_version = int(admin.session_version or 0) + 1
    db.commit()
    db.refresh(admin)
    return admin


_UNSET = object()


def update_own_account(
    db: DbSession,
    admin: Admin,
    name: str | None,
    email: str | None,
    current_password: str | None,
    company_name=_UNSET,
    contact_phone=_UNSET,
) -> dict:
    """
    Self-service edit of an admin's own name / sign-in email / company name / contact number. Changing the email needs the CURRENT
    password (it is the sign-in name). Returns which fields changed, for the audit row.
    """
    changed = {"name": False, "email": False, "company_name": False, "contact_phone": False}
    # Profile fields: `_UNSET` = not sent (unchanged); None = sent empty (cleared).
    if company_name is not _UNSET and company_name != admin.company_name:
        admin.company_name = company_name
        changed["company_name"] = True
    if contact_phone is not _UNSET and contact_phone != admin.contact_phone:
        admin.contact_phone = contact_phone
        changed["contact_phone"] = True
    if name is not None and name != admin.name:
        admin.name = name
        changed["name"] = True
    if email is not None:
        new_email = str(email).strip().lower()
        if new_email != (admin.email or "").lower():
            if not current_password or not verify_password(current_password, admin.password_hash):
                db.rollback()
                raise bad_request("Enter your current password to change your email.", code="INVALID_CURRENT_PASSWORD")
            if db.query(Admin.id).filter(Admin.email == new_email, Admin.id != admin.id).first():
                db.rollback()
                raise ApiError(409, "ADMIN_EMAIL_EXISTS", "An admin with this email already exists.")
            admin.email = new_email
            changed["email"] = True
    db.commit()
    db.refresh(admin)
    return changed


def sign_out_other_sessions(db: DbSession, admin: Admin) -> Admin:
    """Invalidates every session cookie issued before now (the caller re-issues its own)."""
    admin.session_version = int(admin.session_version or 0) + 1
    db.commit()
    db.refresh(admin)
    return admin
