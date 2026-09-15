from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin, get_current_client
from app.database.connection import get_db
from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.schemas.auth import AdminLoginRequest, ClientLoginRequest, CurrentUser
from app.security.session import (
    ADMIN_COOKIE_NAME,
    CLIENT_COOKIE_NAME,
    clear_session_cookie,
    create_admin_token,
    set_session_cookie,
)
from app.services.auth_service import authenticate_admin, authenticate_client, revoke_client_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _log(db: DbSession, user_type: str, user_id: int, action: str, request: Request) -> None:
    db.add(
        AuditLog(
            user_type=user_type,
            user_id=user_id,
            action=action,
            ip_address=request.client.host if request.client else None,
        )
    )
    db.commit()


@router.post("/admin/login")
def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
):
    admin = authenticate_admin(db, payload.email, payload.password)
    token = create_admin_token(admin.id)
    set_session_cookie(response, ADMIN_COOKIE_NAME, token)
    _log(db, "admin", admin.id, "admin_login", request)
    return {"success": True, "data": {"id": admin.id, "name": admin.name}}


@router.post("/client/login")
def client_login(
    payload: ClientLoginRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
):
    client, raw_token = authenticate_client(db, payload.gallery_id, payload.password)
    set_session_cookie(response, CLIENT_COOKIE_NAME, raw_token)
    _log(db, "client", client.id, "client_login", request)
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
            admin: Admin = get_current_admin(admin_session, db)
            return {"success": True, "data": CurrentUser(user_type="admin", id=admin.id, name=admin.name)}
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
