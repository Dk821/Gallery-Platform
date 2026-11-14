"""
Studio-admin self-service API (role: studio_admin).

The studio is ALWAYS taken from the authenticated admin (get_current_admin),
never from the URL, query or body: there is no studio_id parameter anywhere
in this module, so there is nothing for a caller to tamper with.
"""

import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.database.connection import get_db
from app.models.admin import Admin
from app.schemas.errors import bad_request
from app.schemas.pagination import build_page
from app.schemas.studio import StudioUpdateRequest
from app.services import audit_service, quota_service, studio_service

router = APIRouter(prefix="/api/studio", tags=["studio"])


@router.get("/profile")
def get_my_studio(db: DbSession = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    studio = studio_service.get_studio_or_404(db, admin.studio_id)
    return {"success": True, "data": studio_service.studio_to_dict(studio)}


@router.put("/profile")
def update_my_studio(
    payload: StudioUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    # Branding / contact details only. Quota and status are not fields of this
    # request model at all, so they cannot be set from here.
    studio = studio_service.get_studio_or_404(db, admin.studio_id)
    studio = studio_service.update_studio(db, studio, payload)
    audit_service.record_admin(
        db,
        admin,
        "studio_profile_updated",
        request=request,
        resource_type="studio",
        resource_id=studio.id,
        metadata={"fields": sorted(payload.model_fields_set)},
    )
    return {"success": True, "data": studio_service.studio_to_dict(studio)}


@router.get("/usage")
def get_my_usage(db: DbSession = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    studio = studio_service.get_studio_or_404(db, admin.studio_id)
    return {
        "success": True,
        "data": {
            "usage": quota_service.studio_usage(studio),
            "counts": studio_service.studio_counts(db, studio.id),
            "status": studio.status,
        },
    }


@router.get("/audit-logs")
def list_my_audit_logs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    action: str | None = Query(default=None, max_length=100),
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    if date_from and date_to and date_from > date_to:
        raise bad_request("'from' must not be after 'to'.", code="INVALID_DATE_RANGE")
    items, total, page, limit = studio_service.list_audit_logs(
        db, page, limit, studio_id=admin.studio_id, action=action, date_from=date_from, date_to=date_to
    )
    return {"success": True, "data": build_page(items, page, limit, total)}
