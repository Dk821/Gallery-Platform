from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_authenticated_admin, get_current_client
from app.database.connection import get_db
from app.models.admin import Admin
from app.models.client import Client
from app.models.studio import Studio
from app.schemas.errors import ApiError
from app.schemas.auth import AdminLoginRequest, ClientLoginRequest, CurrentUser
from app.security.session import (
    ADMIN_COOKIE_NAME,
    CLIENT_COOKIE_NAME,
    clear_session_cookie,
    create_admin_token,
    set_session_cookie,
)
from app.services import audit_service
from app.services.auth_service import authenticate_admin, authenticate_client, revoke_client_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _log(
    db: DbSession,
    user_type: str,
    user_id: int | None,
    action: str,
    request: Request,
    *,
    role: str | None = None,
    studio_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    audit_service.record(
        db,
        action=action,
        user_type=user_type,
        user_id=user_id,
        actor_role=role,
        studio_id=studio_id,
        request=request,
        metadata=metadata,
    )


@router.post("/admin/login")
def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
):
    try:
        admin = authenticate_admin(db, payload.email, payload.password)
    except ApiError:
        # Failed logins are an important auth event. The attempted password is
        # never recorded; the email is only used to attribute the attempt to a
        # studio if the account exists (and is not echoed anywhere).
        known = db.query(Admin).filter(Admin.email == payload.email).first()
        _log(
            db,
            "admin",
            known.id if known else None,
            "admin_login_failed",
            request,
            role=known.role if known else None,
            studio_id=known.studio_id if known else None,
            metadata={"reason": "invalid_credentials"},
        )
        raise
    token = create_admin_token(admin.id, admin.session_version)
    set_session_cookie(response, ADMIN_COOKIE_NAME, token)
    _log(db, "admin", admin.id, "admin_login", request, role=admin.role, studio_id=admin.studio_id)
    return {
        "success": True,
        # id/name unchanged; role/studio_id are additive.
        "data": {"id": admin.id, "name": admin.name, "role": admin.role, "studio_id": admin.studio_id},
    }


@router.post("/client/login")
def client_login(
    payload: ClientLoginRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
):
    client, raw_token = authenticate_client(db, payload.gallery_id, payload.password)
    set_session_cookie(response, CLIENT_COOKIE_NAME, raw_token)
    _log(db, "client", client.id, "client_login", request, studio_id=client.studio_id)
    return {"success": True, "data": {"id": client.id, "name": client.client_name}}


@router.post("/logout")
def logout(
    response: Response,
    admin_session: str | None = Cookie(default=None, alias=ADMIN_COOKIE_NAME),
    client_session: str | None = Cookie(default=None, alias=CLIENT_COOKIE_NAME),
    db: DbSession = Depends(get_db),
):
    if client_session:
        revoke_client_session(db, client_session)
    clear_session_cookie(response, ADMIN_COOKIE_NAME)
    clear_session_cookie(response, CLIENT_COOKIE_NAME)
    return {"success": True, "data": None}


@router.get("/me")
def get_me(
    admin_session: str | None = Cookie(default=None, alias=ADMIN_COOKIE_NAME),
    client_session: str | None = Cookie(default=None, alias=CLIENT_COOKIE_NAME),
    db: DbSession = Depends(get_db),
):
    if admin_session:
        try:
            admin: Admin = get_authenticated_admin(admin_session, db)
            studio = db.get(Studio, admin.studio_id) if admin.studio_id is not None else None
            return {
                "success": True,
                "data": CurrentUser(
                    user_type="admin",
                    id=admin.id,
                    name=admin.name,
                    role=admin.role,
                    studio_id=admin.studio_id,
                    studio_name=studio.name if studio else None,
                    studio_status=studio.status if studio else None,
                    company_name=admin.company_name if admin.role == "super_admin" else None,
                    logo_url=admin.logo_url if admin.role == "super_admin" else None,
                ),
            }
        except Exception:
            pass
    if client_session:
        try:
            client: Client = get_current_client(client_session, db)
            return {
                "success": True,
                "data": CurrentUser(user_type="client", id=client.id, name=client.client_name),
            }
        except Exception:
            pass
    return {"success": True, "data": None}
