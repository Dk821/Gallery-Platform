"""
Platform operator API (role: super_admin).

Every route depends on require_super_admin, which re-reads the admin's role
from the database. A studio admin gets 403 here; a super admin does NOT get
access to a studio's galleries through these routes - they manage tenants,
quotas, credentials and audit history, not photographs.
"""

import csv
import datetime
import io
import json

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session as DbSession

from app.api.deps import require_super_admin
from app.database.connection import get_db
from app.models.admin import Admin
from app.schemas.errors import ApiError, bad_request
from app.schemas.pagination import build_page
from app.schemas.studio_settings import AdminChangePasswordRequest, SuperAdminAccountUpdateRequest
from app.security.session import ADMIN_COOKIE_NAME, create_admin_token, set_session_cookie
from app.schemas.studio import (
    AdminPasswordResetRequest,
    StudioAdminCreateRequest,
    StudioAdminUpdateRequest,
    StudioCreateRequest,
    StudioQuotaRequest,
    StudioStatusRequest,
    StudioUpdateRequest,
)
from app.services import audit_service, platform_logo_service, quota_reconciliation, quota_service, studio_logo_service, studio_service
from app.services.storage_provider import get_storage_service
from app.services.storage_service import StorageService
from app.services.admin_service import _UNSET, change_admin_password, sign_out_other_sessions, update_own_account
from app.models.audit_log import AuditLog

router = APIRouter(prefix="/api/super-admin", tags=["super-admin"])


def _no_store(response: Response) -> None:
    # Responses that carry a one-time temporary password must never be cached.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.get("/stats")
def platform_stats(db: DbSession = Depends(get_db), admin: Admin = Depends(require_super_admin)):
    return {"success": True, "data": studio_service.platform_stats(db)}


@router.get("/stats/trends")
def platform_trends(
    days: int = 30, db: DbSession = Depends(get_db), admin: Admin = Depends(require_super_admin)
):
    return {"success": True, "data": studio_service.platform_trends(db, days)}


@router.get("/studios")
def list_studios(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None, description="active | suspended"),
    search: str | None = Query(default=None, max_length=255),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    items, total, page, limit = studio_service.list_studios(db, page, limit, status, search)
    return {"success": True, "data": build_page(items, page, limit, total)}


