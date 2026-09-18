import logging
import time
import uuid
from contextlib import asynccontextmanager

# Logging must be configured before ANY app.* module is imported - several
# of them (via app.database.connection) create the SQLAlchemy engine at
# import time, and if that happens before a handler exists on the root
# logger, SQLAlchemy silently attaches its own default-formatted handler
# directly to the "sqlalchemy.engine.Engine" logger. Once main.py's
# basicConfig() below also adds a handler to root, every query logs twice
# (once per handler, in two different formats). Configuring first avoids
# the situation entirely - see connection.py for the other half of this.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("gallery")

# SQL query/parameter logging is opt-in, not tied to environment=development
# by default: bound params routinely include session token hashes and
# encrypted password blobs (see the `clients`/`sessions` tables), so even
# local dev logs shouldn't have it on by default. Flip settings.sql_echo to
# True (env var SQL_ECHO=true) only when actively debugging a query.
_settings_for_logging = None
try:
    from app.config.settings import get_settings as _get_settings_for_logging

    _settings_for_logging = _get_settings_for_logging()
except Exception:  # noqa: BLE001 - logging setup must never block startup
    pass

if _settings_for_logging is not None and getattr(_settings_for_logging, "sql_echo", False):
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
else:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.admin_albums import router as admin_albums_router
from app.api.admin_activity import router as admin_activity_router
from app.api.admin_clients import router as admin_clients_router
from app.api.admin_dashboard import router as admin_dashboard_router
from app.api.admin_download_jobs import router as admin_download_jobs_router
from app.api.admin_downloads import router as admin_downloads_router
from app.api.admin_media import router as admin_media_router
from app.api.admin_settings import router as admin_settings_router
from app.api.admin_storage import router as admin_storage_router
from app.api.auth import router as auth_router
from app.api.client_download_jobs import router as client_download_jobs_router
from app.api.client_gallery import router as client_gallery_router
# NOTE: if client media routes (list/detail/stream/thumbnail/download) live
# in their own module per ARCHITECTURE.md, import + include it below.
# from app.api.client_media import router as client_media_router
from app.config.settings import get_settings
from app.database.connection import SessionLocal
from app.models.upload_session import UploadSession
from app.workers.thumbnail_worker import is_ffmpeg_available

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # System-dependency check (see SYSTEM_REQUIREMENTS.md): ffmpeg can't be
    # pinned in requirements.txt since it's a system binary, not a pip
    # package - so we verify it's actually present right at boot, once,
    # where it'll be seen in startup logs/monitoring rather than only
    # discovered later as scattered per-upload warnings or a confused
    # "why don't my videos have thumbnails?" support ticket.
    if is_ffmpeg_available():
        logger.info("ffmpeg found on PATH - video poster/thumbnail generation is enabled.")
    else:
        logger.warning(
            "STARTUP WARNING: ffmpeg was not found on PATH. Video uploads will still work, "
            "but NO poster/thumbnail images will be generated for any video until ffmpeg is "
            "installed on this server. See SYSTEM_REQUIREMENTS.md for install instructions."
        )

    # Cookie config sanity check: cross_site_frontend=True forces
    # Secure=True on session cookies (required for SameSite=None), but
    # Secure cookies are rejected by browsers over plain HTTP. If someone
    # enables cross-origin cookies while still in a plain-HTTP dev setup,
    # login would appear to succeed but the cookie would silently never
    # be set - flag that loudly at boot rather than as a confusing "why
    # am I logged out immediately" bug report later.
    if settings.cross_site_frontend and settings.environment == "development":
        logger.warning(
            "CROSS_SITE_FRONTEND is enabled while ENVIRONMENT=development. Session cookies "
            "will be marked Secure, which most browsers refuse to set over plain HTTP. Serve "
            "this API over HTTPS (or disable CROSS_SITE_FRONTEND for local same-origin dev) "
            "or logins will silently fail to persist."
        )

    # On boot, every session still marked "uploading"/"queued" is
    # guaranteed orphaned: its owning thread died with the previous
    # process, so it can never resume or reach a terminal state on its
    # own. Failing them here (instead of only lazily on the first status
    # poll) means the frontend never re-hydrates a dead session as
    # in-flight and never starts an endless poll loop against it.
    try:
        with SessionLocal() as db:
            orphaned = (
                db.query(UploadSession)
                .filter(UploadSession.status.in_(("uploading", "queued")))
                .update(
                    {
                        UploadSession.status: "failed",
                        UploadSession.error_code: "UPLOAD_STALE",
                        UploadSession.error_message: (
                            "This upload was interrupted (server restart or process crash) "
                            "and will not resume."
                        ),
                    },
                    synchronize_session=False,
                )
            )
            if orphaned:
                db.commit()
                logger.info("Failed %s upload session(s) orphaned by the previous process.", orphaned)
    except Exception:  # noqa: BLE001 - startup must never crash the API for a cleanup failure
        logger.exception("Startup sweep of orphaned upload sessions failed - continuing.")

    yield

    # --- Shutdown ---
    # Nothing to release explicitly today (SessionLocal is a scoped
    # sessionmaker, connections return to the pool on their own), but this
    # is the place to add it if a future resource (e.g. a thread pool for
    # ZIP jobs) needs an explicit drain/close on SIGTERM.


