import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin
from app.services.folder_naming import generate_folder_uid


class Album(Base, IdMixin, TimestampMixin):
    __tablename__ = "albums"

    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    album_uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    album_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "disabled", name="album_status"), default="active", nullable=False
    )

    # Optional expiry for client-facing access. NULL means "never expires".
    # Enforced server-side in album_service/media_service - the frontend
    # showing/hiding an album based on this is a UX nicety, not the
    # security boundary.
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Google Drive subfolder id for this album
    drive_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Opaque, random suffix embedded in the Drive folder's display name
    # ("{album_name}_A_{folder_uid}"). Generated once and never changed -
    # renaming the album only ever updates the readable part of the Drive
    # folder name. Deliberately distinct from album_uuid and the numeric id.
    folder_uid: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, default=generate_folder_uid
    )

    client: Mapped["Client"] = relationship(back_populates="albums")
    media_items: Mapped[list["Media"]] = relationship(
        back_populates="album", cascade="all, delete-orphan"
    )
