"""
Storage/transfer analytics for the admin Storage page.

Distinct from download_analytics_service.py (which focuses on download
history/records for the Downloads page) - this module answers "how is
storage being used and moved over time", covering:

1. Daily upload/download volume - for the chart on the Storage page.
2. Storage breakdown by client - who's using the most space.
3. Storage breakdown by file type - photos vs videos, by bytes not just count.
4. Upload reliability - completed vs failed vs cancelled, so a spike in
   failures (e.g. a flaky client connection, or the disk/concurrency
   guards kicking in) is visible without digging through logs.

All queries use func.date(...) rather than a dialect-specific date-trunc
function, since DATE(...) is supported identically by both SQLite (used in
the test suite) and MySQL (the production database per requirements.txt's
pymysql dependency).
"""

import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.models.album import Album
from app.models.client import Client
from app.models.download_record import DownloadRecord
from app.models.media import Media
from app.models.upload_session import UploadSession


def get_daily_transfer_series(db: DbSession, days: int = 30) -> list[dict]:
    """
    One row per calendar day for the last `days` days (oldest first),
    always including days with zero activity - a chart with gaps silently
    skipped looks like missing data, not "nothing happened that day".
    """
    # Use the START of the oldest day (midnight), not "now minus N days" -
    # otherwise a record created earlier today gets excluded from a
    # days=1 query just because "now" (at request time) is later in the
    # day than when it was created.
    now = datetime.datetime.utcnow()
    since_date = (now - datetime.timedelta(days=days - 1)).date()
    since = datetime.datetime.combine(since_date, datetime.time.min)

    upload_rows = (
        db.query(
            func.date(UploadSession.created_at).label("day"),
            func.coalesce(func.sum(UploadSession.total_bytes), 0).label("bytes"),
            func.count(UploadSession.id).label("count"),
        )
        .filter(UploadSession.status == "completed", UploadSession.created_at >= since)
        .group_by(func.date(UploadSession.created_at))
        .all()
    )
    download_rows = (
        db.query(
            func.date(DownloadRecord.downloaded_at).label("day"),
            func.coalesce(func.sum(DownloadRecord.total_bytes), 0).label("bytes"),
            func.count(DownloadRecord.id).label("count"),
        )
        .filter(DownloadRecord.downloaded_at >= since)
        .group_by(func.date(DownloadRecord.downloaded_at))
        .all()
    )

    # Rows come back with `day` as either a date or a "YYYY-MM-DD" string
    # depending on dialect/driver - normalize to a plain string key so the
    # zero-filled scaffold below always matches.
    def _day_key(value) -> str:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    uploads_by_day = {_day_key(r.day): (r.bytes, r.count) for r in upload_rows}
    downloads_by_day = {_day_key(r.day): (r.bytes, r.count) for r in download_rows}

    series = []
    for offset in range(days):
        day = since_date + datetime.timedelta(days=offset)
        key = day.isoformat()
        upload_bytes, upload_count = uploads_by_day.get(key, (0, 0))
        download_bytes, download_count = downloads_by_day.get(key, (0, 0))
        series.append(
            {
                "date": key,
                "upload_bytes": upload_bytes,
                "upload_count": upload_count,
                "download_bytes": download_bytes,
                "download_count": download_count,
            }
        )
    return series


def get_storage_by_client(db: DbSession) -> list[dict]:
    rows = (
        db.query(
            Client.id.label("client_id"),
            Client.client_name,
            func.coalesce(func.sum(Media.file_size), 0).label("total_bytes"),
            func.count(Media.id).label("file_count"),
        )
        .join(Media, Media.client_id == Client.id)
        .group_by(Client.id, Client.client_name)
        .order_by(func.coalesce(func.sum(Media.file_size), 0).desc())
        .all()
    )
    return [
        {
            "client_id": r.client_id,
            "client_name": r.client_name,
            "total_bytes": r.total_bytes,
            "file_count": r.file_count,
        }
        for r in rows
    ]


def get_storage_by_file_type(db: DbSession) -> list[dict]:
    rows = (
        db.query(
            Media.file_type,
            func.coalesce(func.sum(Media.file_size), 0).label("total_bytes"),
            func.count(Media.id).label("file_count"),
        )
        .group_by(Media.file_type)
        .all()
    )
    return [{"file_type": r.file_type, "total_bytes": r.total_bytes, "file_count": r.file_count} for r in rows]


def get_upload_reliability(db: DbSession, days: int = 30) -> dict:
    """
    All-time status breakdown (so a persistent problem is visible even if
    it happened outside the recent window) plus a recent-window success
    rate (so a NEW problem stands out even if all-time history is mostly
    clean).
    """
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    all_time_rows = db.query(UploadSession.status, func.count(UploadSession.id)).group_by(UploadSession.status).all()
    by_status = {status: count for status, count in all_time_rows}

    recent_total = db.query(func.count(UploadSession.id)).filter(UploadSession.created_at >= since).scalar() or 0
    recent_completed = (
        db.query(func.count(UploadSession.id))
        .filter(UploadSession.created_at >= since, UploadSession.status == "completed")
        .scalar()
        or 0
    )
    success_rate_percent = round((recent_completed / recent_total) * 100, 1) if recent_total else None

    return {
        "by_status": by_status,
        "recent_window_days": days,
        "recent_total": recent_total,
        "recent_completed": recent_completed,
        "recent_success_rate_percent": success_rate_percent,
    }


def get_largest_files(db: DbSession, limit: int = 10) -> list[dict]:
    """
    Top N files by size, with enough context (client/album) to act on -
    e.g. deciding whether a multi-GB video is worth archiving or deleting.
    Never exposes google_drive_file_id, consistent with every other
    admin-facing media response in this app.
    """
    rows = (
        db.query(
            Media.id.label("media_id"),
            Media.file_name,
            Media.file_type,
            Media.file_size,
            Media.created_at,
            Album.album_name,
            Client.client_name,
        )
        .join(Album, Album.id == Media.album_id)
        .join(Client, Client.id == Media.client_id)
        .order_by(Media.file_size.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "media_id": r.media_id,
            "file_name": r.file_name,
            "file_type": r.file_type,
            "file_size": r.file_size,
            "uploaded_at": r.created_at.isoformat(),
            "album_name": r.album_name,
            "client_name": r.client_name,
        }
        for r in rows
    ]
