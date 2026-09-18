"""
Checks every setting in backend/.env against reality: not just "is it set",
but "does it actually work right now" - connects to the real database,
refreshes the real Google Drive token and probes the real root folder,
checks the ZIP temp dir is actually writable with real free space, checks
ffmpeg is actually on PATH, etc.

Usage:
    cd backend
    python scripts/check_env.py

Exits 0 if everything passed, 1 if anything FAILed (so it's also usable as
a pre-deploy sanity gate: `python scripts/check_env.py || exit 1`).
Safe to run anytime - it never writes/deletes real data, only a throwaway
temp file inside ZIP_TEMP_DIR to prove it's writable.
"""

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so `import app...` works

RESULTS: list[tuple[str, str, str]] = []  # (status, name, detail)


def check(name: str):
    """Decorator: runs fn(), records PASS/WARN/FAIL from what it returns/raises."""

    def decorator(fn):
        try:
            status, detail = fn()
        except Exception as exc:  # noqa: BLE001 - a check crashing IS a FAIL, not a script crash
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
        RESULTS.append((status, name, detail))
        return fn

    return decorator


def ok(detail: str = "OK"):
    return "PASS", detail


def warn(detail: str):
    return "WARN", detail


def fail(detail: str):
    return "FAIL", detail


# ---------------------------------------------------------------------------
# Load settings the same way the real app does (backend/.env via pydantic).
# If this itself blows up (missing required field, unparseable value), that
# IS the first and only result - nothing else can be checked without it.
# ---------------------------------------------------------------------------
try:
    from app.config.settings import get_settings

    settings = get_settings()
