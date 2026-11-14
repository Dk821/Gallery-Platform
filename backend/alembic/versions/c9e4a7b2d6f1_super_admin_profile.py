"""super admin profile: company name, contact number, logo

Adds admins.company_name, admins.contact_phone and admins.logo_url. They are used by the super
admin's Settings page; the logo and company name appear in the console sidebar.

Revision ID: c9e4a7b2d6f1
Revises: b7c3e9a1d5f2
"""

import sqlalchemy as sa
from alembic import op

revision = "c9e4a7b2d6f1"
down_revision = "b7c3e9a1d5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admins", sa.Column("company_name", sa.String(length=255), nullable=True))
    op.add_column("admins", sa.Column("contact_phone", sa.String(length=50), nullable=True))
    op.add_column("admins", sa.Column("logo_url", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("admins", "logo_url")
    op.drop_column("admins", "contact_phone")
    op.drop_column("admins", "company_name")
