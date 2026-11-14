"""
The studio name used in client gallery links: ``/<slug>/gallery/<link id>``.

Lower-case letters, digits and single hyphens, made from the studio name and unique across studios
(a second "Acme Photo" becomes ``acme-photo-2``). A few words are never used because they are
top-level addresses of the app itself.
"""

from sqlalchemy.orm import Session as DbSession

from app.models.studio import Studio
from app.services.storage_paths import slugify

MAX_STUDIO_SLUG_LENGTH = 40

# Top-level paths the app or the dev/production proxy already uses.
RESERVED_SLUGS = frozenset(
    {"admin", "super-admin", "gallery", "api", "assets", "static", "src", "login", "logout", "health", "docs", "redoc", "openapi-json"}
)


def build_studio_slug(db: DbSession, name: str | None, *, exclude_studio_id: int | None = None) -> str:
    """A free slug for ``name``; ``exclude_studio_id`` lets a studio keep its own."""
    base = slugify(name, "studio", MAX_STUDIO_SLUG_LENGTH)
    if base in RESERVED_SLUGS:
        base = f"{base}-studio"
    taken = {
        row[0]
        for row in db.query(Studio.slug).filter(Studio.slug.like(f"{base}%"), Studio.id != (exclude_studio_id or -1)).all()
    }
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def gallery_path(slug: str | None, client_uuid: str) -> str:
    """A client's gallery link: /<studio slug>/gallery/<link id>, or the older /gallery/<link id> without a slug."""
    return f"/{slug}/gallery/{client_uuid}" if slug else f"/gallery/{client_uuid}"
