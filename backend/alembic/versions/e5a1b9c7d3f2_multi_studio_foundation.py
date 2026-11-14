"""multi-studio foundation: studios, roles, studio ownership, storage quota ledger

Turns the single-studio schema into a multi-tenant one WITHOUT touching or
guessing at existing data:

  * new tables:  studios, platform_storage
  * admins:      role (super_admin | studio_admin), studio_id, session_version
  * studio_id (nullable, indexed, FK -> studios) on: clients, albums, media,
                 upload_sessions, download_jobs, download_records,
                 studio_settings (unique: one settings row per studio)
  * audit_logs:  studio_id, actor_role, metadata (JSON)
  * media:       storage_key, storage_provider ('google_drive' for all rows)
  * upload_sessions: reserved_bytes, reservation_status (quota reservation ledger)

LEGACY DATA IS NOT ASSIGNED TO ANY STUDIO HERE. Every pre-existing row keeps
studio_id = NULL and every pre-existing admin becomes a `studio_admin` with no
studio, which the API treats as "not yet mapped" and refuses on studio routes.
Mapping is an explicit, reviewable operator step (dry-run by default):

    python -m app.legacy_to_studio                        # report only
    python -m app.legacy_to_studio --create-studio "Name" --quota-bytes N --apply

The counts of rows awaiting that step are logged below.

BACK UP THE DATABASE BEFORE RUNNING THIS ON PRODUCTION (mysqldump). The
downgrade removes the studio columns and tables again; studio assignments and
quota counters made after the upgrade are discarded by a downgrade (the media,
clients and albums themselves are untouched).

Revision ID: e5a1b9c7d3f2
Revises: d3a7c9e1b5f6
Create Date: 2026-10-23 10:00:00.000000
"""

import logging

import sqlalchemy as sa

from alembic import op

revision = "e5a1b9c7d3f2"
down_revision = "d3a7c9e1b5f6"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# Tables that get a plain nullable studio_id (SET NULL is wrong for tenancy
# data - RESTRICT means a studio with data cannot be deleted by accident).
_OWNED_TABLES = (
    "clients",
    "albums",
    "media",
    "upload_sessions",
    "download_jobs",
    "download_records",
)


def _add_studio_fk(table: str, *, ondelete: str = "RESTRICT", unique: bool = False) -> None:
    with op.batch_alter_table(table) as batch:
        batch.add_column(sa.Column("studio_id", sa.BigInteger(), nullable=True))
        batch.create_foreign_key(f"fk_{table}_studio_id", "studios", ["studio_id"], ["id"], ondelete=ondelete)
        batch.create_index(f"ix_{table}_studio_id", ["studio_id"], unique=unique)


