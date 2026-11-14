import datetime
import logging
import secrets

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.config.settings import get_settings
from app.models.admin import Admin
from app.models.album import Album
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.download_record import DownloadRecord
from app.models.media import Media
from app.models.studio import Studio
from app.models.upload_session import UploadSession
from app.schemas.errors import ApiError, bad_request, not_found
from app.schemas.pagination import paginate_params
from app.schemas.studio import (
    StudioAdminCreateRequest,
    StudioCreateRequest,
    StudioUpdateRequest,
)
from app.security.password import hash_password
from app.services.storage_paths import build_studio_prefix
from app.services.studio_slug import build_studio_slug, gallery_path
from app.services import quota_service

logger = logging.getLogger("gallery.studios")


def generate_temp_password() -> str:
    # ~19 url-safe chars = ~100 bits. Returned to the caller exactly once and
    # never written to logs, audit rows or the database in plaintext.
    return secrets.token_urlsafe(14)


# --------------------------------------------------------------------- reads
def get_studio_or_404(db: DbSession, studio_id: int) -> Studio:
    studio = db.get(Studio, studio_id)
    if studio is None:
        raise not_found("Studio not found.", code="STUDIO_NOT_FOUND")
    return studio


def studio_to_dict(studio: Studio) -> dict:
    return {
        "id": studio.id,
        "name": studio.name,
        "contact_email": studio.contact_email,
        "contact_phone": studio.contact_phone,
        "logo_url": studio.logo_url,
        "brand_color": studio.brand_color,
        "status": studio.status,
        "created_at": studio.created_at,
        "updated_at": studio.updated_at,
        "usage": quota_service.studio_usage(studio),
    }


def client_facing_branding(db: DbSession, studio_id: int | None) -> dict | None:
    """
    What a studio's CLIENTS may see of the studio on their gallery pages: its name, logo, brand colour
    and contact details - the same public face the studio shows everywhere. Nothing else (no quota, usage,
    status or other studio data). None for a legacy client that is not mapped to a studio yet.
    """
    studio = db.get(Studio, studio_id) if studio_id is not None else None
    if studio is None:
        return None
    return {
        "name": studio.name,
        "slug": studio.slug,
        "logo_url": studio.logo_url,
        "brand_color": studio.brand_color,
        "contact_email": studio.contact_email,
        "contact_phone": studio.contact_phone,
    }


def gallery_url_path(db: DbSession, client) -> str:
    """The link a studio shares with a client: /<studio slug>/gallery/<link id> (the older /gallery/<link id> for a studio without a slug)."""
    studio = db.get(Studio, client.studio_id) if client.studio_id is not None else None
    return gallery_path(studio.slug if studio is not None else None, client.client_uuid)


