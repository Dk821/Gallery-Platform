"""studio storage prefix + wider storage path columns

Adds studios.storage_prefix: the studio's readable folder in object storage
(e.g. "studios/acme-photo-1"), chosen once at creation and never changed.
Existing studios keep NULL and continue to use "studios/{id}", so no file moves.

Also widens the columns that hold storage folder ids / object keys from 255 to
512 characters, because those paths now start with the studio folder and can
contain a client name.

Revision ID: f3b8d1a6c9e4
Revises: e5a1b9c7d3f2
"""

import sqlalchemy as sa
from alembic import op

revision = "f3b8d1a6c9e4"
down_revision = "e5a1b9c7d3f2"
branch_labels = None
depends_on = None

_WIDEN = (
    ("clients", "drive_folder_id"),
    ("clients", "thumbnail_folder_id"),
    ("albums", "drive_folder_id"),
    ("upload_sessions", "drive_file_id"),
    ("upload_sessions", "thumbnail_drive_file_id"),
)


def upgrade() -> None:
    op.add_column("studios", sa.Column("storage_prefix", sa.String(length=255), nullable=True))
    for table, column in _WIDEN:
        op.alter_column(table, column, existing_type=sa.String(length=255), type_=sa.String(length=512), existing_nullable=True)


def downgrade() -> None:
    # Shrinking back fails if a longer path was stored in the meantime; that is intended.
    for table, column in reversed(_WIDEN):
        op.alter_column(table, column, existing_type=sa.String(length=512), type_=sa.String(length=255), existing_nullable=True)
    op.drop_column("studios", "storage_prefix")
