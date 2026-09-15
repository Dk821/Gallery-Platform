import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import IdMixin


class ClientSession(Base, IdMixin):
    """
    Server-side session record. Only a hash of the session token is stored,
    the same way passwords are hashed - so a DB leak alone can't be used to
    forge sessions. The raw token lives only in the HttpOnly cookie.
    """

    __tablename__ = "sessions"

    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    # Set only after the client has supplied the separate download password.
    # It grants downloads for the rest of this server-side session.
    download_password_verified_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)

    client: Mapped["Client"] = relationship(back_populates="sessions")
