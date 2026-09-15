import datetime
import hashlib
import secrets

from fastapi import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config.settings import get_settings

settings = get_settings()

ADMIN_COOKIE_NAME = "admin_session"
CLIENT_COOKIE_NAME = "client_session"

# Admins are few and managed directly in MySQL (Section 45), so unlike client
# sessions we don't need a revocable server-side session table for them.
# A signed, expiring token is sufficient and keeps things simple - it can be
# swapped for the same DB-backed session model later with no route changes.
_admin_serializer = URLSafeTimedSerializer(settings.secret_key, salt="admin-session")


def create_admin_token(admin_id: int) -> str:
    return _admin_serializer.dumps({"admin_id": admin_id})


def read_admin_token(token: str) -> int | None:
    try:
        data = _admin_serializer.loads(token, max_age=settings.session_ttl_minutes * 60)
        return int(data["admin_id"])
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None


def generate_session_token() -> str:
    # 256 bits of randomness, URL-safe. This raw value goes in the cookie only,
    # never stored as-is in the DB.
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    # A session token is already high entropy (not a user secret like a
    # password), so a fast SHA-256 hash is appropriate here - Argon2 is
    # reserved for low-entropy user-chosen passwords.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry() -> datetime.datetime:
    return datetime.datetime.utcnow() + datetime.timedelta(minutes=settings.session_ttl_minutes)


def _cookie_security_attrs() -> tuple[bool, str]:
    """
    Returns (secure, samesite) for session cookies.

    - Cross-origin frontend (settings.cross_site_frontend=True, e.g.
      Vercel frontend + VPS backend on a different domain): browsers only
      attach a cookie to a cross-site fetch/XHR call if it's SameSite=None
      - and SameSite=None is rejected by browsers unless the cookie is
      also Secure (HTTPS-only). So cross-site implies secure=True; there's
      no valid "cross-site but not secure" combination.
    - Same-origin frontend (default): SameSite=Lax is stronger baseline
      CSRF protection and works fine since the cookie never needs to
      cross an origin boundary. `secure` still follows environment, same
      as before, so plain-HTTP local dev keeps working.
    """
    if settings.cross_site_frontend:
        return True, "none"
    return settings.environment != "development", "lax"


def set_session_cookie(response: Response, cookie_name: str, token: str) -> None:
    secure, samesite = _cookie_security_attrs()
    response.set_cookie(
        key=cookie_name,
        value=token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )


def clear_session_cookie(response: Response, cookie_name: str) -> None:
    # Matching secure/samesite isn't strictly required for browsers to
    # delete a cookie, but keeping every set_cookie/delete_cookie call for
    # this cookie name using identical attributes avoids any edge-case
    # mismatch across browser implementations.
    secure, samesite = _cookie_security_attrs()
    response.delete_cookie(key=cookie_name, path="/", secure=secure, samesite=samesite)
