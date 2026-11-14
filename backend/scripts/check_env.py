"""
Checks every setting in backend/.env against reality: not just "is it set",
but "does it actually work right now" - connects to the real database,
checks the real Cloudflare R2 bucket is reachable with the configured keys,
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
# Cloudflare R2 (the only storage backend)
# ---------------------------------------------------------------------------
@check("R2_ACCOUNT_ID / ACCESS_KEY_ID / SECRET_ACCESS_KEY / BUCKET")
def _():
    missing = [
        name
        for name, val in (
            ("R2_ACCOUNT_ID", settings.r2_account_id),
            ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
            ("R2_BUCKET", settings.r2_bucket),
        )
        if not val
    ]
    if missing:
        return fail(f"Not set: {', '.join(missing)}. Storage is completely unconfigured.")
    return ok("All four R2 settings are present.")


@check("R2 bucket reachable with these credentials")
def _():
    if not (settings.r2_account_id and settings.r2_access_key_id and settings.r2_secret_access_key and settings.r2_bucket):
        return warn("Skipped - R2 settings aren't complete (see the check above).")

    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError, EndpointConnectionError

    endpoint = settings.r2_endpoint_url or f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 2, "mode": "standard"}),
    )
    try:
        # Read-only: asks whether the bucket exists and the keys may use it.
        s3.head_bucket(Bucket=settings.r2_bucket)
    except ClientError as exc:
        status = (exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode", "?")
        if status in (401, 403):
            return fail(f"HTTP {status} - the access key is wrong or has no permission on bucket '{settings.r2_bucket}'.")
        if status == 404:
            return fail(f"Bucket '{settings.r2_bucket}' not found in this account.")
        return fail(f"HTTP {status} from R2: {exc}")
    except EndpointConnectionError as exc:
        return fail(f"Can't reach {endpoint}: {exc}")
    return ok(f"Bucket '{settings.r2_bucket}' is reachable.")


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
