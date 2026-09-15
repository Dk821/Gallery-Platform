import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import IdMixin


class DownloadRecord(Base, IdMixin):
    """
    A single ZIP download that was actually served to a client. This is
    deliberately separate from DownloadJob: a job only represents the
    background *preparation* of the ZIP (which can then be downloaded zero,
    one or many times before it expires), so the job table cannot answer
    "how many times was this album actually downloaded?" on its own.
    Each row here is written once the ZIP file response has been sent.

    Only aggregate, user-meaningful fields are stored - no Google Drive ids
    and no internal storage paths, consistent with the rest of the API.
    """

    __tablename__ = "download_records"

    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    album_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("albums.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The DownloadJob that produced the ZIP this download served. Kept for
    # traceability; a job can back many download records. Nullable because
    # a job row may be purged - the analytics history must survive that.
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("download_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # "all" == the whole album was downloaded, "selected" == only the
    # chosen files. Derived at serve time from the job's media snapshot.
    download_type: Mapped[str] = mapped_column(
        Enum("all", "selected", name="download_record_type"), nullable=False
    )

    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    downloaded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow, index=True
    )
