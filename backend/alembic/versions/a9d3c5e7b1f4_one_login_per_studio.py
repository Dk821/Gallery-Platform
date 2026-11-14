"""one studio login per studio (unique admins.studio_id)

Each studio has exactly one studio-admin login. This makes the database enforce it:
a UNIQUE index on admins.studio_id replaces the plain index. Super admins and
unmapped legacy admins have studio_id NULL, and several NULLs are allowed.

SAFE FOR EXISTING DATA: nothing is deleted or changed. If any studio currently has
MORE THAN ONE admin account the unique index cannot be created yet, so this
migration leaves the old index in place, prints which studios are affected and
carries on (the application already refuses to create a second login). Clean the
duplicates up with

    python -m app.consolidate_studio_logins              # report only
    python -m app.consolidate_studio_logins --keep STUDIO_ID:ADMIN_ID ... --apply

which also creates the unique index once every studio has at most one login.

Revision ID: a9d3c5e7b1f4
Revises: f3b8d1a6c9e4
"""

import sqlalchemy as sa
from alembic import op

revision = "a9d3c5e7b1f4"
down_revision = "f3b8d1a6c9e4"
branch_labels = None
depends_on = None

UNIQUE_NAME = "uq_admins_studio_id"
OLD_NAME = "ix_admins_studio_id"


def _index_names(bind) -> set[str]:
    return {ix["name"] for ix in sa.inspect(bind).get_indexes("admins")}


def upgrade() -> None:
    bind = op.get_bind()
    admins = sa.table("admins", sa.column("studio_id"))
    dupes = bind.execute(
        sa.select(admins.c.studio_id, sa.func.count().label("n"))
        .where(admins.c.studio_id.is_not(None))
        .group_by(admins.c.studio_id)
        .having(sa.func.count() > 1)
    ).all()
    if dupes:
        listing = ", ".join(f"studio {row.studio_id} ({row.n} logins)" for row in dupes)
        print(
            "\n*** ONE-LOGIN-PER-STUDIO: the unique index was NOT created because these studios have more than "
            f"one admin account: {listing}.\n"
            "    Nothing was changed. Run `python -m app.consolidate_studio_logins` to review them and choose "
            "which account each studio keeps; it creates the index when every studio is clean.\n"
        )
        return

    names = _index_names(bind)
    if UNIQUE_NAME not in names:
        # Created BEFORE the old index is dropped: MySQL needs an index on the foreign-key column at all times.
        op.create_index(UNIQUE_NAME, "admins", ["studio_id"], unique=True)
    if OLD_NAME in names:
        op.drop_index(OLD_NAME, table_name="admins")


def downgrade() -> None:
    bind = op.get_bind()
    names = _index_names(bind)
    if OLD_NAME not in names:
        op.create_index(OLD_NAME, "admins", ["studio_id"], unique=False)
    if UNIQUE_NAME in names:
        op.drop_index(UNIQUE_NAME, table_name="admins")
