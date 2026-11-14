from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.config.settings import Settings, get_settings
from app.database.connection import get_db
from app.models.admin import Admin
from app.services.dashboard_service import get_dashboard_summary
from app.services.orphan_reconciliation import count_orphan_candidates
from app.services.storage_analytics_service import (
    get_daily_transfer_series,
    get_largest_files,
    get_storage_by_client,
    get_storage_by_file_type,
    get_upload_reliability,
)

router = APIRouter(prefix="/api/admin/storage", tags=["admin-storage"])


@router.get("")
def get_storage_overview(
    days: int = Query(30, ge=1, le=365, description="Window for the daily transfer chart and reliability stats."),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
):
    summary = get_dashboard_summary(db, admin.studio_id)

    return {
        "success": True,
        "data": {
            "our_metadata": {
                "total_files": summary["total_photos"] + summary["total_videos"],
                "total_photos": summary["total_photos"],
                "total_videos": summary["total_videos"],
                "total_bytes_tracked": summary["storage_used_bytes"],
            },
            # The studio's own allocation: quota / used / reserved / remaining. (The server disk and the
            # storage provider's own account quota are platform matters and are not shown to a studio.)
            "studio_quota": summary["studio_quota"],
            "daily_transfer": get_daily_transfer_series(db, admin.studio_id, days=days),
            "storage_by_client": get_storage_by_client(db, admin.studio_id),
            "storage_by_file_type": get_storage_by_file_type(db, admin.studio_id),
            "upload_reliability": get_upload_reliability(db, admin.studio_id, days=days),
            "largest_files": get_largest_files(db, admin.studio_id, limit=10),
            # Read-only, DB-only count (no Drive API calls) - safe to
            # compute on every page load. Deleting anything still requires
            # the explicit POST /api/admin/media/reconcile-orphans action.
            "orphan_candidate_count": count_orphan_candidates(
                db, settings.orphan_file_grace_period_hours, studio_id=admin.studio_id
            ),
        },
    }