def list_studios(db: DbSession, page: int, limit: int, status: str | None = None, search: str | None = None):
    page, limit = paginate_params(page, limit)
    query = db.query(Studio)
    if status:
        if status not in ("active", "suspended"):
            raise bad_request("status must be 'active' or 'suspended'.", code="INVALID_STATUS")
        query = query.filter(Studio.status == status)
    if search:
        query = query.filter(Studio.name.ilike(f"%{search.strip()}%"))
    total = query.count()
    rows = query.order_by(Studio.created_at.desc(), Studio.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return [studio_to_dict(s) for s in rows], total, page, limit


LOGIN_STATES = ("active", "disabled", "none")


def list_studio_logins(db: DbSession, page: int, limit: int, state: str | None = None, search: str | None = None):
    """
    One row per studio with its single login (or none): the platform-wide "Studio logins" page.
    `state`: active | disabled | none (studio has no login). `search` matches the studio name,
    the login's name or its email. Last sign-in comes from the audit trail (`admin_login`).
    """
    page, limit = paginate_params(page, limit)
    if state and state not in LOGIN_STATES:
        raise bad_request("state must be 'active', 'disabled' or 'none'.", code="INVALID_STATE")
    query = db.query(Studio, Admin).outerjoin(Admin, (Admin.studio_id == Studio.id) & (Admin.role == "studio_admin"))
    if state == "none":
        query = query.filter(Admin.id.is_(None))
    elif state:
        query = query.filter(Admin.status == state)
    if search and search.strip():
        like = f"%{search.strip()}%"
        query = query.filter(Studio.name.ilike(like) | Admin.name.ilike(like) | Admin.email.ilike(like))
    total = query.count()
    rows = query.order_by(Studio.name.asc(), Studio.id.asc()).offset((page - 1) * limit).limit(limit).all()

    admin_ids = [a.id for _, a in rows if a is not None]
    last = (
        {
            int(uid): when
            for uid, when in db.query(AuditLog.user_id, func.max(AuditLog.created_at))
            .filter(AuditLog.user_type == "admin", AuditLog.action == "admin_login", AuditLog.user_id.in_(admin_ids))
            .group_by(AuditLog.user_id)
            .all()
        }
        if admin_ids
        else {}
    )
    items = [
        {
            "studio_id": s.id,
            "studio_name": s.name,
            "studio_status": s.status,
            "login": None
            if a is None
            else {
                "id": a.id,
                "name": a.name,
                "email": a.email,
                "status": a.status,
                "created_at": a.created_at,
                "last_login": last.get(a.id),
            },
        }
        for s, a in rows
    ]
    return items, total, page, limit


def studio_login_summary(db: DbSession) -> dict:
    """Counts for the filter chips; each one equals the total the matching list filter returns."""
    by_status = dict(
        db.query(Admin.status, func.count(Studio.id))
        .select_from(Studio)
        .outerjoin(Admin, (Admin.studio_id == Studio.id) & (Admin.role == "studio_admin"))
        .group_by(Admin.status)
        .all()
    )
    active, disabled, none = int(by_status.get("active", 0)), int(by_status.get("disabled", 0)), int(by_status.get(None, 0))
    return {"studios": active + disabled + none, "active": active, "disabled": disabled, "none": none}


def studio_counts(db: DbSession, studio_id: int) -> dict:
    return {
        "admins": db.query(func.count(Admin.id)).filter(Admin.studio_id == studio_id).scalar() or 0,
        "clients": db.query(func.count(Client.id)).filter(Client.studio_id == studio_id).scalar() or 0,
        "albums": db.query(func.count(Album.id)).filter(Album.studio_id == studio_id).scalar() or 0,
        "media": db.query(func.count(Media.id)).filter(Media.studio_id == studio_id).scalar() or 0,
    }


def studio_detail(db: DbSession, studio: Studio) -> dict:
    data = studio_to_dict(studio)
    data["counts"] = studio_counts(db, studio.id)
    return data


def platform_stats(db: DbSession) -> dict:
    by_status = dict(db.query(Studio.status, func.count(Studio.id)).group_by(Studio.status).all())
    unmapped = {
        "admins": db.query(func.count(Admin.id))
        .filter(Admin.role == "studio_admin", Admin.studio_id.is_(None))
        .scalar()
        or 0,
        "clients": db.query(func.count(Client.id)).filter(Client.studio_id.is_(None)).scalar() or 0,
        "albums": db.query(func.count(Album.id)).filter(Album.studio_id.is_(None)).scalar() or 0,
        "media": db.query(func.count(Media.id)).filter(Media.studio_id.is_(None)).scalar() or 0,
    }
    return {
        "studios": {
            "total": sum(by_status.values()),
            "active": by_status.get("active", 0),
            "suspended": by_status.get("suspended", 0),
        },
        "totals": {
            "clients": db.query(func.count(Client.id)).scalar() or 0,
            "albums": db.query(func.count(Album.id)).scalar() or 0,
            "media": db.query(func.count(Media.id)).scalar() or 0,
        },
        "storage": quota_service.get_platform_usage(db),
        # Legacy rows not yet assigned to a studio. Non-zero means the
        # `python -m app.legacy_to_studio` step still has to be run.
        "unmapped_legacy_rows": unmapped,
    }


TREND_RANGES = (7, 30, 90)


def _daily(db: DbSession, column, since: datetime.datetime, *aggregates, extra_filter=None, until=None) -> dict[str, tuple]:
    """{ 'YYYY-MM-DD': (aggregate values...) } for rows whose `column` is on/after `since` (and before `until`)."""
    day = func.date(column)
    query = db.query(day, *aggregates).filter(column >= since)
    if until is not None:
        query = query.filter(column < until)
    if extra_filter is not None:
        query = query.filter(extra_filter)
    return {str(d): tuple(int(v or 0) for v in vals) for d, *vals in query.group_by(day).all()}


def platform_trends(
    db: DbSession, days: int = 30, start_date: datetime.date | None = None, end_date: datetime.date | None = None
) -> dict:
    """
    Daily activity across the platform for the dashboard charts (read-only, additive):
    new studios / clients / albums / media, bytes uploaded, downloads and bytes downloaded,
    one bucket per day for the last `days` days (oldest first, empty days are zero), plus the
    totals of the same length period right before it so the UI can show a change.
    """
    today = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    if start_date is not None and end_date is not None:
        # Custom range (UTC days, inclusive): end capped at today, at most one year.
        end = min(datetime.datetime.combine(end_date, datetime.time()), today)
        start = min(datetime.datetime.combine(start_date, datetime.time()), end)
        start = max(start, end - datetime.timedelta(days=365))
        days = (end - start).days + 1
    else:
        days = days if days in TREND_RANGES else 30
        end = today
        start = today - datetime.timedelta(days=days - 1)
    until = end + datetime.timedelta(days=1)
    prev_start = start - datetime.timedelta(days=days)

    media_ok = Media.status != "failed"
    new_studios = _daily(db, Studio.created_at, prev_start, func.count(Studio.id), until=until)
    new_clients = _daily(db, Client.created_at, prev_start, func.count(Client.id), until=until)
    new_albums = _daily(db, Album.created_at, prev_start, func.count(Album.id), until=until)
    new_media = _daily(db, Media.created_at, prev_start, func.count(Media.id), func.sum(Media.file_size), extra_filter=media_ok, until=until)
    downloads = _daily(
        db,
        DownloadRecord.downloaded_at,
        prev_start,
        func.count(DownloadRecord.id),
        func.sum(DownloadRecord.total_bytes),
        until=until,
    )

    def at(source: dict, key: str, idx: int = 0) -> int:
        return source.get(key, (0, 0))[idx]

    series, current, previous = [], dict.fromkeys(("studios", "clients", "albums", "media", "uploaded_bytes", "downloads", "downloaded_bytes"), 0), None
    previous = dict(current)
    for offset in range(days * 2):
        d = prev_start + datetime.timedelta(days=offset)
        key = d.strftime("%Y-%m-%d")
        row = {
            "studios": at(new_studios, key),
            "clients": at(new_clients, key),
            "albums": at(new_albums, key),
            "media": at(new_media, key),
            "uploaded_bytes": at(new_media, key, 1),
            "downloads": at(downloads, key),
            "downloaded_bytes": at(downloads, key, 1),
        }
        bucket = current if offset >= days else previous
        for name, value in row.items():
            bucket[name] += value
        if offset >= days:
            series.append({"date": key, **row})

    kinds = {
        kind: {"files": int(files or 0), "bytes": int(size or 0)}
        for kind, files, size in db.query(Media.file_type, func.count(Media.id), func.sum(Media.file_size))
        .filter(media_ok)
        .group_by(Media.file_type)
        .all()
    }
    active = (
        db.query(Media.studio_id, func.count(Media.id), func.sum(Media.file_size))
        .filter(Media.created_at >= start, Media.created_at < until, media_ok, Media.studio_id.isnot(None))
        .group_by(Media.studio_id)
        .order_by(func.sum(Media.file_size).desc())
        .limit(5)
        .all()
    )
    names = {sid: name for sid, name in db.query(Studio.id, Studio.name).filter(Studio.id.in_([a[0] for a in active])).all()} if active else {}
    return {
        "range_days": days,
        "series": series,
        "totals": current,
        "previous_totals": previous,
        "media_types": {"photo": kinds.get("photo", {"files": 0, "bytes": 0}), "video": kinds.get("video", {"files": 0, "bytes": 0})},
        "most_active_studios": [
            {"studio_id": sid, "name": names.get(sid, f"Studio #{sid}"), "files": int(files or 0), "uploaded_bytes": int(size or 0)}
            for sid, files, size in active
        ],
    }


# -------------------------------------------------------------------- writes
def _new_admin(name: str, email: str, studio_id: int, password: str) -> Admin:
    return Admin(
        name=name,
        email=str(email).lower(),
        password_hash=hash_password(password),
        status="active",
        role="studio_admin",
        studio_id=studio_id,
    )


def create_studio(db: DbSession, payload: StudioCreateRequest) -> tuple[Studio, Admin, str | None]:
    """
    Creates the studio and its first studio-admin login in ONE transaction.
    Returns (studio, admin, temporary_password) where temporary_password is
    only non-None when we generated it (so the super admin can hand it over).
    """
    settings = get_settings()
    quota = payload.quota_bytes if payload.quota_bytes is not None else settings.default_studio_quota_bytes
    temp_password = None
    password = payload.admin_password
    if not password:
        password = temp_password = generate_temp_password()

    if db.query(Admin.id).filter(Admin.email == str(payload.admin_email).lower()).first():
        raise ApiError(409, "ADMIN_EMAIL_EXISTS", "An admin with this email already exists.")

    studio = Studio(
        slug=build_studio_slug(db, payload.name),
        name=payload.name,
        contact_email=str(payload.contact_email) if payload.contact_email else None,
        contact_phone=payload.contact_phone,
        logo_url=payload.logo_url,
        brand_color=payload.brand_color,
        status="active",
        quota_bytes=quota,
        used_bytes=0,
        reserved_bytes=0,
    )
    try:
        db.add(studio)
        db.flush()
        # Readable, permanent storage folder: needs the id, so it is set after the flush.
        studio.storage_prefix = build_studio_prefix(studio.name, studio.id)
        admin = _new_admin(payload.admin_name, payload.admin_email, studio.id, password)
        db.add(admin)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "ADMIN_EMAIL_EXISTS", "An admin with this email already exists.")
    db.refresh(studio)
    db.refresh(admin)
    return studio, admin, temp_password


