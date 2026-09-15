import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.database.connection import get_db
from app.models.admin import Admin
from app.services.activity_service import get_activity_feed

router = APIRouter(prefix="/api/admin/activity", tags=["admin-activity"])

ACTIVITY_TYPES = ("upload", "download", "client", "album")


@router.get("")
def get_activity(
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    search: str | None = Query(default=None, description="Free-text search across activity records."),
    activity_type: str | None = Query(
        default=None,
        alias="type",
        description="Filter to one activity family: upload, download, client or album.",
    ),
    date_from: datetime.date | None = Query(default=None, alias="from", description="Start date (inclusive)."),
    date_to: datetime.date | None = Query(default=None, alias="to", description="End date (inclusive)."),
    limit: int = Query(default=200, ge=1, le=1000),
):
    if activity_type is not None and activity_type not in ACTIVITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_ACTIVITY_TYPE",
                "message": "Unknown activity type.",
            },
        )
    return {
        "success": True,
        "data": get_activity_feed(
            db,
            search=search,
            activity_type=activity_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        ),
    }