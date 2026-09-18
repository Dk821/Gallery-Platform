"""add drive resumable session url to upload_sessions for direct browser upload

Revision ID: c4d8e2a9f1b7
Revises: b2f4a8c1d6e3
Create Date: 2026-09-18 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "c4d8e2a9f1b7"
down_revision = "b2f4a8c1d6e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "upload_sessions",
        sa.Column("drive_resumable_upload_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("upload_sessions", "drive_resumable_upload_url")
