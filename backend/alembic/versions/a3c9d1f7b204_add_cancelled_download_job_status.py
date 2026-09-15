"""add 'cancelled' to download_jobs.status

Revision ID: a3c9d1f7b204
Revises: f1b2c3d4e5f6
Create Date: 2026-09-13 22:00:00.000000
"""

from alembic import op

revision = "a3c9d1f7b204"
down_revision = "f1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MySQL has no ALTER TYPE for enums - widening the allowed value set
    # means re-declaring the column's full ENUM(...) definition. Existing
    # rows/values are untouched; this only adds 'cancelled' as a new
    # option alongside the existing ones.
    op.execute(
        "ALTER TABLE download_jobs MODIFY COLUMN status "
        "ENUM('queued','preparing','processing','completed','failed','expired','cancelled') "
        "NOT NULL DEFAULT 'queued'"
    )


def downgrade() -> None:
    # Narrowing the enum back down would silently truncate any row
    # currently 'cancelled' to '' (MySQL's behavior for an out-of-range
    # enum value) unless those rows are remapped first.
    op.execute("UPDATE download_jobs SET status = 'failed' WHERE status = 'cancelled'")
    op.execute(
        "ALTER TABLE download_jobs MODIFY COLUMN status "
        "ENUM('queued','preparing','processing','completed','failed','expired') "
        "NOT NULL DEFAULT 'queued'"
    )
