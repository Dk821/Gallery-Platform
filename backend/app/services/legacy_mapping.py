"""
Explicit, reviewable mapping of pre-multi-studio ("legacy") rows to a studio.

The migration deliberately leaves studio_id NULL on every existing row,
because the platform cannot know which real-world business they belong to.
This module is the ONLY thing that fills them in, and only when an operator
names the target studio. Everything runs in one transaction: either every
selected row is assigned and the usage counters recomputed, or nothing changes.

Selection
  default                map EVERY unmapped row to the one studio (the normal
                         case: a single-studio install becoming the first tenant)
  client_ids=[...]       map only those clients and everything that hangs off
                         them (albums, media, upload sessions, download jobs and
                         records) - for installs that really hosted several
                         businesses and must be split across studios
  admin_ids=[...]        map only those admins (default: all unmapped studio admins)

Safety rails
  * dry run unless apply=True
  * only rows with studio_id IS NULL are touched - nothing already assigned is moved
  * refuses if the studio is missing, or if the bytes being mapped would not fit
    its quota (raise the quota first; nothing is silently clipped)
  * a client whose albums/media straddle two studios is impossible by
    construction (children follow the client), so there is no partial mapping
"""

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session as DbSession

from app.models.admin import Admin
from app.models.album import Album
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.download_job import DownloadJob
from app.models.download_record import DownloadRecord
from app.models.media import Media
from app.models.studio import Studio
from app.models.studio_settings import StudioSettings
from app.models.upload_session import UploadSession
from app.services import quota_service


class LegacyMappingError(Exception):
    pass


def report_unmapped(db: DbSession) -> dict:
    def count(model, *extra):
        return db.execute(select(func.count()).select_from(model).where(model.studio_id.is_(None), *extra)).scalar_one()

    bytes_unmapped = db.execute(
        select(func.coalesce(func.sum(Media.file_size), 0)).where(Media.studio_id.is_(None))
    ).scalar_one()
    admins = db.execute(
        select(Admin.id, Admin.email, Admin.name).where(Admin.role == "studio_admin", Admin.studio_id.is_(None))
    ).all()
    return {
        "unmapped_rows": {
            "admins": len(admins),
            "clients": count(Client),
            "albums": count(Album),
            "media": count(Media),
            "upload_sessions": count(UploadSession),
            "download_jobs": count(DownloadJob),
            "download_records": count(DownloadRecord),
            "audit_logs": count(AuditLog),
        },
        "unmapped_media_bytes": int(bytes_unmapped),
        "unmapped_admins": [{"id": a.id, "email": a.email, "name": a.name} for a in admins],
        "studios": [
            {"id": s.id, "name": s.name, "status": s.status, "quota_bytes": int(s.quota_bytes)}
            for s in db.execute(select(Studio).order_by(Studio.id)).scalars()
        ],
    }


