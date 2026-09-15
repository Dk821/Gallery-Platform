# Architecture — LoveStory PH (Private Wedding Gallery Platform)

## Overview

A private gallery platform for wedding photographers to manage clients, albums, and media. Two interfaces: an **admin panel** for the studio and a **client gallery** for viewing/downloading photos and videos.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite 5, React Router 6 |
| Backend | Python 3.12, FastAPI 0.115, Uvicorn |
| Database | MySQL 8 (via SQLAlchemy 2 + PyMySQL) |
| Migrations | Alembic |
| Storage | Google Drive v3 API (service account) |
| Video Processing | FFmpeg (system binary) |
| Image Processing | Pillow |
| Auth | Argon2 (passwords), itsdangerous (admin tokens), Fernet (reversible encryption) |
| Testing | pytest, httpx, TestClient |

---

## Directory Structure

```
final v2/
├── backend/
│   ├── app/
│   │   ├── api/              # Route handlers (deps.py auth deps, presenters.py response mapping)
│   │   │   ├── auth.py
│   │   │   ├── deps.py
│   │   │   ├── presenters.py
│   │   │   ├── media_streaming.py
│   │   │   ├── admin_*.py    # Admin endpoints (clients, albums, media, dashboard, activity, storage, downloads, settings)
│   │   │   └── client_*.py   # Client endpoints (gallery, download jobs)
│   │   ├── config/           # pydantic-settings (.env loader)
│   │   ├── database/         # SQLAlchemy engine, session, Base
│   │   ├── models/           # 10 ORM models + mixins
│   │   ├── schemas/          # Pydantic request/response models (auth, client, album, media, download_job, studio_settings, errors, pagination)
│   │   ├── security/         # Password hashing (Argon2), session tokens, reversible encryption (Fernet)
│   │   ├── services/         # Business logic layer (circuit_breaker, storage_provider, folder_naming, retry, timeouts, upload_concurrency, upload_logging, media_validation, disk_service)
│   │   ├── workers/          # Thumbnail generation (PIL + FFmpeg)
│   │   ├── main.py           # App factory, lifespan, middleware, error envelope
│   │   ├── create_admin.py   # First admin bootstrap (python -m app.create_admin)
│   │   ├── reconcile_orphans.py      # Cron: dry-run/--apply Drive orphan cleanup
│   │   └── cleanup_download_jobs.py  # Cron: expired ZIP cleanup
│   ├── scripts/              # check_env.py (env sanity gate), generate_drive_refresh_token.py
│   ├── alembic/              # Database migrations
│   ├── .env                  # Backend config (secrets - not committed)
│   ├── .env.example          # Config template (committed)
│   └── tests/                # 18 pytest test files + conftest/fakes
├── frontend/
│   ├── .env.example          # VITE_API_BASE_URL - only needed when frontend/backend
│   │                         # are on different origins (mirrors CROSS_SITE_FRONTEND)
│   ├── .env                  # Local override (not committed)
│   └── src/
│       ├── components/       # Shared UI (AdminLayout, Sidebar, Lightbox, Modals)
│       ├── pages/            # Admin + Client pages
│       ├── services/         # Typed API client (auth, admin, gallery)
│       ├── styles/           # Plain CSS: index.css + admin.css + gallery.css
│       ├── utils/            # Formatters (format.ts)
│       ├── vite-env.d.ts     # ImportMetaEnv typing for VITE_ vars
│       ├── App.tsx           # Route definitions
│       └── main.tsx          # Entry point
├── ARCHITECTURE.md           # This file
└── README.md                 # Setup guide and project overview
```

---

## Architectural Patterns

### Layered Architecture

```
HTTP Request
    ↓
API Routes (app/api/)       ← Thin HTTP shell, input validation only
    ↓
Services (app/services/)    ← All business logic, Drive interaction, analytics
    ↓
Models (app/models/)        ← SQLAlchemy ORM
    ↓
Google Drive                ← Media storage (never exposed to frontend)
```

### Storage Abstraction

`StorageService` is an abstract base class. Only `google_drive_service.py` imports the Google SDK. Routes receive the storage backend via the `get_storage_service()` dependency (`app/services/storage_provider.py`), which builds a single process-wide `GoogleDriveStorage` instance. The test suite overrides that dependency with `FakeStorageService` (in-memory). Storage is fully mockable.

Folder naming conventions for Drive (client folders, album subfolders) are handled by `app/services/folder_naming.py`, keeping Google Drive path logic separate from the storage service itself.

### Error Envelope

All API responses follow a consistent format:

```json
// Success
{ "success": true, "data": { ... } }

// Error
{ "success": false, "error": { "code": "NOT_FOUND", "message": "..." } }
```

