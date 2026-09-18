from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_current_admin
from app.api.media_streaming import stream_media_file, stream_media_thumbnail
from app.api.presenters import (
    media_to_response,
    upload_session_list_item,
    upload_session_start_response,
    upload_session_to_response,
)
from app.config.settings import Settings, get_settings
from app.database.connection import get_db
from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.schemas.media import (
    BulkDeleteRequest,
    BulkMoveRequest,
    CompleteUploadRequest,
    CreateUploadSessionRequest,
    MediaMoveRequest,
    MediaUpdateRequest,
    UploadProgressRequest,
)
from app.services.album_service import get_album_or_404
from app.services.media_service import (
    abandon_direct_upload,
    bulk_delete_media,
    bulk_move_media,
    complete_direct_upload,
    delete_media,
    get_media_or_404,
    get_upload_session_status,
    list_recent_upload_sessions,
    move_media_to_album,
    report_upload_progress,
    start_direct_upload,
    update_media_metadata,
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


@router.post("/upload-session")
def start_direct_upload_route(
    payload: CreateUploadSessionRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
):
    # Browser -> Drive direct upload, step 1 of 2: this server never
    # receives the file's bytes. It validates the request, reserves the
    # idempotency-ledger row (Section 4), and asks Drive to open a
    # resumable upload session - the browser PUTs its bytes straight to
    # the returned upload_url from here on, then calls POST
    # /upload-complete when done.
    #
    # The browser's own Origin header is forwarded to Drive so it can bake
    # CORS support for that origin into the session (see
    # create_resumable_session's docstring - without this, Drive issues a
    # session with no CORS allowance and the browser's subsequent PUT is
    # blocked client-side before it ever reaches Drive). Only forwarded if
    # it's one of THIS application's own configured CORS origins - never
    # trust an arbitrary Origin header for something that becomes a real
    # CORS grant on Drive's side.
    origin = request.headers.get("origin")
    if origin not in settings.effective_cors_origins:
        origin = None

    album = get_album_or_404(db, payload.album_id)
    session, upload_url, existing_media = start_direct_upload(
        db,
        storage,
        settings,
        admin.id,
        payload.upload_id,
        album,
        payload.filename,
        payload.file_size,
        origin,
    )
    if existing_media is not None:
        # Idempotent replay of an already-completed upload - nothing left
        # to send, the frontend should treat this as done.
        return {"success": True, "data": upload_session_start_response(session, None)}
    return {"success": True, "data": upload_session_start_response(session, upload_url)}


@router.post("/upload-complete")
def complete_direct_upload_route(
    payload: CompleteUploadRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
    storage: StorageService = Depends(get_storage_service),
    settings: Settings = Depends(get_settings),
):
    # Browser -> Drive direct upload, step 2 of 2: called once the
    # browser's direct PUT to the Drive resumable session URL has
    # finished. This server re-confirms the file with Drive itself
    # (never trusts the browser's report for the actual Media record),
    # then creates the Media row.
    media = complete_direct_upload(
        db,
        storage,
        settings,
        admin.id,
        payload.upload_id,
        payload.drive_file_id,
        payload.reported_size,
        payload.reported_mime_type,
    )
    _log(db, admin.id, "media_uploaded", media.id, request)
    return {"success": True, "data": media_to_response(media)}


@router.post("/upload-session/{upload_id}/abandon")
def abandon_direct_upload_route(
    upload_id: str,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    # Fired (best-effort, from the frontend) when the browser's own direct
    # PUT to Drive fails or is cancelled - this server was never in that
    # data path, so it has no other way to learn the attempt failed. Lets
    # an immediate retry with the same upload_id proceed instead of 409ing
    # as "already in progress" (Section 4/9).
    abandon_direct_upload(db, admin.id, upload_id)
    return {"success": True, "data": None}


@router.post("/upload-progress/{upload_id}")
def report_upload_progress_route(
    upload_id: str,
    payload: UploadProgressRequest,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    # Best-effort progress ping from the browser while it PUTs bytes
    # directly to Drive (Section 8) - purely cosmetic, throttled
    # client-side; never trusted for anything beyond display.
    session = report_upload_progress(db, admin.id, upload_id, payload.bytes_uploaded)
    return {"success": True, "data": upload_session_to_response(session)}


@router.get("/upload-status/{upload_id}")
def get_upload_status_route(
    upload_id: str,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    session = get_upload_session_status(db, admin.id, upload_id)
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