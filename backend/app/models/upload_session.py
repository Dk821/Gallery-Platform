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

    # Owning studio (tenant). Indexed, filtered on by every studio-admin query.
    studio_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("studios.id", ondelete="RESTRICT"), nullable=True, index=True
    )

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
    drive_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_drive_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # The provider-issued resumable upload session URL handed to the
    # browser so it can PUT bytes DIRECTLY to Google Drive (this server
    # never receives them). Short-lived and single-use per Drive's own
    # resumable-upload protocol - kept here only so a page refresh mid
    # upload can detect "this session's URL is gone, needs re-upload"
    # rather than for any other durability guarantee. Never exposed to any
    # OTHER admin/session, and cleared once the session reaches a terminal
    # state. Drive session URLs carry long opaque tokens, hence Text
    # rather than a short varchar.
    drive_resumable_upload_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    media_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("media.id", ondelete="SET NULL"), nullable=True
    )

    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Storage-quota reservation ledger -----------------------------------
    # Bytes held against the studio quota (and platform capacity) for this
    # upload while it is in flight. none -> reserved -> committed (converted to
    # used after a verified upload) or released (failed / cancelled / stale).
    # Every transition is a compare-and-set UPDATE so a duplicate completion or
    # abandon can never apply it twice.
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    reservation_status: Mapped[str] = mapped_column(
        Enum("none", "reserved", "committed", "released", name="upload_reservation_status"),
        default="none",
        server_default="none",
        nullable=False,
        index=True,
    )