@router.get("/logins")
def list_studio_logins(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    state: str | None = Query(default=None, description="active | disabled | none"),
    search: str | None = Query(default=None, max_length=255),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    items, total, page, limit = studio_service.list_studio_logins(db, page, limit, state, search)
    data = build_page(items, page, limit, total)
    data["summary"] = studio_service.studio_login_summary(db)
    return {"success": True, "data": data}


@router.get("/storage/reconcile")
def storage_check(db: DbSession = Depends(get_db), admin: Admin = Depends(require_super_admin)):
    """Report-only: compares every studio's stored/reserved counters with the real rows."""
    return {"success": True, "data": _drift_report(quota_reconciliation.reconcile_quota(db, apply=False))}


@router.post("/storage/reconcile")
def storage_repair(request: Request, db: DbSession = Depends(get_db), admin: Admin = Depends(require_super_admin)):
    """Repairs the counters from the real rows (what `python -m app.reconcile_quota --apply` does)."""
    before = quota_reconciliation.reconcile_quota(db, apply=False)
    result = quota_reconciliation.reconcile_quota(db, apply=True)
    audit_service.record_admin(
        db,
        admin,
        "storage_counters_repaired",
        request=request,
        resource_type="platform",
        metadata={"studios_repaired": before["studios_out_of_sync"], "platform_was_in_sync": before["platform"]["in_sync"]},
    )
    # `result` describes the state BEFORE the repair; report what is left afterwards.
    after = _drift_report(quota_reconciliation.reconcile_quota(db, apply=False))
    after.update(applied=True, repaired_studios=result["studios_out_of_sync"], stale_reservations=result["stale_reservations"])
    return {"success": True, "data": after}


def _drift_report(result: dict) -> dict:
    """Only the studios that need attention (counter drift or over quota) - not all of them."""
    flagged = [r for r in result["studios"] if not r["in_sync"] or r["over_quota"]]
    return {
        "applied": result["applied"],
        "checked_studios": len(result["studios"]),
        "studios_out_of_sync": result["studios_out_of_sync"],
        "platform": result["platform"],
        "stale_reservations": result["stale_reservations"],
        "studios": flagged,
    }


@router.post("/studios")
def create_studio(
    payload: StudioCreateRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    studio, studio_admin, temp_password = studio_service.create_studio(db, payload)
    audit_service.record_admin(
        db,
        admin,
        "studio_created",
        request=request,
        studio_id=studio.id,
        resource_type="studio",
        resource_id=studio.id,
        metadata={"name": studio.name, "quota_bytes": int(studio.quota_bytes), "admin_id": studio_admin.id},
    )
    _no_store(response)
    return {
        "success": True,
        "data": {
            "studio": studio_service.studio_to_dict(studio),
            "admin": {"id": studio_admin.id, "name": studio_admin.name, "email": studio_admin.email},
            # Present ONLY when the server generated it; shown once, never stored in plaintext.
            "temporary_password": temp_password,
        },
    }


@router.get("/studios/{studio_id}")
def get_studio(studio_id: int, db: DbSession = Depends(get_db), admin: Admin = Depends(require_super_admin)):
    studio = studio_service.get_studio_or_404(db, studio_id)
    return {"success": True, "data": studio_service.studio_detail(db, studio)}


@router.put("/studios/{studio_id}")
def update_studio(
    studio_id: int,
    payload: StudioUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    studio = studio_service.get_studio_or_404(db, studio_id)
    studio = studio_service.update_studio(db, studio, payload)
    audit_service.record_admin(
        db,
        admin,
        "studio_updated",
        request=request,
        studio_id=studio.id,
        resource_type="studio",
        resource_id=studio.id,
        metadata={"fields": sorted(payload.model_fields_set)},
    )
    return {"success": True, "data": studio_service.studio_to_dict(studio)}


@router.post("/studios/{studio_id}/logo")
def upload_studio_logo(
    studio_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
    storage: StorageService = Depends(get_storage_service),
):
    studio = studio_service.get_studio_or_404(db, studio_id)
    # Refuse an oversized body from its declared length before reading any of it.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > studio_logo_service.MAX_LOGO_UPLOAD_BYTES + 64 * 1024:
        raise ApiError(413, "LOGO_TOO_LARGE", "The logo must be 5 MB or smaller.")
    data = file.file.read(studio_logo_service.MAX_LOGO_UPLOAD_BYTES + 1)
    studio = studio_logo_service.save_logo(db, storage, studio, data)
    audit_service.record_admin(
        db,
        admin,
        "studio_logo_updated",
        request=request,
        studio_id=studio.id,
        resource_type="studio",
        resource_id=studio.id,
    )
    return {"success": True, "data": studio_service.studio_to_dict(studio)}


@router.delete("/studios/{studio_id}/logo")
def remove_studio_logo(
    studio_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
    storage: StorageService = Depends(get_storage_service),
):
    studio = studio_service.get_studio_or_404(db, studio_id)
    studio = studio_logo_service.remove_logo(db, storage, studio)
    audit_service.record_admin(
        db,
        admin,
        "studio_logo_removed",
        request=request,
        studio_id=studio.id,
        resource_type="studio",
        resource_id=studio.id,
    )
    return {"success": True, "data": studio_service.studio_to_dict(studio)}


@router.post("/studios/{studio_id}/suspend")
def suspend_studio(
    studio_id: int,
    request: Request,
    payload: StudioStatusRequest | None = None,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    studio = studio_service.get_studio_or_404(db, studio_id)
    studio = studio_service.set_status(db, studio, "suspended")
    audit_service.record_admin(
        db,
        admin,
        "studio_suspended",
        request=request,
        studio_id=studio.id,
        resource_type="studio",
        resource_id=studio.id,
        metadata={"reason": payload.reason if payload else None},
    )
    return {"success": True, "data": studio_service.studio_to_dict(studio)}


@router.delete("/studios/{studio_id}")
def delete_studio(
    studio_id: int,
    request: Request,
    delete_data: bool = False,
    confirm_name: str | None = None,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
    storage: StorageService = Depends(get_storage_service),
):
    """
    Permanently deletes a studio together with its single login. It must be suspended first
    (409 STUDIO_NOT_SUSPENDED). By default it must also be empty (409 STUDIO_NOT_EMPTY).

    `?delete_data=true&confirm_name=<exact studio name>` deletes the studio AND everything it holds:
    its clients, albums, photos/videos (database rows and stored files), comments, wishlists,
    download history and upload sessions. The exact name is required (400 CONFIRMATION_MISMATCH).
    """
    studio = studio_service.get_studio_or_404(db, studio_id)
    deleted = studio_service.delete_studio(db, studio, storage, delete_data=delete_data, confirm_name=confirm_name)
    # The studio row is gone, so the audit row is not tied to it (studio_id stays empty); the id is kept in the metadata.
    audit_service.record_admin(
        db,
        admin,
        "studio_deleted",
        request=request,
        studio_id=None,
        resource_type="studio",
        resource_id=deleted["id"],
        metadata={"name": deleted["name"], "studio_id": deleted["id"]}
        | ({k: v for k, v in deleted.items() if k not in ("id", "name")} if deleted["data_deleted"] else {}),
    )
    return {"success": True, "data": {"id": deleted["id"], "deleted": True, **({"data_deleted": True, "storage_failures": deleted.get("storage_failures", 0)} if deleted["data_deleted"] else {})}}


@router.post("/studios/{studio_id}/reactivate")
def reactivate_studio(
    studio_id: int,
    request: Request,
    payload: StudioStatusRequest | None = None,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    studio = studio_service.get_studio_or_404(db, studio_id)
    studio = studio_service.set_status(db, studio, "active")
    audit_service.record_admin(
        db,
        admin,
        "studio_reactivated",
        request=request,
        studio_id=studio.id,
        resource_type="studio",
        resource_id=studio.id,
        metadata={"reason": payload.reason if payload else None},
    )
    return {"success": True, "data": studio_service.studio_to_dict(studio)}


@router.put("/studios/{studio_id}/quota")
def set_studio_quota(
    studio_id: int,
    payload: StudioQuotaRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    studio = studio_service.get_studio_or_404(db, studio_id)
    studio, previous = studio_service.set_quota(db, studio, payload.quota_bytes)
    audit_service.record_admin(
        db,
        admin,
        "studio_quota_changed",
        request=request,
        studio_id=studio.id,
        resource_type="studio",
        resource_id=studio.id,
        metadata={"old_quota_bytes": previous, "new_quota_bytes": int(studio.quota_bytes)},
    )
    return {"success": True, "data": studio_service.studio_to_dict(studio)}


@router.get("/studios/{studio_id}/usage")
def get_studio_usage(studio_id: int, db: DbSession = Depends(get_db), admin: Admin = Depends(require_super_admin)):
    studio = studio_service.get_studio_or_404(db, studio_id)
    return {
        "success": True,
        "data": {
            "studio_id": studio.id,
            "usage": quota_service.studio_usage(studio),
            "counts": studio_service.studio_counts(db, studio.id),
            "platform": quota_service.get_platform_usage(db),
        },
    }


@router.get("/studios/{studio_id}/admins")
def list_studio_admins(studio_id: int, db: DbSession = Depends(get_db), admin: Admin = Depends(require_super_admin)):
    studio = studio_service.get_studio_or_404(db, studio_id)
    return {"success": True, "data": studio_service.list_studio_admins(db, studio.id)}


@router.post("/studios/{studio_id}/admins")
def create_studio_admin(
    studio_id: int,
    payload: StudioAdminCreateRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    """
    Gives a studio that has NO login its login (recovery only). One login per studio: a studio that
    already has one - active or disabled - gets 409 STUDIO_USER_LIMIT. New studios get their login
    from POST /studios.
    """
    studio = studio_service.get_studio_or_404(db, studio_id)
    new_admin, temp_password = studio_service.create_studio_admin(db, studio, payload)
    audit_service.record_admin(
        db,
        admin,
        "studio_admin_created",
        request=request,
        studio_id=studio.id,
        resource_type="admin",
        resource_id=new_admin.id,
    )
    _no_store(response)
    return {
        "success": True,
        "data": {
            "admin": {"id": new_admin.id, "name": new_admin.name, "email": new_admin.email},
            "temporary_password": temp_password,
        },
    }


@router.put("/studios/{studio_id}/admins/{admin_id}")
def update_studio_admin(
    studio_id: int,
    admin_id: int,
    payload: StudioAdminUpdateRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    studio = studio_service.get_studio_or_404(db, studio_id)
    target, changed = studio_service.update_studio_admin(db, studio, admin_id, payload.name, payload.email)
    audit_service.record_admin(
        db,
        admin,
        "studio_admin_updated",
        request=request,
        studio_id=studio.id,
        resource_type="admin",
        resource_id=target.id,
        metadata={"changed": sorted(changed)},
    )
    return {
        "success": True,
        "data": {"id": target.id, "name": target.name, "email": target.email, "status": target.status, "created_at": target.created_at},
    }


@router.post("/studios/{studio_id}/admins/{admin_id}/disable")
def disable_studio_admin(
    studio_id: int,
    admin_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    studio = studio_service.get_studio_or_404(db, studio_id)
    target = studio_service.set_studio_admin_status(db, studio, admin_id, "disabled")
    audit_service.record_admin(
        db, admin, "studio_admin_disabled", request=request, studio_id=studio.id, resource_type="admin", resource_id=target.id
    )
    return {"success": True, "data": {"id": target.id, "status": target.status}}


@router.post("/studios/{studio_id}/admins/{admin_id}/enable")
def enable_studio_admin(
    studio_id: int,
    admin_id: int,
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    studio = studio_service.get_studio_or_404(db, studio_id)
    target = studio_service.set_studio_admin_status(db, studio, admin_id, "active")
    audit_service.record_admin(
        db, admin, "studio_admin_enabled", request=request, studio_id=studio.id, resource_type="admin", resource_id=target.id
    )
    return {"success": True, "data": {"id": target.id, "status": target.status}}


@router.post("/studios/{studio_id}/admins/{admin_id}/reset-password")
def reset_studio_admin_password(
    studio_id: int,
    admin_id: int,
    request: Request,
    response: Response,
    payload: AdminPasswordResetRequest | None = None,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    studio = studio_service.get_studio_or_404(db, studio_id)
    target, temp_password = studio_service.reset_studio_admin_password(
        db, studio, admin_id, payload.new_password if payload else None
    )
    # NOTE: no password material in the audit row - only that a reset happened.
    audit_service.record_admin(
        db,
        admin,
        "studio_admin_password_reset",
        request=request,
        studio_id=studio.id,
        resource_type="admin",
        resource_id=target.id,
        metadata={"generated": temp_password is not None},
    )
    _no_store(response)
    return {"success": True, "data": {"admin_id": target.id, "temporary_password": temp_password}}


def _audit_filters(studio_id, action, date_from, date_to, category, actor, search, tz_offset) -> dict:
    if date_from and date_to and date_from > date_to:
        raise bad_request("'from' must not be after 'to'.", code="INVALID_DATE_RANGE")
    return dict(
        studio_id=studio_id, action=action, date_from=date_from, date_to=date_to, category=category, actor=actor, search=search,
        tz_offset_minutes=tz_offset,
    )


@router.get("/audit-logs")
def list_audit_logs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    studio_id: int | None = Query(default=None, ge=1),
    action: str | None = Query(default=None, max_length=100),
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    category: str | None = Query(default=None, description="sign_in | studios | logins | storage | content | problems"),
    actor: str | None = Query(default=None, description="super_admin | studio_admin | client"),
    search: str | None = Query(default=None, max_length=100),
    sort: str = Query(default="newest", pattern="^(newest|oldest)$"),
    tz_offset: int = Query(default=0, ge=-840, le=840, description="viewer's minutes east of UTC; makes from/to local days"),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    filters = _audit_filters(studio_id, action, date_from, date_to, category, actor, search, tz_offset)
    items, total, page, limit = studio_service.list_audit_logs(db, page, limit, oldest_first=sort == "oldest", **filters)
    data = build_page(items, page, limit, total)
    data["summary"] = studio_service.audit_summary(db)
    return {"success": True, "data": data}


def _csv_safe(value) -> str:
    """CSV cell text that a spreadsheet will not treat as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/audit-logs/export")
def export_audit_logs(
    request: Request,
    studio_id: int | None = Query(default=None, ge=1),
    action: str | None = Query(default=None, max_length=100),
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    category: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    tz_offset: int = Query(default=0, ge=-840, le=840),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    """CSV of the entries matching the same filters as the list (newest first, at most 10,000 rows)."""
    filters = _audit_filters(studio_id, action, date_from, date_to, category, actor, search, tz_offset)
    rows, total = studio_service.export_audit_logs(db, **filters)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "when_utc", "action", "studio_id", "studio", "actor_role", "user_type", "user_id", "resource_type", "resource_id", "ip_address", "details"])
    for r in rows:
        writer.writerow(
            [
                r["id"],
                r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r["created_at"] else "",
                _csv_safe(r["action"]),
                r["studio_id"] or "",
                _csv_safe(r["studio_name"]),
                _csv_safe(r["actor_role"]),
                r["user_type"],
                r["user_id"] or "",
                _csv_safe(r["resource_type"]),
                r["resource_id"] or "",
                _csv_safe(r["ip_address"]),
                _csv_safe(json.dumps(r["metadata"], sort_keys=True) if r["metadata"] else ""),
            ]
        )
    audit_service.record_admin(
        db,
        admin,
        "audit_log_exported",
        request=request,
        resource_type="audit_log",
        metadata={"rows": len(rows), "matching": total, "filters": {k: str(v) for k, v in filters.items() if v}},
    )
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M")
    return Response(
        content="\ufeff" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="audit-log-{stamp}.csv"', "Cache-Control": "no-store"},
    )


@router.post("/change-password")
def change_own_password(
    payload: AdminChangePasswordRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    """The signed-in super admin changes their OWN password (current one required)."""
    change_admin_password(db, admin, payload.current_password, payload.new_password)
    # change_admin_password bumped session_version, which signs every OTHER
    # session out; re-issue this browser's cookie so it stays signed in.
    set_session_cookie(response, ADMIN_COOKIE_NAME, create_admin_token(admin.id, admin.session_version))
    _no_store(response)
    # NOTE: no password material in the audit row - only that a change happened.
    audit_service.record_admin(
        db,
        admin,
        "super_admin_password_changed",
        request=request,
        resource_type="admin",
        resource_id=admin.id,
    )
    return {"success": True, "data": None}


def _account(db: DbSession, admin: Admin) -> dict:
    """The signed-in super admin's own details and their recent sign-in attempts (newest first)."""
    rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_type == "admin",
            AuditLog.user_id == admin.id,
            AuditLog.action.in_(("admin_login", "admin_login_failed")),
        )
        .order_by(AuditLog.id.desc())
        .limit(10)
        .all()
    )
    return {
        "name": admin.name,
        "email": admin.email,
        "role": admin.role,
        "company_name": admin.company_name,
        "contact_phone": admin.contact_phone,
        "logo_url": admin.logo_url,
        "created_at": admin.created_at,
        "recent_sign_ins": [
            {"at": r.created_at, "ip_address": r.ip_address, "success": r.action == "admin_login"} for r in rows
        ],
    }


@router.get("/account")
def get_own_account(db: DbSession = Depends(get_db), admin: Admin = Depends(require_super_admin)):
    return {"success": True, "data": _account(db, admin)}


@router.put("/account")
def update_own_account_route(
    payload: SuperAdminAccountUpdateRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    """Edit the signed-in super admin's own name / sign-in email (the current password is required for the email)."""
    sent = payload.model_fields_set
    changed = update_own_account(
        db,
        admin,
        payload.name,
        payload.email,
        payload.current_password,
        company_name=payload.company_name if "company_name" in sent else _UNSET,
        contact_phone=payload.contact_phone if "contact_phone" in sent else _UNSET,
    )
    _no_store(response)
    if any(changed.values()):
        # NOTE: only which fields changed - never the values or any password.
        audit_service.record_admin(
            db,
            admin,
            "super_admin_account_updated",
            request=request,
            resource_type="admin",
            resource_id=admin.id,
            metadata={"fields": [k for k, v in changed.items() if v]},
        )
    return {"success": True, "data": _account(db, admin)}


@router.post("/account/logo")
def upload_own_logo(
    request: Request,
    file: UploadFile = File(...),
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
    storage: StorageService = Depends(get_storage_service),
):
    """Upload / replace the company logo shown in the console sidebar."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > platform_logo_service.MAX_LOGO_UPLOAD_BYTES + 64 * 1024:
        raise ApiError(413, "LOGO_TOO_LARGE", "The logo must be 5 MB or smaller.")
    data = file.file.read(platform_logo_service.MAX_LOGO_UPLOAD_BYTES + 1)
    platform_logo_service.save_logo(db, storage, admin, data)
    audit_service.record_admin(
        db, admin, "super_admin_logo_updated", request=request, resource_type="admin", resource_id=admin.id
    )
    return {"success": True, "data": _account(db, admin)}


@router.delete("/account/logo")
def remove_own_logo(
    request: Request,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
    storage: StorageService = Depends(get_storage_service),
):
    platform_logo_service.remove_logo(db, storage, admin)
    audit_service.record_admin(
        db, admin, "super_admin_logo_removed", request=request, resource_type="admin", resource_id=admin.id
    )
    return {"success": True, "data": _account(db, admin)}


@router.post("/sign-out-others")
def sign_out_other_devices(
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    admin: Admin = Depends(require_super_admin),
):
    """Signs this super admin out of every OTHER browser/device; this one stays signed in."""
    sign_out_other_sessions(db, admin)
    set_session_cookie(response, ADMIN_COOKIE_NAME, create_admin_token(admin.id, admin.session_version))
    _no_store(response)
    audit_service.record_admin(
        db, admin, "super_admin_signed_out_other_devices", request=request, resource_type="admin", resource_id=admin.id
    )
    return {"success": True, "data": None}
