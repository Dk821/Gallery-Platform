from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin


class StudioSettings(Base, IdMixin, TimestampMixin):
    """
    Studio-wide configuration, as a SINGLE-ROW table (id is always 1).

    There's exactly one studio using this install, so a settings table with
    one row - read/created lazily by get_studio_settings() rather than
    seeded by the migration - is simpler than a key/value table and avoids
    ever needing a migration data-seed that could drift from the model's
    defaults. See app/services/studio_settings_service.py.
    """

    __tablename__ = "studio_settings"

    studio_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Security & download policy ----------------------------------
    # Minimum length required for a NEW client gallery/download password.
    # Existing passwords shorter than this are left alone - it only
    # applies going forward, the same way changing a site-wide password
    # policy never retroactively invalidates existing passwords elsewhere.
    min_client_password_length: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    # How long a completed ZIP download stays downloadable before it
    # expires. Mirrors settings.zip_job_ttl_hours (app/config/settings.py),
    # which remains the fallback/default until an admin sets this.
    download_link_ttl_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
