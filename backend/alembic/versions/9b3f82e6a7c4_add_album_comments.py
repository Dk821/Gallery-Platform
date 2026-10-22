"""add album_comments table

A client's page notes ("comments") for the Book View: one note per page
(spread) of an album, written from the client's own gallery session.

  UNIQUE(client_id, album_id, page_number)   one note per client per page
  ix_album_comments_album_id                 the studio's per-album listing
  ix_album_comments_client_id                the client's own notes
  ix_album_comments_media_id                 the studio's "which page is this
                                             note about" lookup

The album and client foreign keys cascade (deleting either removes the
notes). The media foreign key is ON DELETE SET NULL on purpose: a note is
feedback ABOUT a page, so it must survive the studio deleting the photo it
was about - it simply loses its picture.

Revision ID: 9b3f82e6a7c4
Revises: 711430f7f988
Create Date: 2026-10-22 10:15:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "9b3f82e6a7c4"
down_revision = "711430f7f988"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "album_comments",
        sa.Column("album_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("media_id", sa.BigInteger(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "resolved", name="album_comment_status"),
            server_default="open",
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["album_id"], ["albums.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "client_id", "album_id", "page_number", name="uq_album_comment_client_album_page"
        ),
    )
    op.create_index("ix_album_comments_album_id", "album_comments", ["album_id"], unique=False)
    op.create_index("ix_album_comments_client_id", "album_comments", ["client_id"], unique=False)
    op.create_index("ix_album_comments_media_id", "album_comments", ["media_id"], unique=False)


def downgrade() -> None:
    # Dropping the table drops its indexes with it. Do NOT drop the indexes
    # separately first: MySQL refuses ("needed in a foreign key constraint")
    # because the media_id foreign key depends on ix_album_comments_media_id.
    op.drop_table("album_comments")
