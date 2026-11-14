"""studio slug for client gallery links

Adds studios.slug (unique): the studio name as it appears in client gallery links,
/<slug>/gallery/<link id>. Existing studios get one made from their current name
(duplicates get -2, -3, ...). The old /gallery/<link id> links keep working: the
frontend redirects them to the new form.

Revision ID: b7c3e9a1d5f2
Revises: a9d3c5e7b1f4
"""

import re
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "b7c3e9a1d5f2"
down_revision = "a9d3c5e7b1f4"
branch_labels = None
depends_on = None

_RESERVED = {"admin", "super-admin", "gallery", "api", "assets", "static", "src", "login", "logout", "health", "docs", "redoc", "openapi-json"}


def _slugify(name) -> str:
    ascii_text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:40].strip("-")
    slug = slug or "studio"
    return f"{slug}-studio" if slug in _RESERVED else slug


def upgrade() -> None:
    op.add_column("studios", sa.Column("slug", sa.String(length=60), nullable=True))
    bind = op.get_bind()
    taken: set[str] = set()
    for studio_id, name in bind.execute(sa.text("SELECT id, name FROM studios ORDER BY id")).fetchall():
        base = _slugify(name)
        slug, n = base, 2
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        taken.add(slug)
        bind.execute(sa.text("UPDATE studios SET slug = :slug WHERE id = :id"), {"slug": slug, "id": studio_id})
    op.create_index("ix_studios_slug", "studios", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_studios_slug", table_name="studios")
    op.drop_column("studios", "slug")
