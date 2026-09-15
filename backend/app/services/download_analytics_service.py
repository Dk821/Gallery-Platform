"""
Download analytics.

Two jobs live here:

1. `record_download` - the minimal tracking tap. It is wired into the ZIP
   file-serve endpoints as a Starlette BackgroundTask, so it runs only after
   the response has actually been sent to the client (not when the ZIP is
   merely prepared). It opens its OWN DB session (same reason as
   process_download_job: the request's session is torn down by the time a
   BackgroundTasks callback runs, and the test suite monkeypatches
   db_connection.SessionLocal to get a per-test engine).

2. Aggregation helpers that summarise those records for the admin
   dashboard - total downloads, total bytes transferred and per-album
   breakdowns. The DownloadJob table cannot answer these on its own because
   a job is only the *preparation* of a ZIP that can be downloaded many
   times, so we count actual serves instead.
"""

import datetime
import json
import logging

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.database import connection as db_connection
from app.models.album import Album
from app.models.client import Client
from app.models.download_job import DownloadJob
from app.models.download_record import DownloadRecord
from app.models.media import Media

logger = logging.getLogger("gallery.download_analytics")


def _download_type_for_job(db: DbSession, job: DownloadJob) -> str:
    # create_download_job always stores the resolved media ids (even for a
    # "whole album" request), so "all" vs "selected" can't be told apart
    # from the snapshot alone. Compare against the album's current total:
    # a snapshot covering every file is "all", anything smaller is
    # "selected". If the album count can't be determined (e.g. media were
    # deleted since), fall back to "selected" rather than over-claiming.
    job_ids: list[int] = []
    if job.media_ids_json:
        try:
            job_ids = json.loads(job.media_ids_json)
        except (TypeError, ValueError):
            job_ids = []
    total_in_album = db.query(func.count(Media.id)).filter(Media.album_id == job.album_id).scalar() or 0
    if job_ids and total_in_album and len(job_ids) >= total_in_album:
        return "all"
    return "selected"


def record_download(job_id: int) -> None:
    """
    Record one ZIP download that was served. Runs detached from any request
    so it can open its own DB session (mirrors process_download_job - see
    the module docstring). Failures are logged, never allowed to crash the
    response, and never surface to the client.
    """
    db = db_connection.SessionLocal()
    try:
        job = db.query(DownloadJob).filter(DownloadJob.id == job_id).first()
        if job is None:
            logger.warning("record_download called with unknown job id %s", job_id)
            return
        record = DownloadRecord(
            client_id=job.client_id,
            album_id=job.album_id,
            job_id=job.id,
            download_type=_download_type_for_job(db, job),
            file_count=job.total_files,
            total_bytes=job.total_bytes,
        )
        db.add(record)
        db.commit()
    except Exception:  # noqa: BLE001 - analytics must never break a download
        logger.exception("Failed to record download for job %s", job_id)
    finally:
        db.close()


def get_download_summary(db: DbSession) -> dict:
    total_downloads = db.query(func.count(DownloadRecord.id)).scalar() or 0
    total_bytes = db.query(func.coalesce(func.sum(DownloadRecord.total_bytes), 0)).scalar() or 0
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    recent_24h = db.query(func.count(DownloadRecord.id)).filter(
        DownloadRecord.downloaded_at >= since
    ).scalar() or 0
    return {
        "total_downloads": total_downloads,
        "total_transferred_bytes": total_bytes,
        "recent_24h": recent_24h,
    }


def get_per_album_download_stats(db: DbSession) -> list[dict]:
    rows = (
        db.query(
            Album.id.label("album_id"),
            Album.album_name,
            Client.client_name,
            func.count(DownloadRecord.id).label("download_count"),
            func.coalesce(func.sum(DownloadRecord.total_bytes), 0).label("total_bytes"),
            func.max(DownloadRecord.downloaded_at).label("last_downloaded"),
        )
        .join(DownloadRecord, DownloadRecord.album_id == Album.id)
        .join(Client, Client.id == DownloadRecord.client_id)
        .group_by(Album.id, Album.album_name, Client.client_name)
        .order_by(func.count(DownloadRecord.id).desc())
        .all()
    )
    return [
        {
            "album_id": r.album_id,
            "album_name": r.album_name,
            "client_name": r.client_name,
            "download_count": r.download_count,
            "total_bytes": r.total_bytes,
            "last_downloaded": r.last_downloaded.isoformat() if r.last_downloaded else None,
        }
        for r in rows
    ]


def get_download_history(db: DbSession, limit: int = 50) -> list[dict]:
    # Left-join DownloadJob: a downloaded ZIP is a real, countable event even
    # if its job row was later purged (job_id is nullable / SET NULL).
    rows = (
        db.query(
            DownloadRecord.downloaded_at,
            DownloadRecord.download_type,
            DownloadRecord.file_count,
            DownloadRecord.total_bytes,
            Album.album_name,
            Client.client_name,
            DownloadJob.status.label("job_status"),
        )
        .join(Album, Album.id == DownloadRecord.album_id)
        .join(Client, Client.id == DownloadRecord.client_id)
        .outerjoin(DownloadJob, DownloadJob.id == DownloadRecord.job_id)
        .order_by(DownloadRecord.downloaded_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "downloaded_at": r.downloaded_at.isoformat(),
            "download_type": r.download_type,
            "file_count": r.file_count,
            "total_bytes": r.total_bytes,
            "album_name": r.album_name,
            "client_name": r.client_name,
            "status": r.job_status or "completed",
        }
        for r in rows
    ]