def update_studio(db: DbSession, studio: Studio, payload: StudioUpdateRequest) -> Studio:
    fields = payload.model_fields_set
    for field in ("name", "contact_email", "contact_phone", "logo_url", "brand_color"):
        if field in fields:
            value = getattr(payload, field)
            if field == "name" and value is None:
                continue  # name is required; null means "leave unchanged"
            setattr(studio, field, str(value) if field == "contact_email" and value is not None else value)
    db.commit()
    db.refresh(studio)
    return studio


def set_status(db: DbSession, studio: Studio, status: str) -> Studio:
    if status not in ("active", "suspended"):
        raise bad_request("Invalid status.", code="INVALID_STATUS")
    studio.status = status
    db.commit()
    db.refresh(studio)
    return studio


def set_quota(db: DbSession, studio: Studio, quota_bytes: int) -> tuple[Studio, int]:
    """Returns (studio, previous_quota). Refuses to set a quota below what the studio already holds."""
    db.refresh(studio)
    held = int(studio.used_bytes) + int(studio.reserved_bytes)
    if quota_bytes < held:
        raise ApiError(
            409,
            "QUOTA_BELOW_USAGE",
            f"The new quota ({quota_bytes} bytes) is below current usage plus reservations ({held} bytes).",
        )
    previous = int(studio.quota_bytes)
    studio.quota_bytes = quota_bytes
    db.commit()
    db.refresh(studio)
    return studio, previous


