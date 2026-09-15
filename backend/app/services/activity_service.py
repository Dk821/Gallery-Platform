"""
Admin activity feed.

Pulls together the four activity families the Admin "Activity" page shows
into one unified, filterable stream:

  - uploads   (audit_logs.action == "media_uploaded", admin-initiated)
  - downloads (DownloadRecord rows - actual ZIP serves, not job prep)
  - clients   (audit_logs.action == "client_created")
  - albums    (audit_logs.action == "album_created")

Everything is gathered, filtered, sorted and trimmed in Python. That keeps
the query code trivial (the audit log / download tables are append-only and
small by design) and lets one endpoint answer search + type + date filters
without pushing that logic into SQL.
"""

import datetime

from sqlalchemy.orm import Session as DbSession

from app.models.album import Album
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.download_record import DownloadRecord
from app.models.media import Media


def _media_upload_items(db: DbSession) -> list[dict]:
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.action == "media_uploaded", AuditLog.user_type == "admin")
        .order_by(AuditLog.created_at.desc())
        .all()
    )
    if not logs:
        return []

    media_ids = [log.resource_id for log in logs if log.resource_id is not None]
    media_by_id = {
        m.id: m
        for m in db.query(Media).filter(Media.id.in_(media_ids)).all()
    } if media_ids else {}

    album_ids = {m.album_id for m in media_by_id.values()}
    album_by_id = {
        a.id: a
        for a in db.query(Album).filter(Album.id.in_(album_ids)).all()
    } if album_ids else {}

    client_ids = {a.client_id for a in album_by_id.values()}
    client_by_id = {
        c.id: c
        for c in db.query(Client).filter(Client.id.in_(client_ids)).all()
    } if client_ids else {}

    items = []
    for i, log in enumerate(logs):
        media = media_by_id.get(log.resource_id) if log.resource_id is not None else None
        album = album_by_id.get(media.album_id) if media else None
        client = client_by_id.get(album.client_id) if album else None
        items.append(
            {
                "id": f"upload-{log.id}",
                "type": "upload",
                "title": "Uploaded file",
                "description": media.file_name if media else "A media file was uploaded",
                "actor": "Studio Admin",
                "occurred_at": log.created_at.isoformat(),
                "meta": {
                    "album_name": album.album_name if album else None,
                    "client_name": client.client_name if client else None,
                    "file_count": 1,
                    "total_bytes": media.file_size if media else None,
                },
            }
        )
    return items


def _client_created_items(db: DbSession) -> list[dict]:
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.action == "client_created", AuditLog.user_type == "admin")
        .order_by(AuditLog.created_at.desc())
        .all()
    )
    if not logs:
        return []

    client_ids = [log.resource_id for log in logs if log.resource_id is not None]
    client_by_id = {
        c.id: c
        for c in db.query(Client).filter(Client.id.in_(client_ids)).all()
    } if client_ids else {}

    items = []
    for log in logs:
        client = client_by_id.get(log.resource_id) if log.resource_id is not None else None
        items.append(
            {
                "id": f"client-{log.id}",
                "type": "client",
                "title": "Created client",
                "description": client.client_name if client else "A client was created",
                "actor": "Studio Admin",
                "occurred_at": log.created_at.isoformat(),
                "meta": {"client_name": client.client_name if client else None},
            }
        )
    return items


def _album_created_items(db: DbSession) -> list[dict]:
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.action == "album_created", AuditLog.user_type == "admin")
        .order_by(AuditLog.created_at.desc())
        .all()
    )
    if not logs:
        return []

    album_ids = [log.resource_id for log in logs if log.resource_id is not None]
    album_by_id = {
        a.id: a
        for a in db.query(Album).filter(Album.id.in_(album_ids)).all()
    } if album_ids else {}

    client_ids = {a.client_id for a in album_by_id.values()}
    client_by_id = {
        c.id: c
        for c in db.query(Client).filter(Client.id.in_(client_ids)).all()
    } if client_ids else {}

    items = []
    for log in logs:
        album = album_by_id.get(log.resource_id) if log.resource_id is not None else None
        client = client_by_id.get(album.client_id) if album else None
        items.append(
            {
                "id": f"album-{log.id}",
                "type": "album",
                "title": "Added album",
                "description": album.album_name if album else "An album was added",
                "actor": "Studio Admin",
                "occurred_at": log.created_at.isoformat(),
                "meta": {
                    "album_name": album.album_name if album else None,
                    "client_name": client.client_name if client else None,
                },
            }
        )
    return items


def _download_items(db: DbSession) -> list[dict]:
    rows = (
        db.query(
            DownloadRecord.id,
            DownloadRecord.downloaded_at,
            DownloadRecord.file_count,
            DownloadRecord.total_bytes,
            DownloadRecord.download_type,
            Album.album_name,
            Client.client_name,
        )
        .join(Album, Album.id == DownloadRecord.album_id)
        .join(Client, Client.id == DownloadRecord.client_id)
        .order_by(DownloadRecord.downloaded_at.desc())
        .all()
    )
    return [
        {
            "id": f"download-{r.id}",
            "type": "download",
            "title": "Downloaded album",
            "description": r.album_name,
            "actor": r.client_name,
            "occurred_at": r.downloaded_at.isoformat(),
            "meta": {
                "album_name": r.album_name,
                "client_name": r.client_name,
                "file_count": r.file_count,
                "total_bytes": r.total_bytes,
                "download_type": r.download_type,
            },
        }
        for r in rows
    ]


def _matches_search(item: dict, query: str) -> bool:
    if not query:
        return True
    meta = item.get("meta") or {}
    haystack = " ".join(
        [
            item.get("title") or "",
            item.get("description") or "",
            item.get("actor") or "",
            meta.get("album_name") or "",
            meta.get("client_name") or "",
        ]
    ).lower()
    return query in haystack


def _in_date_range(item: dict, date_from: datetime.date | None, date_to: datetime.date | None) -> bool:
    if date_from is None and date_to is None:
        return True
    occurred = datetime.datetime.fromisoformat(item["occurred_at"])
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=datetime.timezone.utc)
    if date_from is not None:
        start = datetime.datetime.combine(date_from, datetime.time.min, tzinfo=datetime.timezone.utc)
        if occurred < start:
            return False
    if date_to is not None:
        end = datetime.datetime.combine(date_to, datetime.time.max, tzinfo=datetime.timezone.utc)
        if occurred > end:
            return False
    return True


def get_activity_feed(
    db: DbSession,
    search: str | None = None,
    activity_type: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = 200,
) -> dict:
    raw = (
        _media_upload_items(db)
        + _client_created_items(db)
        + _album_created_items(db)
        + _download_items(db)
    )

    query = (search or "").lower().strip()

    filtered = [
        item
        for item in raw
        if (activity_type is None or item["type"] == activity_type)
        and _in_date_range(item, date_from, date_to)
        and _matches_search(item, query)
    ]

    filtered.sort(key=lambda i: i["occurred_at"], reverse=True)

    return {
        "items": filtered[:limit],
        "total": len(filtered),
        "limit": limit,
    }