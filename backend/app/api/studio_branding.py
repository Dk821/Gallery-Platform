"""
Public studio logo.

A logo is branding, not private data: the studio admin UI, the super-admin
console and (later) client galleries all show it in a plain <img>, which
cannot send custom headers. The URL carries a content hash (`?v=`), so a
replaced logo gets a new URL and the response can be cached for a year.
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session as DbSession

from app.database.connection import get_db
from app.models.studio import Studio
from app.schemas.errors import not_found
from app.services import studio_logo_service
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/studios", tags=["studio-branding"])


@router.get("/{studio_id}/logo")
def get_studio_logo(
    studio_id: int,
    v: str = Query(default="", max_length=64),
    db: DbSession = Depends(get_db),
    storage: StorageService = Depends(get_storage_service),
):
    studio = db.get(Studio, studio_id)
    if studio is None:
        raise not_found("This studio has no logo.", code="LOGO_NOT_FOUND")
    data = studio_logo_service.read_logo(storage, studio, v or None)
    return Response(
        content=data,
        media_type="image/png",
        headers={
            # With a version in the URL the bytes can never change; without
            # one we only know "the current logo", so keep it short-lived.
            "Cache-Control": "public, max-age=31536000, immutable" if v else "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
            # The frontend may be served from another origin than the API.
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )
