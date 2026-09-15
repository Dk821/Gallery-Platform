from sqlalchemy import BigInteger, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin


class UploadSession(Base, IdMixin, TimestampMixin):
    """
    Idempotency + progress ledger for a single logical upload (Section 4 /
    Section 8 / Section 9 of the upload-hardening spec).

    A row is keyed by (admin_id, upload_id) - the client mints upload_id
    once per logical upload (e.g. a UUID generated when the user picks a
    file) and resends the SAME value on every retry of that same logical
    upload. That lets the server tell "the browser retried because it
    never saw our response" apart from "this is a new upload", without
    ever trusting the filename as an identity key.

    drive_file_id / thumbnail_drive_file_id are written (and committed)
    the moment each Drive upload actually succeeds - BEFORE the Media row
    is created - specifically so that a crash between "Drive accepted the
    file" and "we saved the DB record" leaves durable evidence an orphan
    reconciliation job can find later (Section 9), rather than only living
    in this request's local variables.
    """

    __tablename__ = "upload_sessions"
    __table_args__ = (UniqueConstraint("admin_id", "upload_id", name="uq_upload_session_admin_upload"),)

    upload_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    admin_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("admins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    album_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("albums.id", ondelete="CASCADE"), nullable=False, index=True
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bytes_uploaded: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    status: Mapped[str] = mapped_column(
        Enum("queued", "uploading", "completed", "failed", "cancelled", name="upload_session_status"),
        default="queued",
        nullable=False,
        index=True,
    )

    # Set as soon as the corresponding Drive upload succeeds - never
    # exposed to the frontend (same rule as Media.google_drive_file_id).
    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thumbnail_drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    media_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("media.id", ondelete="SET NULL"), nullable=True
    )

    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
