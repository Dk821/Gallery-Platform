"""add media_wishlists table

A client's favourite ("wishlist") markers on media. Purely a database
relationship - nothing is ever copied or moved in Google Drive.

  UNIQUE(client_id, media_id)   one row per client per media item
  ix_media_wishlists_media_id   media-side lookups (admin EXISTS filter and
                                the ON DELETE CASCADE from media)

Both foreign keys cascade, so deleting a media item, an album or a client
removes the affected wishlist rows automatically.

Revision ID: c8f3d5b0e2a4
Revises: b7e2c4a9d1f3
Create Date: 2026-09-19 12:05:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "c8f3d5b0e2a4"
down_revision = "b7e2c4a9d1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_wishlists",
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("media_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "media_id", name="uq_media_wishlist_client_media"),
    )
    op.create_index("ix_media_wishlists_media_id", "media_wishlists", ["media_id"], unique=False)


def downgrade() -> None:
    # Dropping the table drops its indexes with it. Do NOT drop
    # ix_media_wishlists_media_id separately first: MySQL refuses ("needed in
    # a foreign key constraint") because the media_id foreign key depends on it.
    op.drop_table("media_wishlists")
