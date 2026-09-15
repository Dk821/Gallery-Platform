from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.database.connection import get_db
from app.models.admin import Admin
from app.services.download_analytics_service import (
    get_download_history,
    get_download_summary,
    get_per_album_download_stats,
)

router = APIRouter(prefix="/api/admin/downloads", tags=["admin-downloads"])


@router.get("/analytics")
def get_download_analytics(
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    return {
        "success": True,
        "data": {
            "summary": get_download_summary(db),
            "albums": get_per_album_download_stats(db),
            "history": get_download_history(db),
        },
    }