def map_legacy_to_studio(
    db: DbSession,
    studio_id: int,
    *,
    client_ids: list[int] | None = None,
    admin_ids: list[int] | None = None,
    apply: bool = False,
) -> dict:
    studio = db.get(Studio, studio_id)
    if studio is None:
        raise LegacyMappingError(f"Studio {studio_id} does not exist.")

    # ---- what would be mapped ------------------------------------------
    if client_ids is None:
        client_filter = [Client.studio_id.is_(None)]
    else:
        client_filter = [Client.studio_id.is_(None), Client.id.in_(client_ids)]
    mapped_client_ids = [r for (r,) in db.execute(select(Client.id).where(*client_filter))]

    admin_filter = [Admin.role == "studio_admin", Admin.studio_id.is_(None)]
    if admin_ids is not None:
        admin_filter.append(Admin.id.in_(admin_ids))
    mapped_admin_ids = [r for (r,) in db.execute(select(Admin.id).where(*admin_filter))]

    if client_ids is None:
        # Whole-install mapping: every unmapped row, including ones whose
        # client row is already gone (cascade leftovers).
        media_bytes = db.execute(
            select(func.coalesce(func.sum(Media.file_size), 0)).where(Media.studio_id.is_(None))
        ).scalar_one()
    else:
        media_bytes = db.execute(
            select(func.coalesce(func.sum(Media.file_size), 0)).where(
                Media.studio_id.is_(None), Media.client_id.in_(mapped_client_ids or [-1])
            )
        ).scalar_one()
    media_bytes = int(media_bytes)

    # ONE LOGIN PER STUDIO: never map more admins into a studio than it can hold.
    existing_logins = db.execute(select(func.count(Admin.id)).where(Admin.studio_id == studio.id)).scalar_one()
    if existing_logins + len(mapped_admin_ids) > 1:
        raise LegacyMappingError(
            f"Studio {studio.id} can have only one login account: it already has {existing_logins} and "
            f"{len(mapped_admin_ids)} unmapped admin(s) were selected. Choose exactly one with --admin-ids; nothing was changed."
        )

    projected_used = int(studio.used_bytes) + media_bytes
    plan = {
        "studio_id": studio.id,
        "studio_name": studio.name,
        "clients": len(mapped_client_ids),
        "admins": len(mapped_admin_ids),
        "media_bytes_to_map": media_bytes,
        "projected_used_bytes": projected_used,
        "quota_bytes": int(studio.quota_bytes),
        "fits_quota": projected_used + int(studio.reserved_bytes) <= int(studio.quota_bytes),
        "applied": False,
    }
    if not plan["fits_quota"]:
        raise LegacyMappingError(
            f"The legacy media ({media_bytes} bytes) would not fit studio {studio.id}'s quota "
            f"({int(studio.quota_bytes)} bytes, {int(studio.used_bytes)} already used). "
            "Raise the studio quota first; nothing was changed."
        )
    if not apply:
        return plan

    # ---- apply (single transaction) -------------------------------------
    cid = mapped_client_ids or [-1]
    if mapped_client_ids:
        db.execute(update(Client).where(Client.id.in_(cid), Client.studio_id.is_(None)).values(studio_id=studio.id))
        db.execute(update(Album).where(Album.client_id.in_(cid), Album.studio_id.is_(None)).values(studio_id=studio.id))
        db.execute(update(Media).where(Media.client_id.in_(cid), Media.studio_id.is_(None)).values(studio_id=studio.id))
        db.execute(
            update(DownloadJob).where(DownloadJob.client_id.in_(cid), DownloadJob.studio_id.is_(None)).values(studio_id=studio.id)
        )
        db.execute(
            update(DownloadRecord)
            .where(DownloadRecord.client_id.in_(cid), DownloadRecord.studio_id.is_(None))
            .values(studio_id=studio.id)
        )
        # Upload sessions follow their album.
        db.execute(
            update(UploadSession)
            .where(
                UploadSession.studio_id.is_(None),
                UploadSession.album_id.in_(select(Album.id).where(Album.studio_id == studio.id)),
            )
            .values(studio_id=studio.id)
        )
    if mapped_admin_ids:
        db.execute(update(Admin).where(Admin.id.in_(mapped_admin_ids)).values(studio_id=studio.id))
        db.execute(
            update(AuditLog)
            .where(AuditLog.studio_id.is_(None), AuditLog.user_type == "admin", AuditLog.user_id.in_(mapped_admin_ids))
            .values(studio_id=studio.id)
        )
    if mapped_client_ids:
        db.execute(
            update(AuditLog)
            .where(AuditLog.studio_id.is_(None), AuditLog.user_type == "client", AuditLog.user_id.in_(cid))
            .values(studio_id=studio.id)
        )

    # The legacy single settings row (id=1, no studio) becomes this studio's
    # own settings (copied, so unmapped legacy data still has its row).
    legacy = db.execute(select(StudioSettings).where(StudioSettings.id == 1, StudioSettings.studio_id.is_(None))).scalar_one_or_none()
    has_own = db.execute(select(StudioSettings.id).where(StudioSettings.studio_id == studio.id)).first()
    if legacy is not None and has_own is None:
        db.add(
            StudioSettings(
                studio_id=studio.id,
                studio_name=legacy.studio_name,
                contact_email=legacy.contact_email,
                min_client_password_length=legacy.min_client_password_length,
                download_link_ttl_hours=legacy.download_link_ttl_hours,
            )
        )

    # Usage counters recomputed from the rows (not incremented), so running
    # this twice, or after partial mapping, can never double count.
    db.execute(
        text(
            "UPDATE studios SET used_bytes = "
            "(SELECT COALESCE(SUM(file_size), 0) FROM media WHERE media.studio_id = studios.id) WHERE id = :id"
        ),
        {"id": studio.id},
    )
    quota_service.ensure_platform_row(db)
    db.execute(
        text(
            "UPDATE platform_storage SET used_bytes = (SELECT COALESCE(SUM(used_bytes), 0) FROM studios) WHERE id = :pid"
        ),
        {"pid": quota_service.PLATFORM_ROW_ID},
    )
    db.commit()
    plan["applied"] = True
    return plan
