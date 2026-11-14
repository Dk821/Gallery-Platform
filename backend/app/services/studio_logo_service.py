"""
Studio logo images.

A super admin uploads a picture; this module checks it really is an image,
re-encodes it (strips metadata, bounds the size, drops anything a browser
could execute) and stores the result in R2 under

    {studio folder}/branding/logo-{version}.png      (e.g. studios/acme-photo-1/branding/logo-9f3a….png)

`version` is a hash of the stored bytes. The studio's `logo_url` column then
holds the same-origin path the browser should load,

    /api/studios/{studio_id}/logo?v={version}

which the public GET route in app/api/studio_branding.py serves. A new upload
therefore always gets a new URL (so browsers never show a stale logo), and the
old object is deleted. A `logo_url` that is a plain https:// address (set
through the API before uploads existed) is left alone and keeps working.
"""

import hashlib
import io
import logging
import re

from PIL import Image, ImageOps

from app.models.studio import Studio
from app.schemas.errors import ApiError
from app.services.storage_paths import studio_root
from app.services.storage_service import StorageError, StorageNotFoundError, StorageService

logger = logging.getLogger("gallery.studios.logo")

# What a browser may send us (before re-encoding) and how large the picture may be.
MAX_LOGO_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_LOGO_PIXELS = 50_000_000
# The stored logo is shrunk to fit inside this box; it is only ever shown small.
LOGO_MAX_SIDE = 512
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}

_VERSION_RE = re.compile(r"^[0-9a-f]{16}$")


def logo_key(studio: Studio, version: str) -> str:
    return f"{studio_root(studio)}/branding/logo-{version}.png"


def logo_path(studio_id: int, version: str) -> str:
    return f"/api/studios/{studio_id}/logo?v={version}"


def uploaded_version(studio: Studio) -> str | None:
    """The version of the studio's uploaded logo, or None (no logo / an external https URL)."""
    prefix = f"/api/studios/{studio.id}/logo?v="
    url = studio.logo_url or ""
    if url.startswith(prefix):
        version = url[len(prefix):]
        if _VERSION_RE.match(version):
            return version
    return None


def process_logo(data: bytes) -> bytes:
    """Validate an uploaded picture and return it as a bounded, metadata-free PNG."""
    if not data:
        raise ApiError(400, "LOGO_EMPTY", "Choose an image file to upload.")
    if len(data) > MAX_LOGO_UPLOAD_BYTES:
        raise ApiError(413, "LOGO_TOO_LARGE", "The logo must be 5 MB or smaller.")
    invalid = ApiError(400, "LOGO_INVALID_IMAGE", "The logo must be a PNG, JPEG, WebP or GIF image.")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ALLOWED_FORMATS:
            raise invalid
        width, height = img.size
        if width < 1 or height < 1 or width * height > MAX_LOGO_PIXELS:
            raise ApiError(400, "LOGO_DIMENSIONS_INVALID", "That image is too large in pixels. Use a smaller image.")
        img.load()  # decode fully now so a truncated/corrupt file fails here
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            has_alpha = "A" in img.getbands() or "transparency" in img.info
            img = img.convert("RGBA" if has_alpha else "RGB")
        img.thumbnail((LOGO_MAX_SIDE, LOGO_MAX_SIDE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types for bad input
        logger.info("rejected logo upload: %s", type(exc).__name__)
        raise invalid from exc


def _delete_quietly(storage: StorageService, studio: Studio, version: str) -> None:
    try:
        storage.delete(logo_key(studio, version))
    except StorageError:
        # A leftover object is harmless; failing the request over it is not useful.
        logger.warning("could not delete old logo object for studio %s", studio.id)


def save_logo(db, storage: StorageService, studio: Studio, data: bytes) -> Studio:
    png = process_logo(data)
    version = hashlib.sha256(png).hexdigest()[:16]
    previous = uploaded_version(studio)
    try:
        storage.put_bytes(logo_key(studio, version), png, "image/png")
    except StorageError as exc:
        raise ApiError(502, "STORAGE_UPLOAD_FAILED", "Could not store the logo. Please try again.") from exc
    studio.logo_url = logo_path(studio.id, version)
    db.commit()
    db.refresh(studio)
    if previous and previous != version:
        _delete_quietly(storage, studio, previous)
    return studio


def remove_logo(db, storage: StorageService, studio: Studio) -> Studio:
    previous = uploaded_version(studio)
    studio.logo_url = None
    db.commit()
    db.refresh(studio)
    if previous:
        _delete_quietly(storage, studio, previous)
    return studio


def read_logo(storage: StorageService, studio: Studio, version: str | None) -> bytes:
    """Bytes of the studio's current uploaded logo. 404 for none, or for a stale `version`."""
    current = uploaded_version(studio)
    if current is None or (version and version != current):
        raise ApiError(404, "LOGO_NOT_FOUND", "This studio has no logo.")
    try:
        return b"".join(storage.download(logo_key(studio, current)))
    except StorageNotFoundError as exc:
        raise ApiError(404, "LOGO_NOT_FOUND", "This studio has no logo.") from exc
    except StorageError as exc:
        raise ApiError(502, "STORAGE_DOWNLOAD_FAILED", "Could not load the logo. Please try again.") from exc