def _purge_studio_rows(db: DbSession, studio: Studio) -> None:
    """
    Deletes every row that belongs to the studio, children first, WITHOUT committing (the caller
    commits once, so the studio is removed completely or not at all). Done explicitly rather than
    relying on ON DELETE CASCADE, which SQLite (the test database) does not enforce.
    """
    from app.models.album_comment import AlbumComment
    from app.models.download_job import DownloadJob
    from app.models.download_record import DownloadRecord
    from app.models.media_wishlist import MediaWishlist
    from app.models.platform_storage import PlatformStorage
    from app.models.session import ClientSession
    from app.models.studio_settings import StudioSettings
    from sqlalchemy import select

    sid = studio.id
    clients = select(Client.id).where(Client.studio_id == sid)
    albums = select(Album.id).where((Album.studio_id == sid) | (Album.client_id.in_(clients)))
    logins = select(Admin.id).where(Admin.studio_id == sid)

    def gone(model, *conditions):
        db.query(model).filter(*conditions).delete(synchronize_session=False)

    gone(MediaWishlist, MediaWishlist.client_id.in_(clients))
    gone(AlbumComment, AlbumComment.album_id.in_(albums))
    gone(ClientSession, ClientSession.client_id.in_(clients))
    gone(DownloadRecord, (DownloadRecord.studio_id == sid) | DownloadRecord.client_id.in_(clients))
    gone(DownloadJob, (DownloadJob.studio_id == sid) | DownloadJob.client_id.in_(clients))
    gone(UploadSession, (UploadSession.studio_id == sid) | UploadSession.album_id.in_(albums) | UploadSession.admin_id.in_(logins))
    gone(Media, (Media.studio_id == sid) | Media.client_id.in_(clients))
    # MySQL refuses a subquery on the table being deleted from (error 1093), so no `albums` subquery here.
    gone(Album, (Album.studio_id == sid) | Album.client_id.in_(clients))
    gone(Client, Client.studio_id == sid)
    gone(Admin, Admin.studio_id == sid)
    gone(StudioSettings, StudioSettings.studio_id == sid)

    # The platform-wide storage ledger gives back what this studio held, so the platform capacity
    # figures stay true (same clamped arithmetic as every other release of usage).
    used, reserved = int(studio.used_bytes or 0), int(studio.reserved_bytes or 0)
    quota_service.ensure_platform_row(db)
    db.query(PlatformStorage).filter(PlatformStorage.id == quota_service.PLATFORM_ROW_ID).update(
        {
            PlatformStorage.used_bytes: quota_service._clamped_sub(PlatformStorage.used_bytes, used),
            PlatformStorage.reserved_bytes: quota_service._clamped_sub(PlatformStorage.reserved_bytes, reserved),
        },
        synchronize_session=False,
    )
    db.delete(studio)


