from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin


class Admin(Base, IdMixin, TimestampMixin):
    __tablename__ = "admins"
    __table_args__ = (Index("uq_admins_studio_id", "studio_id", unique=True),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("active", "disabled", name="admin_status"), default="active", nullable=False
    )

    # RBAC. `super_admin` is the platform operator (no studio); `studio_admin`
    # belongs to exactly one studio. Read from the DB on every request - never
    # from the cookie or anything the frontend sends.
    role: Mapped[str] = mapped_column(
        Enum("super_admin", "studio_admin", name="admin_role"),
        default="studio_admin",
        server_default="studio_admin",
        nullable=False,
        index=True,
    )
    # NULL for super admins. NULL for a studio_admin means "legacy admin not
    # yet mapped to a studio" - such an admin is refused on every studio route
    # until `python -m app.legacy_to_studio` assigns one.
    # ONE LOGIN PER STUDIO: the unique index below lets the database itself refuse a
    # second admin for the same studio (several NULLs - super admins, unmapped
    # legacy admins - are allowed).
    studio_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("studios.id", ondelete="RESTRICT"), nullable=True
    )
    # Platform profile of a SUPER ADMIN (shown in the console sidebar; unused for studio admins).
    # `logo_url` is the same-origin path /api/platform/{admin id}/logo?v=<hash> of an uploaded picture.
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Bumped on credential reset / password change; embedded in the signed
    # session cookie so older cookies stop working immediately.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
