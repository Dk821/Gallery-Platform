import os
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.api.media_streaming import stream_media_file, stream_media_thumbnail
from app.api.presenters import media_to_response, upload_session_list_item, upload_session_to_response
from app.config.settings import Settings, get_settings
from app.database.connection import get_db
from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.schemas.media import BulkDeleteRequest, BulkMoveRequest, MediaMoveRequest, MediaUpdateRequest
from app.services.album_service import get_album_or_404
from app.services.media_service import (
    bulk_delete_media,
    bulk_move_media,
    delete_media,
    get_media_or_404,
    get_upload_session_status,
    list_recent_upload_sessions,
    move_media_to_album,
    update_media_metadata,
    upload_media_to_album,
)
from app.services.orphan_reconciliation import reconcile_orphans
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/admin/media", tags=["admin-media"])


def _log(db: DbSession, admin_id: int, action: str, resource_id: int, request: Request) -> None:
    db.add(
        AuditLog(
            user_type="admin",
            user_id=admin_id,
            action=action,
            resource_type="media",
            resource_id=resource_id,
            ip_address=request.client.host if request.client else None,
        )
    )
    db.commit()


def _log_bulk(db: DbSession, admin_id: int, action: str, request: Request, count: int) -> None:
    db.add(
        AuditLog(
            user_type="admin",
            user_id=admin_id,
            action=action,
            resource_type="media",
            resource_id=count,  # no single resource id for a bulk action - count is more useful here
            ip_address=request.client.host if request.client else None,
        )
    )
    db.commit()


@router.post("/upload")
def upload_media_route(
    request: Request,
    album_id: int = Form(...),
    file: UploadFile = File(...),
    # Client-generated idempotency key (Section 4). Optional for backward
    # compatibility with older frontends - if omitted, a fresh id is
    # generated per-request, which behaves exactly as before (no
    # duplicate-retry protection, but nothing breaks).
    upload_id: str | None = Form(default=None),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
):
    album = get_album_or_404(db, album_id)

    # UploadFile.file is a SpooledTemporaryFile - by the time this handler
    # runs the whole upload has already been received and, for anything
    # bigger than Starlette's in-memory threshold, spooled to disk. Reading
    # it via .seek()/.tell() here does not pull the whole thing into RAM.
    raw = file.file
    raw.seek(0, os.SEEK_END)
    file_size = raw.tell()
    raw.seek(0)
    header_bytes = raw.read(4096)
    raw.seek(0)

    media = upload_media_to_album(
        db,
        storage,
        settings,
        album,
        filename=file.filename or "upload",
        declared_content_type=file.content_type or "application/octet-stream",
        file_obj=raw,
        file_size=file_size,
        header_bytes=header_bytes,
        upload_id=upload_id or str(uuid.uuid4()),
        admin_id=admin.id,
    )
    _log(db, admin.id, "media_uploaded", media.id, request)
    return {"success": True, "data": media_to_response(media)}


@router.get("/upload-status/{upload_id}")
def get_upload_status_route(
    upload_id: str,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    print(
        f"[UPLOAD STATUS] upload_id={upload_id} "
        f"admin_id={admin.id}"
    )

    session = get_upload_session_status(db, admin.id, upload_id)

    print(
        f"[UPLOAD STATUS] FOUND id={session.id} "
        f"status={session.status} "
        f"admin_id={session.admin_id}"
    )

    return {
        "success": True,
        "data": upload_session_to_response(session),
    }

@router.get("/upload-sessions")
def list_upload_sessions_route(
    limit: int = Query(default=50, ge=1, le=100),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    # Backs the Uploads page's refresh-recovery (Section 4 idempotency
    # ledger, already persisted server-side): the frontend can rebuild its
    # in-memory upload list - including in-flight and just-finished
    # transfers - from here after a page reload, instead of losing track of
    # them entirely.
    recent = list_recent_upload_sessions(db, admin.id, limit=limit)
    return {
        "success": True,
        "data": [
            upload_session_list_item(item["session"], item["album_name"], item["client_name"])
            for item in recent
        ],
    }


@router.post("/reconcile-orphans")
def reconcile_orphans_route(
    request: Request,
    apply: bool = Query(default=False),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
):
    # Section 9: dry-run by default. Pass ?apply=true to actually delete
    # confirmed orphans; otherwise this only detects and logs candidates.
    # Intended to be triggered by a cron job hitting this endpoint (or via
    # the standalone reconcile_orphans.py script), the same pattern the
    # existing ZIP-job cleanup script uses.
    result = reconcile_orphans(
        db, storage, settings.orphan_file_grace_period_hours, dry_run=not apply
    )
    _log_bulk(db, admin.id, "orphans_reconciled", request, len(result["confirmed"]))
    return {"success": True, "data": result}


@router.post("/bulk-delete")
def bulk_delete_media_route(
    payload: BulkDeleteRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    # Every id is validated and deleted individually inside
    # bulk_delete_media() using the exact same delete_media() the
    # single-item DELETE route uses - including its storage-first
    # reconciliation guarantee. A missing/already-failed id never blocks
    # the rest of the batch.
    result = bulk_delete_media(db, storage, payload.media_ids)
    _log_bulk(db, admin.id, "media_bulk_deleted", request, len(result["deleted"]))
    return {"success": True, "data": result}


@router.post("/bulk-move")
def bulk_move_media_route(
    payload: BulkMoveRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    target_album = get_album_or_404(db, payload.target_album_id)
    result = bulk_move_media(db, storage, payload.media_ids, target_album)
    _log_bulk(db, admin.id, "media_bulk_moved", request, len(result["moved"]))
    return {"success": True, "data": result}


@router.get("/{media_id}")
def get_media_route(
    media_id: int,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    media = get_media_or_404(db, media_id)
    return {"success": True, "data": media_to_response(media)}


@router.patch("/{media_id}")
def update_media_route(
    media_id: int,
    payload: MediaUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    media = get_media_or_404(db, media_id)
    media = update_media_metadata(db, media, payload)
    _log(db, admin.id, "media_updated", media.id, request)
    return {"success": True, "data": media_to_response(media)}


@router.post("/{media_id}/move")
def move_media_route(
    media_id: int,
    payload: MediaMoveRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    media = get_media_or_404(db, media_id)
    # Never trust target_album_id blindly - get_album_or_404 confirms it's a
    # real album, and move_media_to_album() itself re-checks that it
    # belongs to the SAME client as the media being moved before touching
    # storage or the DB.
    target_album = get_album_or_404(db, payload.target_album_id)
    media = move_media_to_album(db, storage, media, target_album)
    _log(db, admin.id, "media_moved", media.id, request)
    return {"success": True, "data": media_to_response(media)}


@router.delete("/{media_id}")
def delete_media_route(
    media_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    media = get_media_or_404(db, media_id)
    delete_media(db, storage, media)
    _log(db, admin.id, "media_deleted", media_id, request)
    return {"success": True, "data": None}


@router.get("/{media_id}/thumbnail")
def get_media_thumbnail_route(
    media_id: int,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    media = get_media_or_404(db, media_id)
    return stream_media_thumbnail(media, storage)


@router.get("/{media_id}/view")
def view_media_route(
    media_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    media = get_media_or_404(db, media_id)
    return stream_media_file(media, storage, disposition="inline", range_header=request.headers.get("range"))


@router.get("/{media_id}/download")
def download_media_route(
    media_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
):
    media = get_media_or_404(db, media_id)
    return stream_media_file(media, storage, disposition="attachment", range_header=request.headers.get("range"))
