from sqlalchemy import BigInteger, DateTime, Enum, String, func
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
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime, server_default=func.now(), nullable=False)