Headers attached to the raised error are forwarded on the response (e.g. `ApiError(416, ...)` sets
`Content-Range` so the client knows the real file size).

### Pagination

`build_page()` returns `{ items, page, limit, total, has_more }` with `limit` capped at 200.

### Middleware & Boot Sequence

Middleware stack (outer → inner): `TrustedHostMiddleware` (rejects spoofed Host headers), CORS, `GZipMiddleware`
(compresses JSON responses ≥ 500 bytes; binary stream/download routes are untouched), and
`RequestContextMiddleware`, which tags every request with a short `request_id`, echoes it as the
`X-Request-ID` response header, and logs `method/path/status/duration_ms` so a browser "500" can be
correlated with an exact backend traceback line (`app/main.py`).

`lifespan` startup checks (all in `app/main.py`):
- **FFmpeg probe** — verifies `ffmpeg` is on PATH once at boot and logs loudly if not (video posters
  won't be generated; see `SYSTEM_REQUIREMENTS.md`).
- **Cookie config sanity** — warns when `CROSS_SITE_FRONTEND=true` while `ENVIRONMENT=development`,
  because Secure (SameSite=None-required) cookies are silently rejected by browsers over plain HTTP.
- **Orphaned upload sweep** — every `uploading`/`queued` upload session left by a previous process is
  marked `failed` (`UPLOAD_STALE`), so the UI never re-hydrates a dead in-flight upload after a restart.

SQL query/parameter logging (`SQL_ECHO=true`) is opt-in and off by default because bound parameters
include session token hashes and encrypted password blobs.

---

## Database Schema (10 Tables)

| Table | Purpose |
|---|---|
| `admins` | Admin/staff users (email, Argon2 password hash, status) |
| `clients` | Client accounts with `client_uuid` (public galleryId), Drive folder ID, encrypted password copies |
| `albums` | Albums per client, with expiry (`expires_at`), Drive folder |
| `media` | Photo/video records with Google Drive file IDs, metadata, type |
| `sessions` | Client server-side sessions (SHA-256 hashed tokens, expiry, download password verification) |
| `upload_sessions` | Idempotency ledger for uploads (admin_id, upload_id) |
| `download_jobs` | Background ZIP download jobs with status lifecycle |
| `download_records` | Download analytics (per client, per album) |
| `audit_logs` | Unified activity feed (admin + client actions) |
| `studio_settings` | Single-row (`id=1`) studio-wide config: studio name/contact email, min client password length, download-link TTL hours. Lazily created on first read - see `studio_settings_service.py` |

Shared mixins: `IdMixin` (BigInteger PK), `TimestampMixin` (created_at/updated_at).

---

## API Endpoints

### Auth (`/api/auth`)
| Method | Path | Description |
|---|---|---|
| POST | `/auth/admin/login` | Admin login → HttpOnly cookie |
| POST | `/auth/client/login` | Client login → HttpOnly cookie |
| POST | `/auth/logout` | Clear session |
| GET | `/auth/me` | Current user info |

### Admin (`/api/admin/*`) — Cookie auth required
| Area | Endpoints |
|---|---|
| Clients | CRUD, view passwords, change password, change download password, disable/enable, regenerate gallery ID |
| Albums | CRUD, filter by client, list media, selection summary |
| Media | Resumable upload, upload status + upload-sessions list, bulk delete/move, stream, download, thumbnail, orphans |
| Dashboard | Stats summary |
| Activity | Audit log feed |
| Storage | Google Drive quota |
| Downloads | Analytics, download job management |
| Settings | `GET /settings` (studio profile + policy + own account), `PUT /settings/profile` (studio name/contact email), `PUT /settings/security` (min client password length, download-link TTL), `POST /settings/change-password` (admin's own password, requires current password) |

### Client (`/api/client/*`) — Cookie auth + galleryId scoping
| Area | Endpoints |
|---|---|
| Gallery | Gallery info, album listing, album detail |
| Media | List, detail, stream, thumbnail, download |
| Downloads | ZIP job creation, password verification, file download |

### Shared
| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check (reports FFmpeg availability) |

---

## Authentication & Security

### Admin Auth
- Login → `URLSafeTimedSerializer` token → HttpOnly cookie `admin_session`
- TTL configurable via `SESSION_TTL_MINUTES` (default 1440)
- Passwords: Argon2 hash + Fernet reversible copy (for admin "view password" feature)
- Admin's own password: self-service change at `POST /api/admin/settings/change-password`, requires the current password (unlike an admin resetting a client's password) - `app/services/admin_service.py`

### Client Auth
- Login → random 256-bit token; only **SHA-256 hash** stored in `sessions`
- Raw token in HttpOnly cookie `client_session`
- Each client scoped to their own `galleryId` — ownership enforced on every route

### Download Password Gate
- If client has a `download_password_hash`, downloads require `download_password_verified_at` flag on the session

### Upload Hardening
- Magic-byte validation + ISO-BMFF box-walk for mp4/mov (`app/services/media_validation.py`)
- `DiskReservationTracker` for free disk checks (`app/services/disk_service.py`)
- Retry with exponential backoff on `{429, 500, 502, 503, 504}` (`app/services/retry.py` — retryable
  statuses only; auth/not-found/permission errors are never retried)
- Per-request and per-upload concurrency limiters (`BoundedSemaphore`, `UploadConcurrencyLimiter`)
- Max upload size: 10 GB (configurable)
- **Disk spooling**: every upload is fully spooled to this machine's temp disk before being relayed
  to Drive (temp file deleted once the request finishes) - this is why the free-disk floor below
  matters with several files in flight at once
- Structured upload log events via `upload_logging.py`, with a forbidden-keys guard that strips
  passwords/tokens/secrets from any logged field
- **Client-side throttling**: the Uploads page (`frontend/src/pages/Uploads.tsx`) caps itself to
  `MAX_CONCURRENT_UPLOADS = 4` simultaneous transfers via a scheduler `useEffect` - queued items are
  started only as active slots free up, instead of firing every selected file at once. This exists
  specifically to support large batch uploads (e.g. ~250 files / ~50GB) without overwhelming the
  server's own admission control below.
- Server admission control is tuned to match: `UPLOAD_MAX_CONCURRENT=4`,
  `UPLOAD_MAX_CONCURRENT_REQUESTS=8`, `UPLOAD_QUEUE_WAIT_SECONDS=300`, `UPLOAD_MIN_FREE_DISK_GB=5`,
  `UPLOAD_CHUNK_SIZE_MB=8`, `UPLOAD_CHUNK_TIMEOUT=120`, `UPLOAD_SESSION_TIMEOUT=7200` (all in `backend/.env`)
- **Socket-level timeouts**: every `httplib2.Http()` used to talk to Google Drive (metadata client,
  resumable upload, download/streaming) is constructed with `timeout=settings.upload_chunk_timeout` -
  httplib2 has no default socket timeout, so without this a single hung TLS handshake (e.g. an
  antivirus/network SSL interception mangling the handshake, seen as `SSL: WRONG_VERSION_NUMBER`) could
  block a worker thread forever instead of failing cleanly. `download()`'s chunk loop is additionally
  wrapped in `run_with_timeout` (`app/services/timeout_utils.py`), mirroring what `upload()` already did.
- **Circuit breaker** (`app/services/circuit_breaker.py`): a process-wide breaker wraps the shared
  `_retry()` path in `google_drive_service.py`. After 3 consecutive pure transport/connectivity
  failures it "opens" and fails fast (no network attempt) for a 20s cooldown, then lets one trial call
  through - prevents a burst of failing Drive calls from exhausting the request-handling thread pool.
  Only transport failures count against it (`httplib2.HttpLib2Error`, `OSError`/`ssl.SSLError`, the
  httplib2 cleanup-bug `AttributeError`); application-level Drive errors (`HttpError`, `RefreshError`)
  don't, since they prove connectivity is fine.

---

## Frontend Architecture

### Routing

```
/admin/login              → Admin login
/admin/dashboard          → Dashboard with area chart
/admin/activity           → Audit log feed
/admin/clients            → Client CRUD
/admin/albums             → Album CRUD
/admin/albums/:albumId    → Album media management
/admin/uploads            → Drag-drop upload queue
/admin/downloads          → Download job monitoring
/admin/storage            → Drive quota usage
/admin/settings           → Studio profile, admin account (change password), security & download policy

/gallery/:galleryId              → Client gallery (password gate)
/gallery/:galleryId/view         → All media view
/gallery/:galleryId/view/:albumId → Single album view
```

### API Client (`services/`)
- `api.ts` — Fetch wrapper with `ApiError`, typed interfaces (`Page`, `MediaItem`, `DownloadJob`);
  exports `API_BASE_URL`, read from `VITE_API_BASE_URL` (frontend `.env`) and prefixed onto every
  request - empty by default (same-origin, today's behavior), set only when the frontend is deployed
  on a different origin than the backend
- `auth.ts` — Login/me/logout calls
- `admin.ts` — All admin endpoints (incl. `getSettings`/`updateStudioProfile`/`updateSecurityPolicy`/`changeAdminPassword`)
- `gallery.ts` — All client-facing endpoints

### Key Components
- `AdminLayout` + `Sidebar` — Admin shell
- `ClientNav` — Gallery navigation
- `MediaLightbox` — Filmstrip + zoom + keyboard nav
- `DownloadJobModal` — Creates ZIP job, polls every 1.5s until completion
- `DownloadPasswordModal` — Gate for download-protected galleries

### Styling
- Plain CSS (no Tailwind/UI framework) split across `index.css` (global) + `styles/admin.css` / `styles/gallery.css` per view
- Wedding typography: Alex Brush, Cormorant Garamond, Montserrat (Google Fonts, imported at the top of the per-view stylesheets)

---

## Background Jobs

No task queue (by design — single-VPS, single-process). Background work uses FastAPI `BackgroundTasks`:

| Job | Mechanism | Notes |
|---|---|---|
| ZIP download creation | `BackgroundTasks` + threading | Snaps media list, prefetches files concurrently (`ZIP_JOB_PARALLEL_DOWNLOADS=4`), builds ZIP incrementally, TTL from `studio_settings.download_link_ttl_hours` (admin-configurable, default 24h) |
| Download analytics recording | Starlette `BackgroundTask` | Own DB session, non-blocking |
| Thumbnail generation | Inline (synchronous) | PIL for images, FFmpeg for video posters |
| Orphan reconciliation | Cron script (`python -m app.reconcile_orphans --apply`) | Deletes Drive files with no DB row after `ORPHAN_FILE_GRACE_PERIOD_HOURS` (default 48h) grace; dry run without `--apply` |
| Expired job cleanup | Cron script (`python -m app.cleanup_download_jobs`) | Removes stale ZIPs; flips rows to `expired` |
| Stale upload sweep | On app boot (`lifespan`) | Marks `uploading`/`queued` sessions from a dead process as `failed` (`UPLOAD_STALE`) |

---

## Third-Party Integrations

| Service | Purpose |
|---|---|
| Google Drive v3 API | Authoritative media storage (folders per client/album) |
| FFmpeg | Video poster frame extraction (t=1.0s) |
| Google Fonts | Wedding-styled typography |
| MySQL 8 | Primary database |

---

## Deployment

- **Backend**: `uvicorn app.main:app` with Alembic migrations (`alembic upgrade head`)
- **Frontend**: `npm run build` → static files served from same origin
- **First admin**: `python -m app.create_admin` (password must be exactly 8 chars)
- **Pre-deploy sanity gate**: `python scripts/check_env.py` (verifies DB connectivity, Drive token/root
  folder, writable `ZIP_TEMP_DIR`, ffmpeg on PATH; exits nonzero on any FAIL)
- **Drive token refresh**: `python scripts/generate_drive_refresh_token.py` (re-runs the OAuth consent
  flow after `invalid_grant: Token has been expired or revoked`)
- **Cron jobs**: `python -m app.cleanup_download_jobs`, `python -m app.reconcile_orphans --apply`
- **Dev proxy**: Vite proxies `/api` → `http://localhost:8000`

---

## Testing

- 18 pytest test files in `backend/tests/` (+ shared `conftest.py` / `fakes.py`)
- SQLite in-memory database + `FakeStorageService` (no real Drive calls)
- Coverage: auth, authorization, client search, admin management, album expiry, media management, bulk ops, download jobs/analytics, upload hardening, thumbnails/streaming, dashboard, storage integration, Drive folder naming, resumable uploads, FFmpeg availability, httplib2 cleanup-bug regression, studio settings/security policy
- No frontend tests

---

## Notable Design Decisions

1. **No task queue** — Deliberate choice for single-VPS simplicity; ZIP jobs run in-process via `BackgroundTasks`
2. **Google Drive as storage** — Media never lives long-term on the app server's disk; uploads are
   spooled to temp disk only while being relayed to Drive (and ZIPs while being built), then deleted.
   Only `google_drive_service.py` imports the Drive SDK
3. **Dual password system** — Login password (Argon2) + optional download password (separate gate)
4. **Client-scoped routes** — Every client route validates `galleryId` ownership; no cross-tenant access possible
5. **Upload idempotency** — `upload_sessions` table prevents duplicate uploads on retry
6. **Orphan reconciliation** — Background cron catches Drive files that lost their DB row
7. **Album expiry** — Enforced only on client routes; admins always see expired albums
8. **Studio settings as a singleton row** — `studio_settings` always has exactly one row (`id=1`),
   created lazily with defaults on first read rather than seeded by its migration, so a fresh install
   and an upgraded install behave identically with no data-seed step to keep in sync
9. **Circuit breaker over raw retries** — Retry-with-backoff alone couldn't stop a burst of failing
   Drive connectivity calls from exhausting the request thread pool; a process-wide circuit breaker
   (`circuit_breaker.py`) fails fast during a cooldown window instead, and is deliberately scoped to
   transport-layer failures only, not application-level Drive errors
