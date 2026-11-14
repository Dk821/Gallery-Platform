"""
Public platform (super admin) logo - see app/services/platform_logo_service.py.

Plain <img> tags cannot send headers, and a logo is branding, so this is unauthenticated like the studio
logo. Only a super admin's logo is ever served. The URL carries a content hash, so a replaced logo gets a
new URL and the response can be cached for a year.
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session as DbSession

from app.database.connection import get_db
from app.models.admin import Admin
from app.schemas.errors import not_found
from app.services import platform_logo_service
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/platform", tags=["platform-branding"])


@router.get("/{admin_id}/logo")
def get_platform_logo(
    admin_id: int,
    v: str = Query(default="", max_length=64),
    db: DbSession = Depends(get_db),
    storage: StorageService = Depends(get_storage_service),
):
    admin = db.get(Admin, admin_id)
    if admin is None or admin.role != "super_admin":
        raise not_found("There is no logo.", code="LOGO_NOT_FOUND")
    data = platform_logo_service.read_logo(storage, admin, v or None)
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable" if v else "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )
