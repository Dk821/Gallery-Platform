"""add book_view_enabled to albums

Revision ID: a1c7f4e2b9d6
Revises: a5c7e3b1d9f8
Create Date: 2026-09-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c7f4e2b9d6'
# Must be the current single head (a5c7e3b1d9f8) - pointing at d4a2c8f6b3e1
# instead would branch off mid-chain and leave two heads, which makes
# `alembic upgrade head` refuse to run at all.
down_revision = 'a5c7e3b1d9f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'albums',
        sa.Column('book_view_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # server_default only exists to backfill existing rows during this
    # migration - drop it afterwards so the model's Python-side default is
    # the single source of truth for new rows, same convention as every
    # other boolean/default column in this schema.
    op.alter_column('albums', 'book_view_enabled', server_default=None)


def downgrade() -> None:
    op.drop_column('albums', 'book_view_enabled')