app = FastAPI(
    title="Private Gallery Platform API",
    version="0.1.0",
    lifespan=lifespan,
    # Don't expose interactive API docs in production - this API sits in
    # front of client PII (encrypted passwords, session data) and there's
    # no reason to hand an unauthenticated visitor a full endpoint map.
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url="/redoc" if settings.environment == "development" else None,
    openapi_url="/openapi.json" if settings.environment == "development" else None,
)

# --- Middleware --------------------------------------------------------
# Order matters: Starlette applies middleware outer-to-inner in the order
# added, so the last one added runs closest to the route handler.

if getattr(settings, "trusted_hosts", None):
    # Rejects requests with a spoofed Host header before they reach any
    # route - cheap defense against host-header-based cache poisoning /
    # password-reset-link poisoning if this is ever fronted by a cache.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.effective_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compresses JSON/text responses over ~500 bytes - meaningful for the
# paginated media/album list endpoints without touching binary media
# streaming (Drive bytes are proxied through separate stream/download
# routes and typically already compressed formats, so this doesn't
# double-compress them).
app.add_middleware(GZipMiddleware, minimum_size=500)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Tags every request with a short id and logs method/path/status/timing.

    This is what turns a bare "500 Internal Server Error" in the browser
    network tab into something you can actually correlate with a specific
    backend traceback line in the terminal - the id is echoed back as a
    response header, so it can be copied straight out of devtools.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # Let the registered exception handlers deal with the actual
            # response; just make sure the id is logged before it propagates.
            logger.error("request_id=%s failed before a response was produced", request_id)
            raise
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response


app.add_middleware(RequestContextMiddleware)


# --- Exception handlers -------------------------------------------------

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # ApiError instances put a {code, message} dict in .detail already;
    # anything else (a plain HTTPException) gets wrapped the same way so the
    # frontend only ever has to handle one error shape.
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        body = {"success": False, "error": detail}
    else:
        body = {"success": False, "error": {"code": "HTTP_ERROR", "message": str(detail)}}
    # Forward any headers the raiser attached (e.g. ApiError(416, ...) sets
    # Content-Range so the client knows the real file size) - previously
    # dropped here even when present on the exception.
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"field": " → ".join(str(part) for part in err.get("loc", [])), "message": err.get("msg", "")}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request data.",
                "details": errors,
            },
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    # Never leak stack traces / internals to the client (Section 25) - but
    # do log the request_id so this specific failure is greppable from the
    # X-Request-ID header the client actually received.
    logger.exception("request_id=%s unhandled exception on %s %s", request_id, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
            },
        },
    )


# --- Routers --------------------------------------------------------------

app.include_router(auth_router)
app.include_router(admin_clients_router)
app.include_router(admin_albums_router)
app.include_router(admin_dashboard_router)
app.include_router(admin_activity_router)
app.include_router(admin_media_router)
app.include_router(admin_storage_router)
app.include_router(admin_settings_router)
app.include_router(admin_download_jobs_router)
app.include_router(admin_downloads_router)
app.include_router(client_gallery_router)
app.include_router(client_download_jobs_router)
# app.include_router(client_media_router)  # <-- uncomment once confirmed/added


@app.get("/api/health")
def health():
    return {
        "success": True,
        "data": {
            "status": "ok",
            # Surfaced here (not just in startup logs) so it's checkable by
            # uptime monitors / ops tooling without needing log access.
            "ffmpeg_available": is_ffmpeg_available(),
        },
    }