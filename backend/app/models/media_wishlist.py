from sqlalchemy import BigInteger, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin


class MediaWishlist(Base, IdMixin, TimestampMixin):
    """
    A client's favourite ("wishlist") marker on one media item.

    Purely a database relationship - marking a photo never creates, copies
    or moves anything in Google Drive.

    client_id is ALWAYS taken from the authenticated client session, never
    from a request body/path (see services/wishlist_service.py), and a row is
    only ever written after the media -> album -> client chain has been
    verified. client_id is deliberately redundant with media.client_id: it
    keeps every "this client's wishlist" query a single indexed lookup and
    lets the unique constraint below enforce one row per (client, media).
    """

    __tablename__ = "media_wishlists"
    __table_args__ = (
        UniqueConstraint("client_id", "media_id", name="uq_media_wishlist_client_media"),
        # The unique constraint's index leads with client_id, so it already
        # serves "this client's wishlist" lookups. This one serves the
        # media-side lookups (the admin EXISTS filter, and the cascade when a
        # media row is deleted).
        Index("ix_media_wishlists_media_id", "media_id"),
    )

    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    media_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("media.id", ondelete="CASCADE"), nullable=False
    )
