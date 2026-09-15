"""add download_records table

Revision ID: 2c8a4f6d3b1a
Revises: 8f98a3b5cfe9
Create Date: 2026-09-09 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2c8a4f6d3b1a'
down_revision = '8f98a3b5cfe9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('download_records',
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('album_id', sa.BigInteger(), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('download_type', sa.Enum('all', 'selected', name='download_record_type'), nullable=False),
    sa.Column('file_count', sa.Integer(), nullable=False),
    sa.Column('total_bytes', sa.BigInteger(), nullable=False),
    sa.Column('downloaded_at', sa.DateTime(), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['album_id'], ['albums.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_id'], ['download_jobs.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_download_records_album_id'), 'download_records', ['album_id'], unique=False)
    op.create_index(op.f('ix_download_records_client_id'), 'download_records', ['client_id'], unique=False)
    op.create_index(op.f('ix_download_records_downloaded_at'), 'download_records', ['downloaded_at'], unique=False)
    op.create_index(op.f('ix_download_records_job_id'), 'download_records', ['job_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_download_records_job_id'), table_name='download_records')
    op.drop_index(op.f('ix_download_records_downloaded_at'), table_name='download_records')
    op.drop_index(op.f('ix_download_records_client_id'), table_name='download_records')
    op.drop_index(op.f('ix_download_records_album_id'), table_name='download_records')
    op.drop_table('download_records')