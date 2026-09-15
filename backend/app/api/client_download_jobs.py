from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session as DbSession

import datetime

from app.api.deps import get_current_client, get_current_client_session
from app.api.presenters import download_job_to_response
from app.database.connection import get_db
from app.models.client import Client
from app.models.session import ClientSession
from app.schemas.download_job import DownloadJobCreateRequest, DownloadJobVerifyPasswordRequest
from app.schemas.errors import ApiError, forbidden
from app.security.password import verify_password
from app.services.album_service import get_album_for_client_or_403
from app.services.download_analytics_service import record_download
from app.services.download_job_service import (
    cancel_download_job,
    create_download_job,
    get_download_job_for_client_or_403,
    get_ready_zip_path_or_error,
    process_download_job,
)
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/client", tags=["client-download-jobs"])


def require_download_permission(client: Client, session: ClientSession) -> None:
    if client.download_password_hash and session.download_password_verified_at is None:
        raise forbidden("This download requires a password.", code="DOWNLOAD_PASSWORD_REQUIRED")


@router.post("/albums/{album_id}/download-jobs")
def create_album_download_job(
    album_id: int,
    payload: DownloadJobCreateRequest,
    background_tasks: BackgroundTasks,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
    storage: StorageService = Depends(get_storage_service),
):
    # get_album_for_client_or_403 enforces both ownership AND expiry
    # (Part 6) - an expired album can't be downloaded, matching the same
    # rule that already blocks viewing it.
    album = get_album_for_client_or_403(db, album_id, client.id)
    job = create_download_job(
        db, album, payload.media_ids, requested_by_type="client", requested_by_id=client.id
    )
    # Passing the already-resolved `storage` through (rather than letting
    # process_download_job call get_storage_service() itself) is what lets
    # tests substitute FakeStorageService here - see the docstring on
    # process_download_job for why that matters.
    background_tasks.add_task(process_download_job, job.id, storage)
    return {"success": True, "data": download_job_to_response(job, client)}


@router.get("/download-jobs/{job_id}")
def get_download_job_status(
    job_id: int,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    job = get_download_job_for_client_or_403(db, job_id, client.id)
    return {"success": True, "data": download_job_to_response(job, client)}


@router.post("/download-jobs/{job_id}/cancel")
def cancel_client_download_job(
    job_id: int,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    job = get_download_job_for_client_or_403(db, job_id, client.id)
    job = cancel_download_job(db, job)
    return {"success": True, "data": download_job_to_response(job, client)}


@router.post("/download-jobs/{job_id}/verify-password")
def verify_download_password(
    job_id: int,
    payload: DownloadJobVerifyPasswordRequest,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
    session: ClientSession = Depends(get_current_client_session),
):
    job = get_download_job_for_client_or_403(db, job_id, client.id)
    get_ready_zip_path_or_error(job)
    if not client.download_password_hash:
        raise ApiError(400, "NO_PASSWORD_REQUIRED", "This gallery does not require a download password.")
    if not verify_password(payload.password, client.download_password_hash):
        raise forbidden("Incorrect download password.", code="INVALID_DOWNLOAD_PASSWORD")
    session.download_password_verified_at = datetime.datetime.utcnow()
    db.commit()
    return {"success": True, "data": {"verified": True}}


@router.post("/verify-download-password")
def verify_gallery_download_password(
    payload: DownloadJobVerifyPasswordRequest,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
    session: ClientSession = Depends(get_current_client_session),
):
    if not client.download_password_hash:
        raise ApiError(400, "NO_PASSWORD_REQUIRED", "This gallery does not require a download password.")
    if not verify_password(payload.password, client.download_password_hash):
        raise forbidden("Incorrect download password.", code="INVALID_DOWNLOAD_PASSWORD")
    session.download_password_verified_at = datetime.datetime.utcnow()
    db.commit()
    return {"success": True, "data": {"verified": True}}


@router.get("/download-jobs/{job_id}/file")
def download_job_file(
    job_id: int,
    db: DbSession = Depends(get_db),
    client: Client = Depends(get_current_client),
    session: ClientSession = Depends(get_current_client_session),
):
    job = get_download_job_for_client_or_403(db, job_id, client.id)
    require_download_permission(client, session)
    zip_path = get_ready_zip_path_or_error(job)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"gallery-{job.album_id}.zip",
        background=BackgroundTask(record_download, job.id),
    )
