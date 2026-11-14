from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session as DbSession

from app.database.connection import get_db
from app.models.admin import Admin
from app.models.client import Client
from app.models.session import ClientSession
from app.models.studio import Studio
from app.schemas.errors import forbidden, unauthorized
from app.security.session import ADMIN_COOKIE_NAME, CLIENT_COOKIE_NAME, read_admin_session
from app.services.auth_service import resolve_client_from_token, resolve_client_session_from_token

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_authenticated_admin(
    admin_session: str | None = Cookie(default=None, alias=ADMIN_COOKIE_NAME),
    db: DbSession = Depends(get_db),
) -> Admin:
    """
    Any valid, active admin of ANY role. Role and studio are always read from
    the database here, never from the cookie or from anything the frontend
    sends. Use get_current_admin / require_super_admin for route protection.
    """
    parsed = read_admin_session(admin_session) if admin_session else None
    if parsed is None:
        raise unauthorized("Admin authentication required.")
    admin_id, session_version = parsed
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if admin is None or admin.status != "active" or int(admin.session_version or 0) != session_version:
        raise unauthorized("Admin authentication required.")
    return admin


def get_current_admin(
    request: Request,
    admin: Admin = Depends(get_authenticated_admin),
    db: DbSession = Depends(get_db),
) -> Admin:
    """
    The dependency every existing /api/admin/* route already uses - now the
    STUDIO gate. Passing it guarantees:
      * the caller is a studio_admin (super admins operate the platform, they
        do not browse a studio's galleries through these routes),
      * the admin is assigned to a studio that exists (`admin.studio_id` is
        therefore safe to use as the tenant filter), and
      * a suspended studio is read-only: GET/HEAD/OPTIONS pass, anything that
        changes state is refused with 403 STUDIO_SUSPENDED.
    """
    if admin.role != "studio_admin":
        raise forbidden("This endpoint is for studio admins.", code="STUDIO_ADMIN_REQUIRED")
    if admin.studio_id is None:
        raise forbidden(
            "This admin account is not assigned to a studio yet. Contact the platform administrator.",
            code="STUDIO_NOT_ASSIGNED",
        )
    studio = db.get(Studio, admin.studio_id)
    if studio is None:
        raise forbidden("Studio not found for this admin.", code="STUDIO_NOT_ASSIGNED")
    if studio.status != "active" and request.method not in _SAFE_METHODS:
        raise forbidden("This studio is suspended. Changes are not allowed.", code="STUDIO_SUSPENDED")
    return admin


def require_super_admin(admin: Admin = Depends(get_authenticated_admin)) -> Admin:
    if admin.role != "super_admin":
        raise forbidden("Super admin access required.", code="SUPER_ADMIN_REQUIRED")
    return admin


def get_current_client(
    client_session: str | None = Cookie(default=None, alias=CLIENT_COOKIE_NAME),
    db: DbSession = Depends(get_db),
) -> Client:
    client = resolve_client_from_token(db, client_session) if client_session else None
    if client is None:
        raise unauthorized("Gallery login required.")
    return client


def get_current_client_session(
    client_session: str | None = Cookie(default=None, alias=CLIENT_COOKIE_NAME),
    db: DbSession = Depends(get_db),
) -> ClientSession:
    session = resolve_client_session_from_token(db, client_session) if client_session else None
    if session is None:
        raise unauthorized("Gallery login required.")
    client = db.query(Client).filter(Client.id == session.client_id).first()
    if client is None or client.status != "active" or not client_studio_is_active(db, client):
        raise unauthorized("Gallery login required.")
    return session


def client_studio_is_active(db: DbSession, client: Client) -> bool:
    """
    A client of a SUSPENDED studio cannot open galleries. Clients not yet
    mapped to any studio (legacy rows awaiting `legacy_to_studio`) keep
    working so a rollout never takes existing galleries offline.
    """
    if client.studio_id is None:
        return True
    studio = db.get(Studio, client.studio_id)
    return studio is not None and studio.status == "active"
