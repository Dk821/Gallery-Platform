"""add thumbnail mime type to media

Thumbnails switch from JPEG to WebP (browser-generated during upload). The
streaming route serves each thumbnail under its stored content-type, so the
Media row needs to remember what its thumbnail actually is - existing rows
(created before this migration) are JPEG, everything stored after is WebP.

Revision ID: d1f6a3b7e90c
Revises: c4d8e2a9f1b7
Create Date: 2026-09-19 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "d1f6a3b7e90c"
down_revision = "c4d8e2a9f1b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media",
        sa.Column("thumbnail_mime_type", sa.String(length=50), nullable=True, server_default="image/jpeg"),
    )


def downgrade() -> None:
    op.drop_column("media", "thumbnail_mime_type")