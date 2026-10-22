"""add book_layout to albums

Revision ID: 711430f7f988
Revises: a1c7f4e2b9d6
Create Date: 2026-10-09 13:49:21.684096

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '711430f7f988'
down_revision = 'a1c7f4e2b9d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'albums',
        sa.Column('book_layout', sa.String(length=20), nullable=False, server_default='landscape'),
    )
    op.alter_column('albums', 'book_layout', server_default=None)


def downgrade() -> None:
    op.drop_column('albums', 'book_layout')
