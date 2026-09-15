from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.api.presenters import download_job_to_response
from app.database.connection import get_db
from app.models.admin import Admin
from app.models.client import Client
from app.schemas.download_job import DownloadJobCreateRequest
from app.services.album_service import get_album_or_404
from app.services.client_service import get_client_or_404
from app.services.download_analytics_service import record_download
from app.services.download_job_service import (
    cancel_download_job,
    create_download_job,
    get_download_job_or_404,
    get_ready_zip_path_or_error,
    process_download_job,
)
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/admin", tags=["admin-download-jobs"])


@router.post("/albums/{album_id}/download-jobs")
def create_admin_album_download_job(
    album_id: int,
    payload: DownloadJobCreateRequest,
    background_tasks: BackgroundTasks,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    # Admin bypasses expiry the same way every other admin album route
    # does - an expired album can still be bulk-downloaded by the studio
    # (Section: "Admin should still be able to manage the album").
    album = get_album_or_404(db, album_id)
    client = get_client_or_404(db, album.client_id)
    job = create_download_job(
        db, album, payload.media_ids, requested_by_type="admin", requested_by_id=admin.id
    )
    background_tasks.add_task(process_download_job, job.id, storage)
    return {"success": True, "data": download_job_to_response(job, client)}


@router.get("/download-jobs/{job_id}")
def get_admin_download_job_status(
    job_id: int,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    job = get_download_job_or_404(db, job_id)
    client = db.query(Client).filter(Client.id == job.client_id).first()
    return {"success": True, "data": download_job_to_response(job, client)}


@router.post("/download-jobs/{job_id}/cancel")
def cancel_admin_download_job(
    job_id: int,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    job = get_download_job_or_404(db, job_id)
    client = db.query(Client).filter(Client.id == job.client_id).first()
    job = cancel_download_job(db, job)
    return {"success": True, "data": download_job_to_response(job, client)}


@router.get("/download-jobs/{job_id}/file")
def download_admin_job_file(
    job_id: int,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    job = get_download_job_or_404(db, job_id)
    zip_path = get_ready_zip_path_or_error(job)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"gallery-{job.album_id}.zip",
        background=BackgroundTask(record_download, job.id),
    )
