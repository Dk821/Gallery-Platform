from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.config.settings import Settings, get_settings
from app.database.connection import get_db
from app.models.admin import Admin
from app.services.dashboard_service import get_dashboard_summary
from app.services.disk_service import get_disk_tracker
from app.services.orphan_reconciliation import count_orphan_candidates
from app.services.storage_analytics_service import (
    get_daily_transfer_series,
    get_largest_files,
    get_storage_by_client,
    get_storage_by_file_type,
    get_upload_reliability,
)
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/admin/storage", tags=["admin-storage"])


@router.get("")
def get_storage_overview(
    days: int = Query(30, ge=1, le=365, description="Window for the daily transfer chart and reliability stats."),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
):
    summary = get_dashboard_summary(db)

    # Section 42: if the provider can't give an exact quota for this
    # account/configuration, label it unavailable rather than inventing a
    # number - get_metadata() already returns {"available": False} in that
    # case, and GoogleDriveStorage never raises out of this call.
    drive_quota = storage.get_metadata()

    # Distinct from drive_quota above: this is the actual disk on THIS
    # server (where uploads are spooled and ZIP jobs are written before/
    # during transfer to Drive), not Google Drive's storage quota. A VPS
    # can run out of local disk well before Drive's quota is anywhere
    # near full, and that failure mode is otherwise invisible without
    # SSHing in and running `df`.
    vps_disk = get_disk_tracker().get_headroom(min_free_bytes=settings.upload_min_free_disk_bytes)

    return {
        "success": True,
        "data": {
            "our_metadata": {
                "total_files": summary["total_photos"] + summary["total_videos"],
                "total_photos": summary["total_photos"],
                "total_videos": summary["total_videos"],
                "total_bytes_tracked": summary["storage_used_bytes"],
            },
            "drive_quota": drive_quota,
            "vps_disk": vps_disk,
            "daily_transfer": get_daily_transfer_series(db, days=days),
            "storage_by_client": get_storage_by_client(db),
            "storage_by_file_type": get_storage_by_file_type(db),
            "upload_reliability": get_upload_reliability(db, days=days),
            "largest_files": get_largest_files(db, limit=10),
            # Read-only, DB-only count (no Drive API calls) - safe to
            # compute on every page load. Deleting anything still requires
            # the explicit POST /api/admin/media/reconcile-orphans action.
            "orphan_candidate_count": count_orphan_candidates(db, settings.orphan_file_grace_period_hours),
        },
    }
