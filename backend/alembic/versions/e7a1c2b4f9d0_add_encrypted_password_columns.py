"""add encrypted password columns to clients

Revision ID: e7a1c2b4f9d0
Revises: 2c8a4f6d3b1a
Create Date: 2026-09-09 09:15:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "e7a1c2b4f9d0"
down_revision = "2c8a4f6d3b1a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("password_encrypted", sa.Text(), nullable=True))
    op.add_column("clients", sa.Column("download_password_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "download_password_encrypted")
    op.drop_column("clients", "password_encrypted")