def _drop_studio_fk(table: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(f"fk_{table}_studio_id", type_="foreignkey")
        batch.drop_index(f"ix_{table}_studio_id")
        batch.drop_column("studio_id")


def upgrade() -> None:
    op.create_table(
        "studios",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=50), nullable=True),
        sa.Column("logo_url", sa.String(length=1000), nullable=True),
        sa.Column("brand_color", sa.String(length=20), nullable=True),
        sa.Column("status", sa.Enum("active", "suspended", name="studio_status"), nullable=False),
        sa.Column("quota_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studios_name", "studios", ["name"], unique=False)
    op.create_index("ix_studios_status", "studios", ["status"], unique=False)

    platform_storage = op.create_table(
        "platform_storage",
        sa.Column("used_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # The single platform-wide counter row (id is always 1). Starts at zero;
    # `python -m app.reconcile_quota --apply` (or legacy_to_studio) recomputes it
    # from the real media rows once studios exist.
    op.bulk_insert(platform_storage, [{"id": 1, "used_bytes": 0, "reserved_bytes": 0}])

    # --- admins: RBAC ------------------------------------------------------
    with op.batch_alter_table("admins") as batch:
        batch.add_column(
            sa.Column(
                "role",
                sa.Enum("super_admin", "studio_admin", name="admin_role"),
                server_default="studio_admin",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("studio_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("session_version", sa.Integer(), server_default="0", nullable=False))
        batch.create_foreign_key("fk_admins_studio_id", "studios", ["studio_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_admins_role", ["role"], unique=False)
        batch.create_index("ix_admins_studio_id", ["studio_id"], unique=False)

    # --- tenant ownership --------------------------------------------------
    for table in _OWNED_TABLES:
        _add_studio_fk(table)
    _add_studio_fk("studio_settings", ondelete="CASCADE", unique=True)

    # --- media: provider-neutral object key --------------------------------
    with op.batch_alter_table("media") as batch:
        batch.add_column(sa.Column("storage_key", sa.String(length=500), nullable=True))
        batch.add_column(
            sa.Column("storage_provider", sa.String(length=20), server_default="google_drive", nullable=False)
        )
        batch.create_index("ix_media_storage_key", ["storage_key"], unique=False)

    # --- upload_sessions: quota reservation ledger -------------------------
    with op.batch_alter_table("upload_sessions") as batch:
        batch.add_column(sa.Column("reserved_bytes", sa.BigInteger(), server_default="0", nullable=False))
        batch.add_column(
            sa.Column(
                "reservation_status",
                sa.Enum("none", "reserved", "committed", "released", name="upload_reservation_status"),
                server_default="none",
                nullable=False,
            )
        )
        batch.create_index("ix_upload_sessions_reservation_status", ["reservation_status"], unique=False)

    # --- audit_logs --------------------------------------------------------
    with op.batch_alter_table("audit_logs") as batch:
        batch.add_column(sa.Column("studio_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("actor_role", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("metadata", sa.JSON(), nullable=True))
        batch.create_foreign_key("fk_audit_logs_studio_id", "studios", ["studio_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_audit_logs_studio_id", ["studio_id"], unique=False)

    _report_unmapped_legacy_rows()


def _report_unmapped_legacy_rows() -> None:
    bind = op.get_bind()
    counts = {}
    for table in ("admins", "clients", "albums", "media", "upload_sessions", "download_jobs", "download_records"):
        counts[table] = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
    if any(counts.values()):
        logger.warning(
            "MULTI-STUDIO: existing rows were NOT assigned to a studio: %s. Studio admins stay locked out "
            "until you run `python -m app.legacy_to_studio` (dry run) and then the same command with "
            "--create-studio/--studio-id and --apply. Create the first super admin with "
            "`python -m app.create_super_admin`.",
            ", ".join(f"{t}={n}" for t, n in counts.items() if n),
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_constraint("fk_audit_logs_studio_id", type_="foreignkey")
        batch.drop_index("ix_audit_logs_studio_id")
        batch.drop_column("metadata")
        batch.drop_column("actor_role")
        batch.drop_column("studio_id")

    with op.batch_alter_table("upload_sessions") as batch:
        batch.drop_index("ix_upload_sessions_reservation_status")
        batch.drop_column("reservation_status")
        batch.drop_column("reserved_bytes")

    with op.batch_alter_table("media") as batch:
        batch.drop_index("ix_media_storage_key")
        batch.drop_column("storage_provider")
        batch.drop_column("storage_key")

    _drop_studio_fk("studio_settings")
    for table in reversed(_OWNED_TABLES):
        _drop_studio_fk(table)

    with op.batch_alter_table("admins") as batch:
        batch.drop_constraint("fk_admins_studio_id", type_="foreignkey")
        batch.drop_index("ix_admins_studio_id")
        batch.drop_index("ix_admins_role")
        batch.drop_column("session_version")
        batch.drop_column("studio_id")
        batch.drop_column("role")

    op.drop_table("platform_storage")
    op.drop_index("ix_studios_status", table_name="studios")
    op.drop_index("ix_studios_name", table_name="studios")
    op.drop_table("studios")
