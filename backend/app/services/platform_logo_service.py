"""
The super admin's company logo (shown in the console sidebar).

Same handling as a studio logo (studio_logo_service.process_logo: validated, re-encoded to a bounded PNG),
stored in R2 under

    platform/branding/admin-{admin id}/logo-{version}.png

and referenced by `admins.logo_url` = /api/platform/{admin id}/logo?v={version}, served publicly by
app/api/platform_branding.py (an <img> cannot send headers; a logo is branding, not private data).
"""

import hashlib
import logging
import re

from app.models.admin import Admin
from app.schemas.errors import ApiError
from app.services.storage_service import StorageError, StorageNotFoundError, StorageService
from app.services.studio_logo_service import MAX_LOGO_UPLOAD_BYTES, process_logo

logger = logging.getLogger("gallery.platform.logo")

_VERSION_RE = re.compile(r"^[0-9a-f]{16}$")


def logo_key(admin: Admin, version: str) -> str:
    return f"platform/branding/admin-{admin.id}/logo-{version}.png"


def logo_path(admin_id: int, version: str) -> str:
    return f"/api/platform/{admin_id}/logo?v={version}"


def uploaded_version(admin: Admin) -> str | None:
    prefix = f"/api/platform/{admin.id}/logo?v="
    url = admin.logo_url or ""
    if url.startswith(prefix) and _VERSION_RE.match(url[len(prefix):]):
        return url[len(prefix):]
    return None


def _delete_quietly(storage: StorageService, admin: Admin, version: str) -> None:
    try:
        storage.delete(logo_key(admin, version))
    except StorageError:
        logger.warning("could not delete old platform logo object for admin %s", admin.id)


def save_logo(db, storage: StorageService, admin: Admin, data: bytes) -> Admin:
    png = process_logo(data)
    version = hashlib.sha256(png).hexdigest()[:16]
    previous = uploaded_version(admin)
    try:
        storage.put_bytes(logo_key(admin, version), png, "image/png")
    except StorageError as exc:
        raise ApiError(502, "STORAGE_UPLOAD_FAILED", "Could not store the logo. Please try again.") from exc
    admin.logo_url = logo_path(admin.id, version)
    db.commit()
    db.refresh(admin)
    if previous and previous != version:
        _delete_quietly(storage, admin, previous)
    return admin


def remove_logo(db, storage: StorageService, admin: Admin) -> Admin:
    previous = uploaded_version(admin)
    admin.logo_url = None
    db.commit()
    db.refresh(admin)
    if previous:
        _delete_quietly(storage, admin, previous)
    return admin


def read_logo(storage: StorageService, admin: Admin, version: str | None) -> bytes:
    current = uploaded_version(admin)
    if current is None or (version and version != current):
        raise ApiError(404, "LOGO_NOT_FOUND", "There is no logo.")
    try:
        return b"".join(storage.download(logo_key(admin, current)))
    except StorageNotFoundError as exc:
        raise ApiError(404, "LOGO_NOT_FOUND", "There is no logo.") from exc
    except StorageError as exc:
        raise ApiError(502, "STORAGE_DOWNLOAD_FAILED", "Could not load the logo. Please try again.") from exc


__all__ = ["MAX_LOGO_UPLOAD_BYTES", "save_logo", "remove_logo", "read_logo", "uploaded_version"]
