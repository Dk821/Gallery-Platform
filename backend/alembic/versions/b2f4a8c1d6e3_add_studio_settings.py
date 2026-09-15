"""add studio_settings table

Revision ID: b2f4a8c1d6e3
Revises: a3c9d1f7b204
Create Date: 2026-09-13 23:50:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "b2f4a8c1d6e3"
down_revision = "a3c9d1f7b204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Single-row settings table - no data is seeded here on purpose. The
    # first call to get_studio_settings() (app/services/studio_settings_
    # service.py) lazily creates the id=1 row with the model's defaults,
    # so a fresh install and an upgraded install behave identically.
    op.create_table(
        "studio_settings",
        sa.Column("studio_name", sa.String(length=255), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("min_client_password_length", sa.Integer(), nullable=False),
        sa.Column("download_link_ttl_hours", sa.Integer(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("studio_settings")