def _collect_studio_objects(db: DbSession, studio: Studio) -> dict:
    """Everything the studio has in object storage (read BEFORE the rows are deleted)."""
    from app.models.download_job import DownloadJob

    sid = studio.id
    clients = db.query(Client.id).filter(Client.studio_id == sid)
    keys: set[str] = set()
    for row in db.query(Media.google_drive_file_id, Media.storage_key, Media.thumbnail_reference).filter(
        (Media.studio_id == sid) | Media.client_id.in_(clients)
    ):
        keys.update(k for k in row if k)
    folders = {
        f
        for (f,) in db.query(Client.thumbnail_folder_id).filter(Client.studio_id == sid, Client.thumbnail_folder_id.isnot(None))
        if f
    }
    zips = [
        z
        for (z,) in db.query(DownloadJob.zip_path).filter(
            (DownloadJob.studio_id == sid) | DownloadJob.client_id.in_(clients), DownloadJob.zip_path.isnot(None)
        )
        if z
    ]
    return {"keys": keys, "folders": folders, "zips": zips}


def _purge_studio_storage(storage, studio_id: int, studio_prefix: str | None, objects: dict) -> dict:
    """
    Removes the studio's stored files after its rows are gone. Never touches another studio's
    objects: every key and folder must pass storage.owns_object() for THIS studio, and the whole-folder
    sweep only runs on the studio's own root folder. Failures are counted, not raised - the rows are
    already deleted, and anything left behind is an orphan that `python -m app.reconcile_orphans` lists.
    """
    import os

    failed = 0
    deleted = 0
    for key in sorted(objects["keys"]):
        if not storage.owns_object(key, studio_id):
            continue
        try:
            storage.delete(key)
            deleted += 1
        except Exception:  # noqa: BLE001
            failed += 1
            logger.warning("could not delete object %s of purged studio %s", key, studio_id)
    for folder in sorted(objects["folders"]):
        if not storage.owns_object(folder.rstrip("/") + "/x", studio_id):
            continue
        try:
            storage.delete_folder(folder)
        except Exception:  # noqa: BLE001
            failed += 1
            logger.warning("could not delete folder %s of purged studio %s", folder, studio_id)
    root = storage.tenant_root_folder(studio_id, studio_prefix)
    if root and storage.owns_object(root.rstrip("/") + "/x", studio_id):
        try:
            storage.delete_folder(root)
        except Exception:  # noqa: BLE001
            failed += 1
            logger.warning("could not sweep storage folder %s of purged studio %s", root, studio_id)
    for path in objects["zips"]:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            logger.warning("could not remove ZIP file of purged studio %s", studio_id)
    return {"objects_deleted": deleted, "storage_failures": failed}


