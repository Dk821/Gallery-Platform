from sqlalchemy import BigInteger, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin

STUDIO_STATUSES = ("active", "suspended")


class Studio(Base, IdMixin, TimestampMixin):
    """
    A tenant (one photography studio) of the shared platform.

    Every studio-owned row (clients, albums, media, upload sessions, download
    jobs/records) carries `studio_id`, and every studio-admin query filters on
    it. Storage accounting lives here too:

      quota_bytes     - hard ceiling for used + reserved, set by a super admin
      used_bytes      - bytes of verified, stored media (Media.file_size sum)
      reserved_bytes  - bytes promised to in-flight uploads, not yet verified

    `used_bytes` and `reserved_bytes` are only ever changed through
    app.services.quota_service (conditional UPDATEs), never by assigning to
    the ORM attributes, so concurrent uploads cannot oversubscribe a studio.
    """

    __tablename__ = "studios"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Branding shown in the studio's own admin UI and (later) client galleries.
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    brand_color: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # The studio's folder in object storage, e.g. "studios/acme-photo-1". Chosen
    # once when the studio is created and never changed (renaming the studio must
    # not move files). NULL for studios that predate it: they use "studios/{id}".
    storage_prefix: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The studio's name as it appears in client gallery links: /<slug>/gallery/<link id>. Made from the
    # studio name when the studio is created and then kept (renaming the studio must not break links
    # clients already hold). NULL only for rows that predate it; their links stay /gallery/<link id>.
    slug: Mapped[str | None] = mapped_column(String(60), nullable=True, unique=True)

    status: Mapped[str] = mapped_column(
        Enum(*STUDIO_STATUSES, name="studio_status"), default="active", nullable=False, index=True
    )

    quota_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
