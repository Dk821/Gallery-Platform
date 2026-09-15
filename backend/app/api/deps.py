from fastapi import Cookie, Depends
from sqlalchemy.orm import Session as DbSession

from app.database.connection import get_db
from app.models.admin import Admin
from app.models.client import Client
from app.models.session import ClientSession
from app.schemas.errors import unauthorized
from app.security.session import ADMIN_COOKIE_NAME, CLIENT_COOKIE_NAME, read_admin_token
from app.services.auth_service import resolve_client_from_token, resolve_client_session_from_token


def get_current_admin(
    admin_session: str | None = Cookie(default=None, alias=ADMIN_COOKIE_NAME),
    db: DbSession = Depends(get_db),
) -> Admin:
    admin_id = read_admin_token(admin_session) if admin_session else None
    if admin_id is None:
        raise unauthorized("Admin authentication required.")
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if admin is None or admin.status != "active":
        raise unauthorized("Admin authentication required.")
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
    if client is None or client.status != "active":
        raise unauthorized("Gallery login required.")
    return session
