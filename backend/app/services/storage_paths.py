"""
Readable, stable storage prefixes.

Every studio gets one folder in the bucket, named after the studio plus its id:

    studios/acme-photo-1/

The name makes the bucket browsable by a human; the trailing ``-{id}`` keeps it
unique and lets the tenant check (R2Storage.owns_object) recognise a studio's
objects without a database lookup. The prefix is chosen ONCE, when the studio is
created, and stored in ``studios.storage_prefix``. Renaming the studio later
never changes it (R2 cannot rename a folder - that would mean copying every
file), so objects never move.

Studios created before this existed have no stored prefix and keep using the
plain ``studios/{id}`` form, so their files stay exactly where they are.
"""

import re
import unicodedata

# Keeps "studios/<slug>-<id>/albums/<client-slug>_<id>/<uuid>" well inside the
# 512-character storage columns even for long names.
MAX_SLUG_LENGTH = 30


def slugify(text: str | None, fallback: str, max_len: int = MAX_SLUG_LENGTH) -> str:
    """Lower-case ASCII letters, digits and single hyphens; ``fallback`` when nothing is left."""
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:max_len].strip("-")
    return slug or fallback


def build_studio_prefix(name: str | None, studio_id: int) -> str:
    return f"studios/{slugify(name, 'studio')}-{studio_id}"


def studio_root(studio) -> str:
    """The studio's folder in the bucket (no trailing slash)."""
    return studio.storage_prefix or f"studios/{studio.id}"
