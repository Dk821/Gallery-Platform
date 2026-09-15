import datetime

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin
from app.services.folder_naming import generate_folder_uid


class Client(Base, IdMixin, TimestampMixin):
    __tablename__ = "clients"

    # This is the unpredictable gallery id used in /gallery/<client_uuid>
    client_uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Admin-viewable copy of the login password, encrypted with Fernet (see
    # app/security/encryption.py). NULL for clients created before this was
    # added - never used for authentication, only for the admin "view
    # password" UI. Kept out of every client-facing response.
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional second password - when set, clients must enter it before
    # downloading any files (ZIP or single-file).
    download_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Encrypted copy of the download password, same rules as above.
    download_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "disabled", name="client_status"), default="active", nullable=False
    )
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    # Google Drive folder id for this client (root of their albums), stored so
    # it never needs to be recomputed / re-derived from name.
    drive_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Opaque, random suffix embedded in the Drive folder's display name
    # ("{client_name}_C_{folder_uid}"). Generated once and never changed -
    # renaming the client only ever updates the readable part of the Drive
    # folder name. Deliberately distinct from client_uuid (the public
    # gallery id) and the numeric id (never exposed anywhere).
    folder_uid: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, default=generate_folder_uid
    )

    albums: Mapped[list["Album"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["ClientSession"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
