from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.database.connection import get_db
from app.models.admin import Admin
from app.models.studio import Studio
from app.schemas.errors import ApiError
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService
from app.services import studio_logo_service
from app.security.session import ADMIN_COOKIE_NAME, create_admin_token, set_session_cookie
from app.schemas.studio_settings import (
    AdminChangePasswordRequest,
    SecurityPolicyUpdateRequest,
    StudioProfileUpdateRequest,
    StudioSettingsResponse,
)
from app.services import audit_service
from app.services.admin_service import change_admin_password
from app.services.studio_settings_service import _UNSET as _PHONE_UNSET
from app.services.studio_settings_service import (
    get_studio_settings,
    update_security_policy,
    update_studio_profile,
)

router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])


def _log(db: DbSession, admin: Admin, action: str, request: Request) -> None:
    audit_service.record_admin(
        db, admin, action, request=request, resource_type="studio_settings", resource_id=admin.id
    )


def _profile(db: DbSession, admin: Admin) -> dict:
    """What the studio shows publicly (name, contact, logo), read from the studio record."""
    studio = db.get(Studio, admin.studio_id) if admin.studio_id is not None else None
    if studio is None:
        return {"name": None, "contact_email": None, "contact_phone": None, "logo_url": None}
    return {
        "name": studio.name,
        "contact_email": studio.contact_email,
        "contact_phone": studio.contact_phone,
        "logo_url": studio.logo_url,
    }


def _own_studio(db: DbSession, admin: Admin) -> Studio:
    studio = db.get(Studio, admin.studio_id) if admin.studio_id is not None else None
    if studio is None:
        raise ApiError(409, "STUDIO_NOT_ASSIGNED", "This account is not linked to a studio.")
    return studio


@router.get("")
def get_settings_route(
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    studio_settings = get_studio_settings(db, admin.studio_id)
    return {
        "success": True,
        "data": {
            "studio": StudioSettingsResponse.model_validate(studio_settings),
            "admin": {"id": admin.id, "name": admin.name, "email": admin.email},
            "profile": _profile(db, admin),
        },
    }


@router.put("/profile")
def update_profile_route(
    payload: StudioProfileUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    phone = payload.contact_phone if "contact_phone" in payload.model_fields_set else _PHONE_UNSET
    studio_settings = update_studio_profile(
        db, admin.studio_id, payload.studio_name, payload.contact_email, phone
    )
    _log(db, admin, "studio_profile_updated", request)
    return {
        "success": True,
        # Same fields as before, plus the studio's public profile (incl. phone and logo).
        "data": {**StudioSettingsResponse.model_validate(studio_settings).model_dump(mode="json"), "profile": _profile(db, admin)},
    }


@router.post("/logo")
def upload_logo_route(
    request: Request,
    file: UploadFile = File(...),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    studio = _own_studio(db, admin)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > studio_logo_service.MAX_LOGO_UPLOAD_BYTES + 64 * 1024:
        raise ApiError(413, "LOGO_TOO_LARGE", "The logo must be 5 MB or smaller.")
    data = file.file.read(studio_logo_service.MAX_LOGO_UPLOAD_BYTES + 1)
    studio_logo_service.save_logo(db, storage, studio, data)
    _log(db, admin, "studio_logo_updated", request)
    return {"success": True, "data": _profile(db, admin)}


@router.delete("/logo")
def remove_logo_route(
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    studio = _own_studio(db, admin)
    studio_logo_service.remove_logo(db, storage, studio)
    _log(db, admin, "studio_logo_removed", request)
    return {"success": True, "data": _profile(db, admin)}


@router.put("/security")
def update_security_route(
    payload: SecurityPolicyUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    studio_settings = update_security_policy(
        db, admin.studio_id, payload.min_client_password_length, payload.download_link_ttl_hours
    )
    _log(db, admin, "security_policy_updated", request)
    return {"success": True, "data": StudioSettingsResponse.model_validate(studio_settings)}


@router.post("/change-password")
def change_admin_password_route(
    payload: AdminChangePasswordRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    change_admin_password(db, admin, payload.current_password, payload.new_password)
    # change_admin_password bumped session_version (every OTHER session is now
    # signed out); keep THIS browser logged in by re-issuing its cookie.
    set_session_cookie(response, ADMIN_COOKIE_NAME, create_admin_token(admin.id, admin.session_version))
    _log(db, admin, "admin_password_changed", request)
    return {"success": True, "data": None}
