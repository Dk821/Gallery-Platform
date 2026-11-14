from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin


class PlatformStorage(Base, IdMixin, TimestampMixin):
    """
    SINGLE-ROW table (id is always 1) holding platform-wide storage totals.

    Per-studio quotas alone cannot stop the platform as a whole from being
    oversubscribed (the sum of studio quotas may exceed physical capacity on
    purpose). Every reservation therefore also does one conditional UPDATE on
    this row - `WHERE used + reserved + :n <= :platform_capacity` - and the
    row lock serialises concurrent reservations from different studios.

    The capacity itself is NOT stored here: it comes from configuration
    (PLATFORM_CAPACITY_BYTES) so it can change without a migration.
    """

    __tablename__ = "platform_storage"

    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
