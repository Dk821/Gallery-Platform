from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.database.connection import get_db
from app.models.admin import Admin
from app.services.dashboard_service import get_dashboard_summary, get_recent_clients

router = APIRouter(prefix="/api/admin/dashboard", tags=["admin-dashboard"])


@router.get("")
def get_dashboard(
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    summary = get_dashboard_summary(db)
    recent = get_recent_clients(db)
    return {
        "success": True,
        "data": {
            **summary,
            "recent_clients": [
                {
                    "id": c.id,
                    "client_uuid": c.client_uuid,
                    "client_name": c.client_name,
                    "status": c.status,
                    "created_at": c.created_at.isoformat(),
                }
                for c in recent
            ],
        },
    }