def delete_studio(db: DbSession, studio: Studio, storage, *, delete_data: bool = False, confirm_name: str | None = None) -> dict:
    """
    Permanently delete a studio. Deliberately hard to do by accident:

      1. it must be SUSPENDED first,
      2. by default it must hold no clients, albums, media or storage - nothing is removed but the
         studio, its settings, its logo and its single studio login;
      3. with delete_data=True (the super admin's "delete the studio AND all of its data") the
         studio's clients, albums, photos/videos, comments, wishlists, download history, upload
         sessions and stored files are removed too. That needs the exact studio name as confirmation.

    Audit rows are kept (their studio_id becomes empty). Returns what was deleted, for the audit row.
    """
    from app.services import studio_logo_service  # local import: avoids a cycle at module load

    if studio.status != "suspended":
        raise ApiError(409, "STUDIO_NOT_SUSPENDED", "Suspend this studio first, then delete it.")
    counts = studio_counts(db, studio.id)
    held = counts["clients"] or counts["albums"] or counts["media"] or int(studio.used_bytes) or int(studio.reserved_bytes)
    if held and not delete_data:
        raise ApiError(
            409,
            "STUDIO_NOT_EMPTY",
            "This studio still holds clients, albums or files. Choose \"Delete studio and all its data\" to remove it together with everything it holds.",
        )
    if delete_data and (confirm_name or "").strip() != studio.name.strip():
        raise ApiError(400, "CONFIRMATION_MISMATCH", "Type the studio's exact name to confirm deleting it with all of its data.")

    info = {
        "id": studio.id,
        "name": studio.name,
        "data_deleted": bool(delete_data),
        "clients": counts["clients"],
        "albums": counts["albums"],
        "media": counts["media"],
        "bytes": int(studio.used_bytes or 0),
    }
    version = studio_logo_service.uploaded_version(studio)
    logo_key = studio_logo_service.logo_key(studio, version) if version else None
    objects = _collect_studio_objects(db, studio) if delete_data else None
    # Read now: the row is gone (and its instance unusable) by the time storage is swept.
    studio_id, studio_prefix = studio.id, studio.storage_prefix
    try:
        if delete_data:
            _purge_studio_rows(db, studio)
        else:
            login_ids = [row[0] for row in db.query(Admin.id).filter(Admin.studio_id == studio.id).all()]
            if login_ids:
                db.query(UploadSession).filter(UploadSession.admin_id.in_(login_ids)).delete(synchronize_session=False)
                db.query(Admin).filter(Admin.id.in_(login_ids)).delete(synchronize_session=False)
            db.delete(studio)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "STUDIO_NOT_EMPTY", "This studio is still referenced by other records.") from exc
    if delete_data:
        info.update(_purge_studio_storage(storage, studio_id, studio_prefix, objects))
    if logo_key:
        try:
            storage.delete(logo_key)
        except Exception:  # a leftover logo object is harmless; the studio is already gone
            logger.warning("could not delete logo object of deleted studio %s", info["id"])
    return info


def _studio_has_login(db: DbSession, studio_id: int) -> bool:
    return bool(db.query(func.count(Admin.id)).filter(Admin.studio_id == studio_id).scalar())


def create_studio_admin(db: DbSession, studio: Studio, payload: StudioAdminCreateRequest) -> tuple[Admin, str | None]:
    """
    ONE LOGIN PER STUDIO. A new studio gets its login in create_studio(); this is only the
    recovery path for a studio that has none (for example an old studio whose login was removed).
    It refuses (409 STUDIO_USER_LIMIT) as soon as the studio has any login, active or disabled.
    The unique index on admins.studio_id makes the database refuse a second one too.
    """
    if _studio_has_login(db, studio.id):
        raise ApiError(
            409,
            "STUDIO_USER_LIMIT",
            "This studio already has its login account. A studio has exactly one login - edit it, change its email "
            "or reset its password instead.",
        )
    temp_password = None
    password = payload.password
    if not password:
        password = temp_password = generate_temp_password()
    if db.query(Admin.id).filter(Admin.email == str(payload.email).lower()).first():
        raise ApiError(409, "ADMIN_EMAIL_EXISTS", "An admin with this email already exists.")
    admin = _new_admin(payload.name, payload.email, studio.id, password)
    try:
        db.add(admin)
        db.commit()
    except IntegrityError:
        db.rollback()
        # Either the email is taken or another request just gave this studio its login.
        if _studio_has_login(db, studio.id):
            raise ApiError(409, "STUDIO_USER_LIMIT", "This studio already has its login account.")
        raise ApiError(409, "ADMIN_EMAIL_EXISTS", "An admin with this email already exists.")
    db.refresh(admin)
    return admin, temp_password


def list_studio_admins(db: DbSession, studio_id: int) -> list[dict]:
    rows = db.query(Admin).filter(Admin.studio_id == studio_id).order_by(Admin.id.asc()).all()
    return [
        {"id": a.id, "name": a.name, "email": a.email, "status": a.status, "created_at": a.created_at}
        for a in rows
    ]


