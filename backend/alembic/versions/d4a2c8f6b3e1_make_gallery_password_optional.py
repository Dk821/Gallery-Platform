"""make client gallery password optional

Revision ID: d4a2c8f6b3e1
Revises: c8f3d5b0e2a4
Create Date: 2026-09-22 10:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "d4a2c8f6b3e1"
down_revision = "c8f3d5b0e2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Clients may now be created without a gallery password (password_hash =
    # NULL), which the gallery flow treats as "no password prompt".
    op.alter_column("clients", "password_hash", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # Safest downgrade: refuse to re-apply NOT NULL while passwordless rows
    # exist, rather than silently breaking them. Admins must backfill a
    # password first.
    op.alter_column("clients", "password_hash", existing_type=sa.String(length=255), nullable=False)