"""
Builds the human-readable Google Drive folder names for clients and albums.

Format (per spec):
    {client_name}_C_{unique_id}
    {album_name}_A_{unique_id}

`unique_id` is an opaque, random, per-record id - never the database
numeric id - generated once when the record is created and stored
alongside it (Client.folder_uid / Album.folder_uid). Renaming a client or
album only ever changes the readable portion of the folder name; the
`unique_id` suffix is never regenerated, which is also what keeps two
records that happen to share a name unambiguous.

This module only builds strings - it never talks to Drive or the DB. It's
used by client_service/album_service, which call StorageService with the
resulting name.
"""

import re
import uuid

CLIENT_FOLDER_SEPARATOR = "_C_"
ALBUM_FOLDER_SEPARATOR = "_A_"

# Generous but bounded - keeps the final folder name well under Drive's
# (very high) folder name length limit without truncating any name a real
# client/album would plausibly have.
MAX_READABLE_NAME_LENGTH = 200

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")


def generate_folder_uid() -> str:
    """
    A random, opaque, stable id for embedding in a Drive folder name.
    Deliberately independent of both the DB primary key (never exposed)
    and client_uuid/album_uuid (the client-facing gallery id, which admins
    can regenerate for security reasons - see
    client_service.regenerate_gallery_id - without that affecting Drive
    folder identity).

    12 uppercase hex characters (48 bits of randomness from uuid4) is
    enough that two records - even with the identical readable name - are
    never ambiguous.
    """
    return uuid.uuid4().hex[:12].upper()


def sanitize_display_name(name: str) -> str:
    """
    Minimal cleanup of the human-readable portion of a folder name: strips
    control characters, collapses whitespace, and trims to a safe length.
    Google Drive folder names aren't filesystem paths, so characters like
    "/" are valid there and are deliberately left alone rather than
    mangled.
    """
    cleaned = _CONTROL_CHARS_RE.sub("", name)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned:
        cleaned = "Untitled"
    return cleaned[:MAX_READABLE_NAME_LENGTH]


def build_client_folder_name(client_name: str, folder_uid: str) -> str:
    return f"{sanitize_display_name(client_name)}{CLIENT_FOLDER_SEPARATOR}{folder_uid}"


def build_album_folder_name(album_name: str, folder_uid: str) -> str:
    return f"{sanitize_display_name(album_name)}{ALBUM_FOLDER_SEPARATOR}{folder_uid}"