except Exception as exc:  # noqa: BLE001
    print(f"FAIL  .env failed to load at all: {type(exc).__name__}: {exc}")
    print("\nFix backend/.env (a required field is missing or a value can't be parsed) and re-run.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
@check("DATABASE_URL")
def _():
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError

    if not settings.database_url:
        return fail("Not set.")
    try:
        engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
        start = time.monotonic()
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        engine.dispose()
        return ok(f"Connected ({elapsed_ms}ms) - MySQL {version}")
    except SQLAlchemyError as exc:
        return fail(f"Could not connect: {exc.__class__.__name__}: {str(exc)[:200]}")


# ---------------------------------------------------------------------------
# Sessions / crypto
# ---------------------------------------------------------------------------
@check("SECRET_KEY")
def _():
    key = settings.secret_key
    if not key:
        return fail("Not set - admin sessions and encrypted password storage cannot work at all.")
    if key == "CHANGE_ME_TO_A_LONG_RANDOM_VALUE":
        return fail(
            "Still the placeholder value from .env.example. Anyone who knows this default can "
            "forge admin sessions and decrypt every stored client password. Generate a real "
            "random value, e.g.: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    if len(key) < 32:
        return warn(f"Only {len(key)} characters - fine functionally, but short for a signing/encryption key.")
    return ok(f"Set ({len(key)} characters, not the placeholder).")


@check("CROSS_SITE_FRONTEND / ENVIRONMENT combination")
def _():
    if settings.cross_site_frontend and settings.environment == "development":
        return warn(
            "CROSS_SITE_FRONTEND=true forces Secure cookies, which browsers refuse over plain "
            "HTTP - logins will silently fail to persist in local dev with this combination."
        )
    return ok(f"cross_site_frontend={settings.cross_site_frontend}, environment={settings.environment}")


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------
@check("GOOGLE_DRIVE_CLIENT_ID / SECRET / REFRESH_TOKEN")
def _():
    missing = [
        name
        for name, val in (
            ("GOOGLE_DRIVE_CLIENT_ID", settings.google_drive_client_id),
            ("GOOGLE_DRIVE_CLIENT_SECRET", settings.google_drive_client_secret),
            ("GOOGLE_DRIVE_REFRESH_TOKEN", settings.google_drive_refresh_token),
        )
        if not val
    ]
    if missing:
        return fail(f"Not set: {', '.join(missing)}. Storage is completely unconfigured.")

    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials(
        token=None,
        refresh_token=settings.google_drive_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_drive_client_id,
        client_secret=settings.google_drive_client_secret,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        return fail(
            f"Token rejected by Google: {exc}. Refresh token is expired/revoked - run "
            "scripts/generate_drive_refresh_token.py to get a new one."
        )
    return ok("Refresh token is valid - Google issued a new access token.")


@check("GOOGLE_DRIVE_ROOT_FOLDER_ID")
def _():
    if not settings.google_drive_root_folder_id:
        return warn("Not set - uploads with no explicit parent will fail with no root to fall back to.")

    # Only meaningful if the refresh token check above actually succeeded -
    # re-derive fresh credentials here rather than depending on call order.
    if not (settings.google_drive_client_id and settings.google_drive_client_secret and settings.google_drive_refresh_token):
        return warn("Skipped - Drive credentials aren't configured (see the check above).")

    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    creds = Credentials(
        token=None,
        refresh_token=settings.google_drive_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_drive_client_id,
        client_secret=settings.google_drive_client_secret,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    try:
        creds.refresh(Request())
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        meta = service.files().get(fileId=settings.google_drive_root_folder_id, fields="id, name, mimeType, trashed").execute()
    except RefreshError as exc:
        return fail(f"Can't verify - token itself is invalid: {exc}")
    except HttpError as exc:
        status = getattr(exc.resp, "status", "?")
        if status == 404:
            return fail("Folder not found - wrong id, or this Drive account was never granted access to it.")
        return fail(f"HTTP {status} fetching folder: {exc}")

    if meta.get("mimeType") != "application/vnd.google-apps.folder":
        return fail(f"That id exists but is NOT a folder (mimeType={meta.get('mimeType')}).")
    if meta.get("trashed"):
        return fail(f"Folder '{meta.get('name')}' exists but is in the Trash.")
    return ok(f"Accessible - folder '{meta.get('name')}' (id={meta['id']}).")


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
@check("CORS_ORIGINS")
def _():
    origins = settings.cors_origin_list

    if not origins:
        dev_origin = settings.dev_frontend_origin

        if not dev_origin:
            return fail(
                "CORS_ORIGINS and DEV_FRONTEND_ORIGIN are both not set."
            )

        if not (
            dev_origin.startswith("http://")
            or dev_origin.startswith("https://")
        ):
            return fail(
                f"DEV_FRONTEND_ORIGIN is not valid (missing scheme): {dev_origin}"
            )

        return warn(
            f"CORS_ORIGINS not set - falling back to {dev_origin} only. "
            "Fine for local dev, wrong for prod."
        )

    bad = [
        o
        for o in origins
        if not (o.startswith("http://") or o.startswith("https://"))
    ]

    if bad:
        return fail(f"Not valid origins (missing scheme): {bad}")

    return ok(f"{len(origins)} origin(s): {', '.join(origins)}")

# ---------------------------------------------------------------------------
# Uploads / ZIP jobs
# ---------------------------------------------------------------------------
@check("ALLOWED_IMAGE_TYPES / ALLOWED_VIDEO_TYPES")
def _():
    images = settings.allowed_image_extensions
    videos = settings.allowed_video_extensions
    if not images and not videos:
        return fail("Both empty - no upload would ever be accepted.")
    return ok(f"{len(images)} image type(s), {len(videos)} video type(s): {sorted(images | videos)}")


@check("ZIP_TEMP_DIR")
def _():
    target = Path(settings.zip_temp_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return fail(f"Can't create '{target}': {exc}")

    try:
        with tempfile.NamedTemporaryFile(dir=target, prefix="env-check-", suffix=".tmp", delete=True) as f:
            f.write(b"ok")
    except OSError as exc:
        return fail(f"Directory exists but isn't writable: {exc}")

    try:
        free_gb = shutil.disk_usage(target).free / (1024 ** 3)
    except OSError:
        return warn(f"Writable at '{target}', but couldn't check free disk space.")

    if free_gb < settings.upload_min_free_disk_gb:
        return warn(
            f"Writable at '{target}', but only {free_gb:.1f}GB free - below the configured "
            f"UPLOAD_MIN_FREE_DISK_GB={settings.upload_min_free_disk_gb}GB floor, so uploads will "
            f"currently be refused."
        )
    return ok(f"Writable at '{target}' - {free_gb:.1f}GB free.")


@check("Upload concurrency settings (internal consistency)")
def _():
    problems = []
    if settings.upload_max_concurrent_requests < settings.upload_max_concurrent:
        problems.append(
            f"upload_max_concurrent_requests ({settings.upload_max_concurrent_requests}) must be >= "
            f"upload_max_concurrent ({settings.upload_max_concurrent})"
        )
    if settings.effective_max_upload_bytes <= 0:
        problems.append("effective max upload size resolves to 0 bytes")
    if problems:
        return fail("; ".join(problems))
    return ok(
        f"max_concurrent={settings.upload_max_concurrent}, "
        f"max_concurrent_requests={settings.upload_max_concurrent_requests}, "
        f"effective_max_upload={settings.effective_max_upload_bytes / (1024**3):.1f}GB"
    )


# ---------------------------------------------------------------------------
# ffmpeg (system binary, not from .env, but everything else depends on it
# for video thumbnails - worth surfacing here rather than only in prod logs)
# ---------------------------------------------------------------------------
@check("ffmpeg (system binary)")
def _():
    from app.workers.thumbnail_worker import is_ffmpeg_available

    if is_ffmpeg_available():
        return ok("Found on PATH - video thumbnails will generate.")
    return warn("Not found on PATH - uploads still work, but videos get no poster/thumbnail image.")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
WIDTH = max(len(name) for _, name, _ in RESULTS) if RESULTS else 0
ICON = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}

print()
for status, name, detail in RESULTS:
    print(f"{ICON[status]:8} {name:<{WIDTH}}  {detail}")

n_pass = sum(1 for s, _, _ in RESULTS if s == "PASS")
n_warn = sum(1 for s, _, _ in RESULTS if s == "WARN")
n_fail = sum(1 for s, _, _ in RESULTS if s == "FAIL")
print(f"\n{n_pass} passed, {n_warn} warning(s), {n_fail} failed.\n")

sys.exit(1 if n_fail else 0)