def reset_studio_admin_password(
    db: DbSession, studio: Studio, admin_id: int, new_password: str | None
) -> tuple[Admin, str | None]:
    """
    Super-admin credential reset. The target admin must belong to THIS studio
    (the studio id comes from the URL the super admin chose, and the admin id
    is verified against it - never trusted on its own). Bumps session_version
    so every cookie the admin already holds stops working immediately.
    """
    admin = (
        db.query(Admin)
        .filter(Admin.id == admin_id, Admin.studio_id == studio.id, Admin.role == "studio_admin")
        .first()
    )
    if admin is None:
        raise not_found("Studio admin not found.", code="ADMIN_NOT_FOUND")
    temp_password = None
    password = new_password
    if not password:
        password = temp_password = generate_temp_password()
    admin.password_hash = hash_password(password)
    admin.session_version = int(admin.session_version or 0) + 1
    db.commit()
    db.refresh(admin)
    return admin, temp_password


def _get_studio_admin(db: DbSession, studio: Studio, admin_id: int) -> Admin:
    """The admin must belong to THIS studio - the id from the URL is never trusted on its own."""
    admin = (
        db.query(Admin)
        .filter(Admin.id == admin_id, Admin.studio_id == studio.id, Admin.role == "studio_admin")
        .first()
    )
    if admin is None:
        raise not_found("Studio admin not found.", code="ADMIN_NOT_FOUND")
    return admin


def update_studio_admin(
    db: DbSession, studio: Studio, admin_id: int, name: str | None, email: str | None
) -> tuple[Admin, dict]:
    """Edits name / login email. Returns (admin, changed-field names -> bool) for the audit row."""
    admin = _get_studio_admin(db, studio, admin_id)
    changed: dict[str, bool] = {}
    if name is not None and name != admin.name:
        admin.name = name
        changed["name"] = True
    if email is not None:
        new_email = str(email).lower()
        if new_email != admin.email:
            if db.query(Admin.id).filter(Admin.email == new_email, Admin.id != admin.id).first():
                raise ApiError(409, "ADMIN_EMAIL_EXISTS", "An admin with this email already exists.")
            admin.email = new_email
            # The login identity changed: end any session signed in under the old one.
            admin.session_version = int(admin.session_version or 0) + 1
            changed["email"] = True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "ADMIN_EMAIL_EXISTS", "An admin with this email already exists.")
    db.refresh(admin)
    return admin, changed


def set_studio_admin_status(db: DbSession, studio: Studio, admin_id: int, status: str) -> Admin:
    """Disable (can no longer sign in; current sessions end now) or re-enable a studio admin."""
    if status not in ("active", "disabled"):
        raise bad_request("Invalid status.", code="INVALID_STATUS")
    admin = _get_studio_admin(db, studio, admin_id)
    admin.status = status
    if status == "disabled":
        admin.session_version = int(admin.session_version or 0) + 1
    db.commit()
    db.refresh(admin)
    return admin


# ---------------------------------------------------------------- audit logs
AUDIT_CATEGORIES = ("sign_in", "studios", "logins", "storage", "content", "problems")
AUDIT_ACTORS = ("super_admin", "studio_admin", "client")
AUDIT_EXPORT_MAX_ROWS = 10_000


def _audit_category_filter(category: str):
    """Groups of audit actions for the Audit log chips (matched on the action text)."""
    if category == "sign_in":
        return AuditLog.action.in_(("admin_login", "admin_login_failed", "client_login"))
    if category == "studios":
        return AuditLog.action.in_(
            (
                "studio_created",
                "studio_updated",
                "studio_logo_updated",
                "studio_logo_removed",
                "studio_suspended",
                "studio_reactivated",
                "studio_deleted",
                "studio_profile_updated",
                "security_policy_updated",
            )
        )
    if category == "logins":
        return AuditLog.action.startswith("studio_admin_") | AuditLog.action.in_(
            ("admin_password_changed", "super_admin_password_changed")
        )
    if category == "storage":
        return AuditLog.action.in_(("studio_quota_changed", "storage_counters_repaired"))
    if category == "content":
        return (
            AuditLog.action.startswith("media_")
            | AuditLog.action.startswith("album_")
            | AuditLog.action.startswith("comment_")
            | AuditLog.action.startswith("wishlist_")
            | (AuditLog.action.startswith("client_") & (AuditLog.action != "client_login"))
        )
    if category == "problems":
        return AuditLog.action.endswith("_failed")
    raise bad_request(f"category must be one of: {', '.join(AUDIT_CATEGORIES)}.", code="INVALID_CATEGORY")


