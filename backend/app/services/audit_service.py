"""
Single entry point for writing audit-log rows.

Rules enforced here so no caller can get them wrong:
  * `metadata` is for small, NON-SENSITIVE context only. Any key that looks
    like a secret (password, token, cookie, credential, access/secret key,
    authorization) is dropped, and values are limited to short scalars.
  * studio_id records WHICH studio an action affected. Studio admins can only
    ever read rows with their own studio_id.
"""

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session as DbSession

from app.models.admin import Admin
from app.models.audit_log import AuditLog

logger = logging.getLogger("gallery.audit")

_SENSITIVE_FRAGMENTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "credential",
    "cookie",
    "authorization",
    "api_key",
    "access_key",
    "private",
    "session",
)
_MAX_STR = 300
_MAX_KEYS = 25


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata:
        return None
    clean: dict[str, Any] = {}
    for key, value in list(metadata.items())[:_MAX_KEYS]:
        k = str(key)
        if any(fragment in k.lower() for fragment in _SENSITIVE_FRAGMENTS):
            continue
        if isinstance(value, (int, float, bool)) or value is None:
            clean[k] = value
        elif isinstance(value, str):
            clean[k] = value[:_MAX_STR]
        elif isinstance(value, (list, tuple)) and all(isinstance(v, (int, float, str, bool)) for v in value):
            clean[k] = [v if not isinstance(v, str) else v[:_MAX_STR] for v in list(value)[:50]]
        # anything else (nested dicts, objects) is dropped on purpose
    return clean or None


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def record(
    db: DbSession,
    *,
    action: str,
    user_type: str = "admin",
    user_id: int | None = None,
    actor_role: str | None = None,
    studio_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditLog | None:
    """
    Appends one audit row. Audit failures must never break the user's request,
    so errors are logged and swallowed - but only when we own the commit.
    """
    entry = AuditLog(
        user_type=user_type,
        user_id=user_id,
        actor_role=actor_role,
        studio_id=studio_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=client_ip(request),
        event_metadata=sanitize_metadata(metadata),
    )
    db.add(entry)
    if not commit:
        return entry
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Failed to write audit log action=%s", action)
        return None
    return entry


def record_admin(
    db: DbSession,
    admin: Admin,
    action: str,
    *,
    request: Request | None = None,
    studio_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditLog | None:
    """Audit row for an action by `admin`; studio defaults to the admin's own studio."""
    return record(
        db,
        action=action,
        user_type="admin",
        user_id=admin.id,
        actor_role=admin.role,
        studio_id=studio_id if studio_id is not None else admin.studio_id,
        resource_type=resource_type,
        resource_id=resource_id,
        request=request,
        metadata=metadata,
        commit=commit,
    )
