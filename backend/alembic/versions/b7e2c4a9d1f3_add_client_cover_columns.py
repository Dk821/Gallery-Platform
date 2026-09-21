"""add automatic cover columns to clients

Every client gets ONE automatically generated cover image (WebP), stored in a
dedicated "Cover Images" Drive folder at the client level - never inside an
album. Both columns are nullable: every client that exists before this
migration simply has no cover yet, keeps working exactly as before (the
gallery falls back to its default hero), and gets a cover on its next
eligible photo upload. No backfill is required or performed.

  cover_drive_file_id - Drive file id of cover.webp
  cover_folder_id     - Drive folder id of the client's "Cover Images" folder

Revision ID: b7e2c4a9d1f3
Revises: d1f6a3b7e90c
Create Date: 2026-09-19 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "b7e2c4a9d1f3"
down_revision = "d1f6a3b7e90c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("cover_drive_file_id", sa.String(length=255), nullable=True))
    op.add_column("clients", sa.Column("cover_folder_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "cover_folder_id")
    op.drop_column("clients", "cover_drive_file_id")
