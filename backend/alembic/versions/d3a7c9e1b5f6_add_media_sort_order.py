"""add sort_order to media

The studio can now drag photos into the order they should appear in the
Book View and the client's gallery. sort_order is 1-based inside one album;
existing rows are backfilled from their current book order (created_at,
then id), which is exactly what Book View used before this column existed.

Uploads and items moved in from another album append at the end and ties
fall back to id, so ordering stays deterministic even while two uploads
race for the same max+1 value.

Revision ID: d3a7c9e1b5f6
Revises: 9b3f82e6a7c4
Create Date: 2026-10-22 15:05:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "d3a7c9e1b5f6"
down_revision = "9b3f82e6a7c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))

    # Backfill each album's existing rows in the order Book View already read
    # them. MySQL refuses to read the target table from a plain subquery, so it
    # gets the canonical derived-table JOIN form; SQLite (local/dev) accepts
    # the correlated subquery directly.
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            """
            UPDATE media AS m
            JOIN (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY album_id ORDER BY created_at, id
                       ) AS rn
                FROM media
            ) AS ranked ON ranked.id = m.id
            SET m.sort_order = ranked.rn
            """
        )
    else:
        op.execute(
            """
            UPDATE media
            SET sort_order = (
                SELECT rn FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY album_id ORDER BY created_at, id
                           ) AS rn
                    FROM media
                ) AS ranked
                WHERE ranked.id = media.id
            )
            """
        )


def downgrade() -> None:
    op.drop_column("media", "sort_order")
