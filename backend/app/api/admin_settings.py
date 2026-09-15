from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.database.connection import get_db
from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.schemas.studio_settings import (
    AdminChangePasswordRequest,
    SecurityPolicyUpdateRequest,
    StudioProfileUpdateRequest,
    StudioSettingsResponse,
)
from app.services.admin_service import change_admin_password
from app.services.studio_settings_service import (
    get_studio_settings,
    update_security_policy,
    update_studio_profile,
)

router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])


def _log(db: DbSession, admin_id: int, action: str, request: Request) -> None:
    db.add(
        AuditLog(
            user_type="admin",
            user_id=admin_id,
            action=action,
            resource_type="studio_settings",
            resource_id=admin_id,
            ip_address=request.client.host if request.client else None,
        )
    )
    db.commit()


@router.get("")
def get_settings_route(
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    studio_settings = get_studio_settings(db)
    return {
        "success": True,
        "data": {
            "studio": StudioSettingsResponse.model_validate(studio_settings),
            "admin": {"id": admin.id, "name": admin.name, "email": admin.email},
        },
    }


@router.put("/profile")
def update_profile_route(
    payload: StudioProfileUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    studio_settings = update_studio_profile(db, payload.studio_name, payload.contact_email)
    _log(db, admin.id, "studio_profile_updated", request)
    return {"success": True, "data": StudioSettingsResponse.model_validate(studio_settings)}


@router.put("/security")
def update_security_route(
    payload: SecurityPolicyUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    studio_settings = update_security_policy(
        db, payload.min_client_password_length, payload.download_link_ttl_hours
    )
    _log(db, admin.id, "security_policy_updated", request)
    return {"success": True, "data": StudioSettingsResponse.model_validate(studio_settings)}


@router.post("/change-password")
def change_admin_password_route(
    payload: AdminChangePasswordRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    change_admin_password(db, admin, payload.current_password, payload.new_password)
    _log(db, admin.id, "admin_password_changed", request)
    return {"success": True, "data": None}
