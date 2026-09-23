import datetime

from sqlalchemy.orm import Session as DbSession

from app.models.admin import Admin
from app.models.client import Client
from app.models.session import ClientSession
from app.schemas.errors import unauthorized
from app.security.password import verify_password
from app.security.session import (
    generate_session_token,
    hash_session_token,
    session_expiry,
)


def authenticate_admin(db: DbSession, email: str, password: str) -> Admin:
    admin = db.query(Admin).filter(Admin.email == email).first()
    if admin is None or admin.status != "active" or not verify_password(password, admin.password_hash):
        # Same error for "no such admin" and "wrong password" -
        # never reveal which one failed.
        raise unauthorized("Invalid email or password.", code="INVALID_CREDENTIALS")
    return admin


def authenticate_client(db: DbSession, gallery_id: str, password: str | None) -> tuple[Client, str]:
    """
    Verifies the gallery password (when the gallery has one) and creates a
    new server-side session. Returns (client, raw_session_token). The raw
    token is only ever returned here - callers must put it straight into an
    HttpOnly cookie and never log or persist it as-is.

    Galleries created WITHOUT a password (password_hash is NULL) skip the
    password check entirely and create a session directly. A password-
    protected gallery always rejects a missing/wrong password - existing
    protection is never bypassed.
    """
    client = db.query(Client).filter(Client.client_uuid == gallery_id).first()
    if client is None or client.status != "active":
        raise unauthorized("Invalid gallery link or password.", code="INVALID_CREDENTIALS")

    if client.password_hash is not None and not verify_password(password or "", client.password_hash):
        raise unauthorized("Invalid gallery link or password.", code="INVALID_CREDENTIALS")

    client.last_login_at = datetime.datetime.utcnow()

    raw_token = generate_session_token()
    session = ClientSession(
        client_id=client.id,
        session_token_hash=hash_session_token(raw_token),
        expires_at=session_expiry(),
        created_at=datetime.datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(client)

    return client, raw_token


def resolve_client_from_token(db: DbSession, raw_token: str) -> Client | None:
    session = resolve_client_session_from_token(db, raw_token)
    if session is None:
        return None
    client = db.query(Client).filter(Client.id == session.client_id).first()
    if client is None or client.status != "active":
        return None
    return client


def resolve_client_session_from_token(db: DbSession, raw_token: str) -> ClientSession | None:
    if not raw_token:
        return None
    token_hash = hash_session_token(raw_token)
    session = (
        db.query(ClientSession)
        .filter(ClientSession.session_token_hash == token_hash)
        .filter(ClientSession.expires_at > datetime.datetime.utcnow())
        .first()
    )
    return session


def revoke_client_session(db: DbSession, raw_token: str) -> None:
    if not raw_token:
        return
    token_hash = hash_session_token(raw_token)
    db.query(ClientSession).filter(ClientSession.session_token_hash == token_hash).delete()
    db.commit()
