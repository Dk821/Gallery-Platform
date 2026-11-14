from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import IdMixin


class AuditLog(Base, IdMixin):
    __tablename__ = "audit_logs"

    user_type: Mapped[str] = mapped_column(Enum("admin", "client", name="audit_user_type"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The studio the action affected (NULL for platform-level events with no
    # studio, e.g. a super-admin login). Filtering audit logs by studio_id is
    # what keeps a studio admin from ever seeing another studio's history.
    studio_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("studios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Small, NON-SENSITIVE context (old/new quota, counts, reason codes).
    # Never passwords, tokens, cookies or storage credentials - see
    # app.services.audit_service, which strips known-sensitive keys.
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime, server_default=func.now(), nullable=False)
