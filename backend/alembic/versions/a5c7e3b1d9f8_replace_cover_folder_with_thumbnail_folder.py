"""replace the client cover columns with a single thumbnail folder column

The automatic client cover has been removed. Nothing ever rendered
cover.webp - the gallery landing page used a static local backdrop and the
album cards used each item's own thumbnail - so the cover was an extra
~200 KB Drive file plus an extra HTTP round trip per upload for an image no
user saw.

What this migration does:

  cover_folder_id     -> renamed to thumbnail_folder_id, VALUE PRESERVED
  cover_drive_file_id -> dropped

Renaming rather than dropping the folder column is deliberate. Every item
thumbnail (video poster / photo thumb) was already stored in that one
per-client folder, and Media.thumbnail_reference holds the file id of each
one - the gallery serves a thumbnail by that id, never by folder. Dropping
the column and creating a fresh "Thumbnails" folder would leave every
existing thumb stranded in an orphaned "Cover Images" folder that nothing
tracks. Keeping the id means existing thumbnails keep resolving and new ones
simply land in the same folder.

The folder is still *named* "Cover Images" in Drive for clients that already
have one; only new clients get a folder called "Thumbnails". Renaming the
existing ones is a Drive write, which belongs in an ops step rather than a
schema migration (there is no Drive credential guarantee at migrate time).
The leftover cover.webp in each of those folders is likewise harmless litter
to clear by hand, or with `backend/app/reconcile_orphans.py`'s storage
sweep - it is no longer referenced by any column.

Reversible: downgrade re-adds cover_drive_file_id and renames the column
back, so the folder id (and therefore every existing thumbnail) survives a
downgrade too. The cover itself cannot be restored - its bytes are gone from
the database's point of view, which is the point of the downgrade being
"restore the schema, not the data".

Revision ID: a5c7e3b1d9f8
Revises: d4a2c8f6b3e1
Create Date: 2026-09-26 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "a5c7e3b1d9f8"
down_revision = "d4a2c8f6b3e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "clients",
        "cover_folder_id",
        new_column_name="thumbnail_folder_id",
        existing_type=sa.String(length=255),
        existing_nullable=True,
    )
    op.drop_column("clients", "cover_drive_file_id")


def downgrade() -> None:
    op.add_column("clients", sa.Column("cover_drive_file_id", sa.String(length=255), nullable=True))
    op.alter_column(
        "clients",
        "thumbnail_folder_id",
        new_column_name="cover_folder_id",
        existing_type=sa.String(length=255),
        existing_nullable=True,
    )
