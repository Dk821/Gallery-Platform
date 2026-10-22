from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import IdMixin, TimestampMixin


class AlbumComment(Base, IdMixin, TimestampMixin):
    """
    A client's note about ONE page (spread) of an album's Book View.

    Purely a database relationship - a note never creates, copies or moves
    anything in Google Drive, exactly like a wishlist entry.

    client_id is ALWAYS taken from the authenticated client session, never
    from a request body/path (see services/comment_service.py), and a row is
    only ever written after the album -> client chain has been verified.
    client_id is deliberately redundant with album.client_id: it keeps every
    "this client's notes" query a single indexed lookup and lets the unique
    constraint below enforce ONE note per (client, album, page).

    media_id points at the item shown on that page and is NULLABLE with
    ON DELETE SET NULL: a note is feedback about a page, so it must survive
    the studio deleting (or moving) the photo it was about - the note simply
    loses its thumbnail.

    page_number is the logical page (spread) number, 1-based, in the Book
    View's front-to-back order. It is what makes the notes readable in the
    admin UI ("page 3 of the book"), independent of how the media rows are
    paginated or filtered.
    """

    __tablename__ = "album_comments"
    __table_args__ = (
        # One note per client per page: re-submitting a page edits the
        # existing note instead of stacking duplicates. The constraint's
        # index leads with client_id, so it also serves every
        # "this client's notes for this album" lookup.
        UniqueConstraint("client_id", "album_id", "page_number", name="uq_album_comment_client_album_page"),
    )

    album_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("albums.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("media.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 1-based page (spread) number in the Book View's front-to-back order.
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    # "open" until the studio resolves it; the admin UI shows the status.
    status: Mapped[str] = mapped_column(
        Enum("open", "resolved", name="album_comment_status"), default="open", nullable=False
    )
