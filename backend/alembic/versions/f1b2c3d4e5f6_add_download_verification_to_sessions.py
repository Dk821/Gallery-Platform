"""add download password verification state to sessions

Revision ID: f1b2c3d4e5f6
Revises: e7a1c2b4f9d0
Create Date: 2026-09-09 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "f1b2c3d4e5f6"
down_revision = "e7a1c2b4f9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("download_password_verified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "download_password_verified_at")
