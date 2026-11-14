from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.models.album import Album
from app.models.client import Client
from app.models.media import Media
from app.models.studio import Studio
from app.services import quota_service
from app.services.download_analytics_service import get_download_summary
from app.workers.thumbnail_worker import is_ffmpeg_available


def get_dashboard_summary(db: DbSession, studio_id: int) -> dict:
    total_clients = db.query(func.count(Client.id)).filter(Client.studio_id == studio_id).scalar() or 0
    active_clients = (
        db.query(func.count(Client.id))
        .filter(Client.studio_id == studio_id, Client.status == "active")
        .scalar()
        or 0
    )
    total_albums = db.query(func.count(Album.id)).filter(Album.studio_id == studio_id).scalar() or 0
    total_photos = (
        db.query(func.count(Media.id))
        .filter(Media.studio_id == studio_id, Media.file_type == "photo")
        .scalar()
        or 0
    )
    total_videos = (
        db.query(func.count(Media.id))
        .filter(Media.studio_id == studio_id, Media.file_type == "video")
        .scalar()
        or 0
    )
    storage_used_bytes = (
        db.query(func.coalesce(func.sum(Media.file_size), 0)).filter(Media.studio_id == studio_id).scalar() or 0
    )
    studio = db.get(Studio, studio_id)

    return {
        "total_clients": total_clients,
        "active_clients": active_clients,
        "total_albums": total_albums,
        "total_photos": total_photos,
        "total_videos": total_videos,
        # Bytes summed from our own metadata, not a live Google Drive quota
        # call - Phase 3 will add a separate "drive_quota" field once the
        # StorageService exists, clearly labelled per spec Section 42.
        "storage_used_bytes": storage_used_bytes,
        # Additive (multi-studio): the studio's own quota / used / reserved /
        # remaining. Existing dashboard fields above are unchanged.
        "studio_quota": quota_service.studio_usage(studio) if studio is not None else None,
        "downloads_summary": get_download_summary(db, studio_id),
        # Surfaced so an admin logged into the dashboard can see (rather
        # than needing server log access) whether video thumbnails are
        # currently being generated at all. See SYSTEM_REQUIREMENTS.md.
        "ffmpeg_available": is_ffmpeg_available(),
    }


def get_recent_clients(db: DbSession, studio_id: int, limit: int = 5) -> list[Client]:
    return (
        db.query(Client)
        .filter(Client.studio_id == studio_id)
        .order_by(Client.created_at.desc())
        .limit(limit)
        .all()
    )
