from sqlalchemy import BigInteger, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin


class Media(Base, IdMixin, TimestampMixin):
    __tablename__ = "media"

    # Denormalized client_id (in addition to album->client) so every media
    # ownership check can be a single indexed comparison, not a join.
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    album_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("albums.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    # Optional admin-facing metadata, distinct from file_name (the actual
    # stored filename). Added for the admin media-management feature -
    # nullable so every pre-existing row (and every upload that doesn't set
    # them) stays valid with no backfill required.
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str] = mapped_column(
        Enum("photo", "video", name="media_file_type"), nullable=False
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Google Drive is the storage layer today; this column is the only place
    # that ties a media row to a specific provider file. Swapping providers
    # later means adding a `storage_provider` discriminator column + a new
    # id field, not touching the rest of the schema.
    google_drive_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    thumbnail_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Content-Type of the stored thumbnail (thumbnail_reference). Existing
    # rows predating this column are JPEG; everything stored going forward is
    # WebP. The media model remembers this because the thumbnail streaming
    # route must label the bytes it serves correctly (it always did before,
    # hard-coded as image/jpeg).
    thumbnail_mime_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    status: Mapped[str] = mapped_column(
        Enum("processing", "ready", "failed", name="media_status"),
        default="processing",
        nullable=False,
    )

    album: Mapped["Album"] = relationship(back_populates="media_items")
