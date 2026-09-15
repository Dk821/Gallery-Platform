import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin


class DownloadJob(Base, IdMixin, TimestampMixin):
    """
    Tracks a background ZIP-generation job (Parts 7-9). The actual ZIP file
    lives on local disk at `zip_path` - that path is an internal
    implementation detail and is NEVER serialized into an API response
    (same principle as never exposing a Google Drive file id).
    """

    __tablename__ = "download_jobs"

    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    album_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("albums.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        Enum(
            "queued", "preparing", "processing", "completed", "failed", "expired", "cancelled",
            name="download_job_status",
        ),
        default="queued",
        nullable=False,
        index=True,
    )

    # Null media_ids_json means "every media item in the album at the time
    # the job was created" (Part 8's "All photos as ZIP"); a JSON array of
    # ints means "just these" (Part 7's "Selected photos as ZIP").
    media_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    total_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completed_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    zip_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Who asked for this - lets an admin trigger a bulk ZIP on a client's
    # behalf (Part 1's "Bulk Download as ZIP") using the exact same job
    # machinery as the client's own self-service download.
    requested_by_type: Mapped[str] = mapped_column(
        Enum("admin", "client", name="download_job_requester_type"), nullable=False
    )
    requested_by_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # Only set once the job completes (created_at + ttl from that point) -
    # a job that's still queued/processing/failed has nothing to expire yet.
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, index=True)