def _audit_query(
    db: DbSession,
    *,
    studio_id: int | None = None,
    action: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    category: str | None = None,
    actor: str | None = None,
    search: str | None = None,
    tz_offset_minutes: int = 0,
):
    """
    studio_id is applied as a hard filter - callers acting for a studio admin MUST pass their own.
    `date_from`/`date_to` are calendar days in the viewer's time zone (`tz_offset_minutes` = minutes
    east of UTC, e.g. 330 for India); timestamps are stored in UTC.
    """
    shift = datetime.timedelta(minutes=max(-840, min(840, int(tz_offset_minutes or 0))))
    # Failed media uploads are noisy and not shown in the audit log.
    query = db.query(AuditLog).filter(AuditLog.action != "media_upload_failed")
    if studio_id is not None:
        query = query.filter(AuditLog.studio_id == studio_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if date_from:
        query = query.filter(AuditLog.created_at >= datetime.datetime.combine(date_from, datetime.time.min) - shift)
    if date_to:
        query = query.filter(AuditLog.created_at <= datetime.datetime.combine(date_to, datetime.time.max) - shift)
    if category:
        query = query.filter(_audit_category_filter(category))
    if actor:
        if actor not in AUDIT_ACTORS:
            raise bad_request(f"actor must be one of: {', '.join(AUDIT_ACTORS)}.", code="INVALID_ACTOR")
        query = query.filter(AuditLog.user_type == "client") if actor == "client" else query.filter(AuditLog.actor_role == actor)
    if search and search.strip():
        text = search.strip()
        matches = (
            AuditLog.action.icontains(text, autoescape=True)
            | AuditLog.resource_type.icontains(text, autoescape=True)
            | AuditLog.ip_address.icontains(text, autoescape=True)
            | AuditLog.studio_id.in_(db.query(Studio.id).filter(Studio.name.icontains(text, autoescape=True)))
        )
        if text.isdigit():
            matches = matches | (AuditLog.resource_id == int(text)) | (AuditLog.user_id == int(text))
        query = query.filter(matches)
    return query


def _audit_item(r: AuditLog) -> dict:
    return {
        "id": r.id,
        "created_at": r.created_at,
        "action": r.action,
        "user_type": r.user_type,
        "user_id": r.user_id,
        "actor_role": r.actor_role,
        "studio_id": r.studio_id,
        "resource_type": r.resource_type,
        "resource_id": r.resource_id,
        "ip_address": r.ip_address,
        "metadata": r.event_metadata,
    }


def list_audit_logs(
    db: DbSession,
    page: int,
    limit: int,
    *,
    studio_id: int | None = None,
    action: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    category: str | None = None,
    actor: str | None = None,
    search: str | None = None,
    oldest_first: bool = False,
    tz_offset_minutes: int = 0,
):
    """studio_id is applied as a hard filter - callers acting for a studio admin MUST pass their own."""
    page, limit = paginate_params(page, limit)
    query = _audit_query(
        db,
        studio_id=studio_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        category=category,
        actor=actor,
        search=search,
        tz_offset_minutes=tz_offset_minutes,
    )
    total = query.count()
    order = AuditLog.id.asc() if oldest_first else AuditLog.id.desc()
    rows = query.order_by(order).offset((page - 1) * limit).limit(limit).all()
    return [_audit_item(r) for r in rows], total, page, limit


def audit_summary(db: DbSession) -> dict:
    """Platform-wide pulse for the Audit log header (ignores the page filters on purpose)."""
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    shown = AuditLog.action != "media_upload_failed"
    last_day = db.query(func.count(AuditLog.id)).filter(AuditLog.created_at >= since, shown).scalar() or 0
    failed = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.created_at >= since, AuditLog.action == "admin_login_failed")
        .scalar()
        or 0
    )
    return {"events_24h": int(last_day), "failed_sign_ins_24h": int(failed), "total": int(db.query(func.count(AuditLog.id)).filter(shown).scalar() or 0)}


def export_audit_logs(db: DbSession, **filters) -> tuple[list[dict], int]:
    """Up to AUDIT_EXPORT_MAX_ROWS newest rows matching the filters, with studio names. Returns (rows, total_matching)."""
    query = _audit_query(db, **filters)
    total = query.count()
    rows = query.order_by(AuditLog.id.desc()).limit(AUDIT_EXPORT_MAX_ROWS).all()
    names = {sid: name for sid, name in db.query(Studio.id, Studio.name).filter(Studio.id.in_({r.studio_id for r in rows if r.studio_id})).all()} if rows else {}
    items = []
    for r in rows:
        item = _audit_item(r)
        item["studio_name"] = names.get(r.studio_id)
        items.append(item)
    return items, total
