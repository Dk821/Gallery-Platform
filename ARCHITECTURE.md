# Architecture — LoveStory PH (Private Wedding Gallery Platform)

## Overview

A private gallery platform for wedding photographers to manage clients, albums, and media. It is **multi-studio**: one FastAPI app and one MySQL database serve many studios, each isolated from the others. Three interfaces live in one React app: a **Super Admin console** (`/super-admin/*`, platform owner), a **studio admin panel** (`/admin/*`) and a **client gallery** (`/gallery/*`) for viewing/downloading photos and videos. Files live in Cloudflare R2.

> **v0.5 (31/10/2026):** storage is selectable with `STORAGE_PROVIDER` — **Google Drive (default)** or Cloudflare R2 — behind the same `StorageService` seam, with one folder model (`studios/{name}-{id}/albums/{client}_{albumId}/…`; real nested folders on Drive). Where this document says R2/presigned/bucket, that is the `r2` provider; see `README.md` §4 and `STORAGE_STRUCTURE.md`.

Companion documents: `MULTI_STUDIO.md` (tenancy, roles, quotas, super admin API, migration runbook), `STORAGE_STRUCTURE.md` (the R2 key layout), `Upload-Pipeline.md` (direct-to-R2 uploads).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite 8, React Router 7 |
| Backend | Python 3.12, FastAPI 0.115, Uvicorn |
| Database | MySQL 8 (via SQLAlchemy 2 + PyMySQL) |
| Migrations | Alembic |
| Storage | Cloudflare R2 (S3-compatible, boto3; browsers upload with presigned URLs) |
| Video Processing | FFmpeg (system binary — **optional**, see below) |
| Image Processing | Pillow (server-side fallbacks) + HTML5 Canvas/WebP (client-side) |
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
│   │   │   ├── admin_*.py    # Studio admin endpoints (clients, albums, media, dashboard, activity, storage, downloads, settings)
│   │   │   ├── client_*.py   # Client endpoints (gallery, download jobs, wishlist)
│   │   │   ├── super_admin.py     # /api/super-admin/* (studios, quotas, the studio's single login, logos, platform audit log)
│   │   │   ├── studio.py          # /api/studio/* (the studio's own profile, usage, audit log)
│   │   │   └── studio_branding.py # GET /api/studios/{id}/logo (public logo image)
│   │   ├── config/           # pydantic-settings (.env loader)
│   │   ├── database/         # SQLAlchemy engine, session, Base
│   │   ├── models/           # 14 ORM models + mixins (incl. studios, platform_storage)
│   │   ├── schemas/          # Pydantic request/response models (auth, client, album, media, download_job, studio_settings, errors, pagination)
│   │   ├── security/         # Password hashing (Argon2), session tokens, reversible encryption (Fernet)
│   │   ├── services/         # Business logic layer (activity_service, admin_service, album_service, audit_service, auth_service, client_service, comment_service, dashboard_service, disk_service, download_analytics_service, download_job_service, folder_naming, media_aggregates, media_service, media_validation, orphan_reconciliation, quota_service, quota_reconciliation, r2_storage, storage_analytics_service, storage_paths, storage_provider, storage_service, studio_service, studio_logo_service, studio_settings_service, wishlist_service, ... plus the dormant google_drive_service / circuit_breaker / retry / thumbnail_folder_migration from the Drive era)
│   │   ├── workers/          # Thumbnail generation (PIL + FFmpeg)
│   │   ├── main.py           # App factory, lifespan, middleware, error envelope
│   │   ├── create_super_admin.py     # Platform owner bootstrap (python -m app.create_super_admin)
│   │   ├── create_admin.py           # Legacy single-studio admin bootstrap
│   │   ├── legacy_to_studio.py       # One-off: map pre-multi-studio rows into a studio (dry-run by default)
│   │   ├── consolidate_studio_logins.py  # One-off: report/fix studios with more than one login (one login per studio)
│   │   ├── reconcile_quota.py        # Cron: recompute / repair studio usage counters
│   │   ├── reconcile_orphans.py      # Cron: dry-run/--apply cleanup of objects from unfinished uploads
│   │   ├── cleanup_download_jobs.py  # Cron: expired ZIP cleanup
│   │   └── migrate_thumbnail_folders.py  # Legacy (Drive era): "Cover Images" → "Thumbnails" rename
│   ├── scripts/              # check_env.py (env sanity gate), check_r2.py (R2 access test)
│   ├── alembic/              # Database migrations
│   ├── .env                  # Backend config (secrets - not committed)
│   ├── .env.example          # Config template (committed)
│   └── tests/                # 27 pytest test files + conftest/fakes/ms_helpers
├── frontend/
│   ├── .env.example          # VITE_API_BASE_URL - API base for cross-origin builds
│   │                         #   (VITE_API_URL is only needed to enable the dev proxy)
│   ├── .env                  # Local override (not committed)
│   ├── index.html            # SPA entry: <head> (title, description, favicon -> /ls-logo.png,
│   │                         #   Google Fonts) + #root mount + the /src/main.tsx module script
│   ├── vite.config.ts        # React plugin + /api dev proxy to VITE_API_URL
│   ├── vercel.json           # Hosting config: SPA rewrite, /api proxy, security headers,
│   │                         #   robots.txt/sitemap.xml content-type + cache headers
│   ├── public/               # Copied verbatim to dist/ (never hashed, never bundled)
│   │   ├── ls-logo.png       # The platform logo — favicon and home mark (each studio's own logo is uploaded to R2)
│   │   ├── light-ls-logo.png # Light-background variant of the logo
│   │   ├── favicon.svg       # Legacy heart-and-lens mark (superseded by ls-logo.png)
│   │   ├── images/           # album-bg.webp, album-hero.webp (landing-page backdrops)
│   │   ├── robots.txt        # Allows /, blocks /admin, /api, /.git, /.env*
│   │   └── sitemap.xml       # Canonical public URLs (the site root + /gallery)
│   └── src/
│       ├── components/       # Shared UI (AdminLayout, Sidebar, StudioBrandMark, Lightbox, Modals, GlobalUploadBadge,
│       │   │                     WishlistHeart, PoweredBy credit line, RequireAdmin route guard)
│       │   └── superadmin/   # Console UI (SuperAdminLayout, RequireSuperAdmin, Modal, ResetPasswordModal, SecretModal,
│       │                     StudioAdminsPanel, StudioLogoField, StudioProfileForm, StudioQuotaCard, Toast, ...)
│       ├── contexts/         # React Contexts (UploadContext - global persistent upload queue)
│       ├── hooks/            # useWishlist (optimistic wishlist state), useStudioBranding (studio name + logo)
│       ├── pages/            # Admin + Client pages (incl. BookView - the client-facing page-turning reader)
│       │   └── superadmin/   # Console pages: Dashboard, Studios, StudioDetail, AuditLogs, Settings, NotFound
│       ├── services/         # Typed API client (auth, admin, gallery, superAdmin, studioBranding)
│       ├── styles/           # Plain CSS: index.css + admin.css + gallery.css + book-view.css + super-admin.css (`sa-` prefixed)
│       ├── utils/            # format.ts, photoThumbnail.ts, videoPoster.ts
│       ├── vite-env.d.ts     # ImportMetaEnv typing for VITE_ vars
│       ├── App.tsx           # Route definitions
│       └── main.tsx          # Entry point
├── ARCHITECTURE.md           # This file
├── MULTI_STUDIO.md           # Tenancy, roles, quotas, super admin API, migration runbook
├── STORAGE_STRUCTURE.md      # Where each file lives in R2
├── Upload-Pipeline.md        # Deep dive on the direct-to-R2 upload pipeline
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
Services (app/services/)    ← All business logic, storage interaction, quota, analytics
    ↓
Models (app/models/)        ← SQLAlchemy ORM
    ↓
Cloudflare R2               ← Media storage (never exposed to the frontend except
                              as short-lived presigned upload URLs)
```

### Storage Abstraction

`StorageService` is an abstract base class (`storage_service.py`). `r2_storage.py` (`R2Storage`, boto3) is the only implementation in use; routes receive it via the `get_storage_service()` dependency (`app/services/storage_provider.py`), which builds a single process-wide instance. The test suite overrides that dependency with `FakeStorageService` (in-memory) or injects a fake S3 client into `R2Storage`, so storage is fully mockable. `google_drive_service.py` is kept in the repository but is dormant: nothing selects it and no Drive configuration is read.

R2 objects are addressed by key, and every key starts with the studio's own readable folder, `studios/{studio-name}-{studio_id}/` (tenant isolation; see `STORAGE_STRUCTURE.md`). The folder is built once by `app/services/storage_paths.py` when the studio is created, saved in `studios.storage_prefix` and never changed, so renaming a studio never moves files; studios that predate it keep `studios/{id}/`. Four small seams in the interface let key-addressed providers work without special cases in the services: `object_key_for()` (the server chooses an upload's key), `owns_object()` (refuses any key outside the calling studio's folder), `tenant_root_folder()` (parent for a studio's client folders) and `album_originals_folder()` (`{studio folder}/albums/{client-name}_{album_id}`, where an album's originals go). Providers that cannot do this keep the default behaviour. `put_bytes()` stores small server-generated objects such as studio logos.

Folder naming conventions (`{client}_C_{uid}`, `{album}_A_{uid}`) are handled by `app/services/folder_naming.py`. On R2 a "folder" is only a key prefix: renaming is a no-op (the readable name lives in the database) and album membership of an object is a database fact.

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

## Database Schema (14 Tables)

| Table | Purpose |
|---|---|
| `studios` | One row per photography studio: name, `slug` (the name in client gallery links, unique, kept when the studio is renamed), contact, `logo_url` (path of the uploaded logo), `storage_prefix` (its permanent folder in R2, e.g. `studios/acme-photo-1`; NULL = legacy `studios/{id}`), brand colour, `status` (`active`/`suspended`), `quota_bytes`, `used_bytes`, `reserved_bytes`. See `MULTI_STUDIO.md` |
| `platform_storage` | Single row (`id=1`): platform-wide `used_bytes` / `reserved_bytes`, checked against `PLATFORM_CAPACITY_BYTES` |
| `admins` | Admin users (email, Argon2 password hash, status) plus `role` (`super_admin` / `studio_admin`), `studio_id` and `session_version` (bumped on password change/reset to revoke old cookies) |
| `clients` | Client accounts with `client_uuid` (public galleryId), `studio_id`, storage folder id (an R2 key prefix, `studios/{studio-name}-{id}/{name}_C_{uid}`), a random `folder_uid` folder-name suffix, encrypted password copies, and `thumbnail_folder_id` (the client's dedicated `Thumbnails` prefix - holding every item thumbnail; nullable, created lazily, never exposed by any API). `password_hash` is **nullable**: a `NULL` gallery password means the gallery has no password prompt (see *Client Auth*) |
| `albums` | Albums per client, with expiry (`expires_at`), a storage folder id, and the two Book View presentation columns: `book_view_enabled` (boolean, default `false` - per-album opt-in to the client-facing page-turning reader) and `book_layout` (`square` / `portrait` / `landscape`, default `landscape` - the aspect ratio of the spread) |
| `media` | Photo/video records with `storage_key` / `storage_provider` (R2 object key), metadata, type, and `sort_order` (1-based position inside the album's book order; ordering is `sort_order ASC, id ASC`, and uploads/moves append at `MAX(sort_order)+1`) |
| `sessions` | Client server-side sessions (SHA-256 hashed tokens, expiry, download password verification) |
| `media_wishlists` | A client's favourites: `(client_id, media_id)` with `UNIQUE(client_id, media_id)` and an index on `media_id`; both FKs `ON DELETE CASCADE`. Pure database relationship - nothing is ever copied in storage |
| `album_comments` | Client page notes on a Book View album: 1-based `page_number`, free text (≤2000 chars), `status` (`open` / `resolved`), and an optional `media_id` (`ON DELETE SET NULL`, so the note survives its photo). `UNIQUE(client_id, album_id, page_number)` makes saving a page an upsert; the album/client FKs cascade |
| `upload_sessions` | Idempotency ledger for uploads (admin_id, upload_id) plus the quota reservation (`reserved_bytes`, `reservation_status` none/reserved/committed/released) |
| `download_jobs` | Background ZIP download jobs with status lifecycle |
| `download_records` | Download analytics (per client, per album) |
| `audit_logs` | Unified activity feed (admin + client actions) with `studio_id`, `actor_role` and sanitised `metadata` |
| `studio_settings` | One row per studio (`studio_id` unique): studio name/contact email, min client password length, download-link TTL hours. Lazily created on first read - see `studio_settings_service.py` |

Every studio-owned table (`clients`, `albums`, `media`, `upload_sessions`, `download_jobs`, `download_records`, `studio_settings`) carries an indexed `studio_id`, and every service query filters on it.

Shared mixins: `IdMixin` (BigInteger PK), `TimestampMixin` (created_at/updated_at).

---

## API Endpoints

### Auth (`/api/auth`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/admin/login` | Admin login → HttpOnly cookie; the response carries `role` (`super_admin` / `studio_admin`) so the app knows which area to open |
| POST | `/api/auth/client/login` | Client login → HttpOnly cookie |
| POST | `/api/auth/logout` | Clear session |
| GET | `/api/auth/me` | Current user info |

### Super admin (`/api/super-admin/*`) — `super_admin` role only (else `403 SUPER_ADMIN_REQUIRED`)
Studios (list/create with the studio's one login and optional logo, detail, edit, suspend/reactivate, quota, usage), studio logo upload/remove (`POST`/`DELETE /studios/{id}/logo`), deleting a suspended studio (`DELETE /studios/{id}`; empty by default, or with all its data via `?delete_data=true&confirm_name=`), the studio's single login (edit name, change email, reset password, disable/enable — one login per studio, enforced by `studio_service` and the unique index `uq_admins_studio_id`; `POST /studios/{id}/admins` is recovery-only for a studio with no login; there is no delete-login endpoint), platform stats, the platform audit log and the super admin's own `POST /change-password`. A super admin can **not** browse a studio's clients/albums/media. Full table in `MULTI_STUDIO.md` §4.

### Studio profile (`/api/studio/*`) and public logo
`GET/PUT /api/studio/profile`, `GET /api/studio/usage`, `GET /api/studio/audit-logs` — always scoped to the logged-in studio admin's own studio. `GET /api/studios/{id}/logo?v=…` is public (no login) and serves the studio's uploaded logo with a one-year immutable cache; the `v` hash changes on every upload.

### Admin (`/api/admin/*`) — Cookie auth required (`studio_admin` role; scoped to the admin's own studio)
| Area | Endpoints |
|---|---|
| Clients | CRUD (gallery password optionally left blank → **passwordless** gallery), view passwords, change password, change/clear download password, disable/enable, regenerate gallery ID, client wishlist (`GET /{id}/wishlist?album_id=`, read-only) |
| Albums | CRUD, filter by client, list media (`?wishlist=all\|wishlisted\|not_wishlisted`, in book order), selection summary (same filter), wishlist counts (`GET /{id}/media/wishlist-counts`), drag-and-drop book order (`PUT /{id}/media/order` - the complete media-id list exactly once; `MEDIA_ORDER_INVALID` otherwise, page notes follow their photo). `PUT /{id}` also carries the Book View presentation flags (`book_view_enabled` - omit to leave untouched, explicit `false` to turn off - and `book_layout`) |
| Page notes | Per-album notes (`GET /{id}/comments`), resolve/reopen or correct the text (`PATCH /comments/{id}`, both fields optional), delete (`DELETE /comments/{id}`). Admin review deliberately ignores album expiry |
| Media | Direct upload session (`POST /upload-session` - reserves quota and returns a presigned R2 URL), thumbnail upload (`POST /upload-session/{id}/thumbnail`), completion confirmation (`POST /upload-complete`), progress ping (`POST /upload-progress/{id}`), abandonment (`POST /upload-session/{id}/abandon`), status (`GET /upload-status/{id}`), recent session list (`GET /upload-sessions`), bulk delete/move, stream, download, thumbnail, orphans |
| Dashboard | Stats summary |
| Activity | Audit log feed |
| Storage | The studio's own storage allocation (quota, used, remaining, reserved by uploads in progress — `studio_quota`), daily transfer, upload reliability, breakdowns. Server disk and the storage provider's account quota are platform matters and are not shown to studios |
| Downloads | Analytics, download job management |
| Settings | `GET /settings` (studio profile + policy + own account), `PUT /settings/profile` (studio name/contact email), `PUT /settings/security` (min client password length, download-link TTL), `POST /settings/change-password` (admin's own password, requires current password) |

### Public (no auth) — gallery door checks
| Area | Endpoints |
|---|---|
| Gallery access | `GET /api/client/gallery/access/{gallery_id}` → `{ requires_password, client_name }`; 404 `GALLERY_NOT_FOUND` for an unknown link id. Security-neutral "is there a door?" probe used by the client landing flow to decide between the password card and opening the gallery directly. The URL it answers for is a UUID the visitor already holds, so it leaks nothing else. |

### Client (`/api/client/*`) — Cookie auth + galleryId scoping
| Area | Endpoints |
|---|---|
| Gallery | Gallery info (incl. aggregated photo/video/byte totals), album listing, album detail (both album responses carry `book_view_enabled` / `book_layout` for the Book View entry point) |
| Media | List, detail (both carry `is_wishlisted`), selection summary, stream, thumbnail, download |
| Wishlist | `GET /wishlist` (paginated, optional `album_id`), `POST /wishlist/{media_id}`, `DELETE /wishlist/{media_id}` - both idempotent |
| Page notes | `GET /albums/{id}/comments` (own notes only), `POST /albums/{id}/comments` (upsert by `media_id` + `page_number` + `comment`), `PUT /comments/{id}`, `DELETE /comments/{id}` |
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
- **Optional gallery password**: a client created without one has `password_hash = NULL`
  and no password prompt. `POST /api/auth/client/login` accepts an empty/missing `password`
  and creates a normal server-side session, so every authenticated client page works
  unchanged. A gallery *with* a password always rejects a missing or wrong password
  (`INVALID_CREDENTIALS`) — an admin can remove a set password entirely via
  `POST /api/admin/clients/{id}/change-password` with `password: null`, which
  returns it to the passwordless state (mirrors the nullable download-password
  endpoint).
- **Pre-login probe**: `GET /api/client/gallery/access/{gallery_id}` (public, no auth)
  tells the landing page whether that gallery requires a password and returns the client
  name, so a passwordless gallery can open directly without flashing a form first. It
  never returns anything but that yes/no for a UUID the visitor already holds.

### Download Password Gate
- If client has a `download_password_hash`, downloads require `download_password_verified_at` flag on the session

### Upload Hardening (Direct-to-R2 Architecture)
Full detail: `Upload-Pipeline.md`.
- **Direct-to-R2 transfers**: the browser PUTs bytes straight to Cloudflare R2 with a short-lived presigned URL (`adminService.uploadToDrive` - the function keeps its old name - sends an `XMLHttpRequest` PUT). Large media payloads (up to 10 GB; single PUT limit 5 GiB) never touch the application server's disk or network interface.
- **Server-chosen object key**: `POST /api/admin/media/upload-session` makes the key `{studio folder}/albums/{client-name}_{album_id}/{media_uuid}` (for example `studios/acme-photo-1/albums/test-couple_25/<uuid>`) itself and signs the URL for that one key, content type and exact `Content-Length`. At completion the server uses the key it issued and ignores whatever the browser reports; `owns_object()` additionally refuses any key outside the studio's prefix.
- **Quota reservation before any URL is issued**: the declared size is reserved against the studio quota and the platform capacity in one conditional `UPDATE` (413 `STUDIO_QUOTA_EXCEEDED`, 507 `PLATFORM_CAPACITY_EXCEEDED`, 403 `STUDIO_SUSPENDED`); it becomes `used_bytes` on completion and is released on failure, cancel, stale sweep or deletion. See `MULTI_STUDIO.md` §5.
- **Bucket CORS**: the browser's PUT goes to R2, so the bucket needs a CORS rule allowing the frontend origin to `PUT` (README, Setup step 4). Without it uploads fail in the browser with a CORS error.
- **Client-Side WebP thumbnails**: Video poster frames (`videoPoster.ts`) and photo thumbnails (`photoThumbnail.ts`) are generated directly in the browser using HTML5 Canvas and WebP compression, then uploaded as small images to `POST /upload-session/{id}/thumbnail`. This eliminates heavy server-side video downloads and makes server-side FFmpeg optional. Both are stored under the client's `Thumbnails` prefix (`{studio folder}/{client folder}/Thumbnails/`), which counts toward no quota (see *Album Covers*).
- **One thumbnail prefix per client**: `media_service._ensure_thumbnail_folder` lazily creates (or reuses, via `clients.thumbnail_folder_id`) a single `Thumbnails` folder per client, so every video poster and photo thumbnail of that client lives in exactly one place.
- **Portable aggregates**: `media_aggregates.py` builds the photo/video count and byte-total expressions as `SUM(CASE WHEN ...)` rather than `count(...) FILTER (WHERE ...)`, because MySQL 8 has no `FILTER` clause — the `FILTER` spelling compiles and passes on the SQLite test suite, then dies with a 1064 on the real database.
- **Ranged-read signature validation**: Upon completion (`POST /api/admin/media/upload-complete`), the server asks R2 for the object's real size and reads only the initial header bytes (range 0..511 bytes) to perform magic-byte and ISO-BMFF box-walk checks (`app/services/media_validation.py`) without downloading the bulk file. A rejected object is deleted and its reservation released.
- **Idempotency ledger (`upload_sessions`)**: Each upload uses a UUID-based `upload_id` decoupled from filename to prevent `VARCHAR(100)` column overflow. Duplicate submissions of completed uploads safely return the existing `Media` record without re-uploading. The object key is recorded on the session as soon as the session opens, so `reconcile_orphans` can find the object of an upload whose confirmation never arrived.
- **Global queue persistence**: `UploadContext.tsx` maintains upload state globally across admin routes. Transfer progress is visible anywhere via `GlobalUploadBadge.tsx`. Memory is guarded by `withReleasedFile()`, which clears `File` object handles from React state upon upload completion or cancellation.
- **Client-side throttling**: The upload queue scheduler caps active transfers to `MAX_CONCURRENT_UPLOADS = 4` simultaneous connections to prevent network saturation.
- **Legacy Google Drive hardening (dormant)**: server admission control (`UPLOAD_MAX_CONCURRENT`, ...), per-call `httplib2` socket timeouts and the circuit breaker (`circuit_breaker.py`) existed for the Drive transport. They are only used by the dormant `google_drive_service.py`; their settings have no effect with R2.


### Album Covers
There is no stored cover image anywhere in the system, and nothing to manage: no cover column, no cover upload route, no cover in any API response.

- **Derived per album, at read time**: the gallery album grid fetches `GET /api/client/media?album_id={id}&page=1&limit=1` and uses the first item's `has_thumbnail` flag — if set, that item's thumbnail URL becomes the album cover; if not, the card renders its styled empty cover block (`wedding-album-card__cover-empty`) over the album's gradient background.
- **One request per album, deliberately**: photo/video counts and byte totals already ride on the album list (aggregated in SQL), so the first media page is the only extra fetch the grid makes — and it asks for a single item.
- **Replacing a removed feature**: an earlier design gave each *client* one automatic cover, built by the browser from the first eligible photo and stored as `cover.webp` beside the album folders. It was removed (Alembic `a5c7e3b1d9f8`) along with `cover_service.py` and the `POST /upload-session/{id}/cover` + `GET /gallery/cover` endpoints; `cover_drive_file_id` was dropped, while `cover_folder_id` was renamed to `thumbnail_folder_id` (value preserved). Album art now comes from the album's own first thumbnail, so there is no cover that can go stale or need reconciling.
- **Legacy bytes**: this concerned the Google Drive era only. `migrate_thumbnail_folders.py` (dry-run by default, `--apply` to write) renamed each legacy `Cover Images` Drive folder to `Thumbnails` and deleted the orphaned `cover.webp`. A fresh R2 installation never has either, so the script is not part of normal operation.

### Client Wishlist
A client can heart any photo or video; the state is one row in `media_wishlists`.
- **Security**: the client is only ever the one resolved from the session cookie - no client id is accepted from the path, query or body. Add/remove verify the chain *authenticated client → media → album → album.client* (and album expiry) and answer any mismatch, or an unknown id, with the same `MEDIA_FORBIDDEN` 403, so ids can't be probed.
- **Idempotent**: adding twice creates no duplicate row (checked, and enforced by the unique constraint for racing requests); only real changes are audited (`wishlist_added` / `wishlist_removed`, `user_type="client"`, `resource_type="media"`; the album is `media.album_id`).
- **No N+1**: `is_wishlisted` rides on every media list/detail response from one batched `IN` query per page; the admin filter is a correlated SQL `EXISTS`, and the filter tab counts are one aggregate query.
- **Admin** sees the client's picks read-only: filter tabs (`All media / Wishlist / Not wishlisted`) with counts on `/admin/albums/:albumId`, a heart badge on each wishlisted item, and `GET /api/admin/clients/{id}/wishlist`. "Select all" honours the active filter, since it feeds bulk delete/move/download.
- **Lifecycle**: deleting a media item removes its wishlist rows; moving it between the client's albums keeps them; media in an expired album is hidden from the client's wishlist like everything else.

### Book View (page-turning photo book)

A per-album presentation mode: the client opens the album as a 3D book with an
animated page turn instead of the normal grid (`frontend/src/pages/BookView.tsx`,
styles in `frontend/src/styles/book-view.css`).

- **Presentation flag, not a security boundary**: `albums.book_view_enabled`
  (default `false` — an admin must opt each album in) only decides whether the
  "Open as Book" button and the `/gallery/:galleryId/view/:albumId/book` route
  are useful. It never changes which media a client may read.
- **Entry point**: `AlbumView.tsx` renders the "Open as Book" button on the album
  stat bar only when `album.book_view_enabled` is set (the same `getAlbum`
  response the reader re-checks on entry, so the button and the page can never
  disagree). In the demo path (`test-uuid` / `preview` / `demo`, and the
  placeholder album/media data) the flag is baked in as `true` so the reader can
  be previewed without an admin switching it on first.
- **No new backend surface**: the page calls the same client endpoints the grid
  uses (`GET /api/client/albums/{id}` and `GET /api/client/media?album_id=`),
  so `get_album_for_client_or_403` and `check_album_not_expired` apply
  unchanged. The page re-checks the flag on entry and redirects to the plain
  album view when it is off, and back to the gallery entrance on
  `ALBUM_EXPIRED` / `ALBUM_FORBIDDEN`.
- **Admin controls**: the Edit Album dialog holds a Book View toggle plus an
  Album layout select (`square` / `portrait` / `landscape`, `albums.book_layout`,
  default `landscape` — sets the spread's aspect ratio via
  `data-book-layout`). Both save through the normal `PUT /api/admin/albums/{id}`.
  Two-state semantics: omit `book_view_enabled` to leave it alone, send an
  explicit `false` to turn it off.
- **Migrations**: `a1c7f4e2b9d6` (adds `book_view_enabled`), `711430f7f988`
  (adds `book_layout`). Both backfill existing rows with a `server_default`
  that is dropped afterwards, leaving the model's Python-side default as the
  single source of truth.
- **Presentation model**: one photo = one spread — the image is drawn across
  both pages and cropped in half by each page's `overflow: hidden`. A turning
  page is a chain of 12 nested hinged strips that curl (CSS `--p` / `--bend`
  driven by a `requestAnimationFrame` loop), so completion never depends on a
  browser event. Videos can't be split, so they turn as their poster and play
  in a single overlay across the whole spread.
- **Behaviour**: cover opens on its own after the first spread is decoded (or
  instantly under `prefers-reduced-motion`), autoplay at 5s/page (paused on
  video pages), arrow keys / swipe / click zones / scrubber navigation,
  preloading ±3/−2 pages, and reads in the studio's saved book order
  (`media.sort_order`, `id` as tie-break). Media is paged in at 200/page up to
  a 2000-item hard cap.

### Book Order (drag-and-drop page order)

The album's reading order, owned by the studio. `AlbumMedia.tsx` opens
`MediaOrderModal.tsx` ("Reorder book"): the whole album is loaded, reordered
with native drag & drop (up/down buttons cover touch and keyboard), and saved
in one request to `PUT /api/admin/albums/{id}/media/order`.

- **One source of truth**: `media.sort_order`, 1-based inside its album. Every
  album-scoped read (admin grid, client gallery default "Book Order", Book
  View) orders by `sort_order ASC, id ASC`; the id tie-break only matters for
  uploads that raced for the same value. Uploads and cross-album moves append
  at `MAX(sort_order)+1`, so deletions leave gaps instead of silently
  renumbering the book.
- **Complete list or nothing**: the request must name every media item in the
  album exactly once. A partial, duplicated, or foreign-album id list is
  rejected with `MEDIA_ORDER_INVALID` 400 - silently leaving the unseen items
  in place would produce an order the admin never saw. The write is audited as
  `media_reordered`.
- **Page notes follow their photo**: notes store a page number, not a media
  id, so `_renumber_page_notes` rewrites them from the new positions. Because
  `UNIQUE(client_id, album_id, page_number)` would reject a simple swap, it
  negates all page numbers in the album first, flushes, then assigns the
  finals. Notes whose media was deleted or moved away have no position and
  keep their stored page.
- **Migration**: `d3a7c9e1b5f6` adds the column and backfills existing albums
  by `created_at, id` so the pre-reorder chronological order is preserved.

### Page Notes (client feedback on book pages)

The client's one-line channel back to the studio, attached to the page they are
looking at (`BookCommentPanel.tsx` on the client, `AlbumCommentsModal.tsx` on
the admin side).

- **One note per page, upserted**: `UNIQUE(client_id, album_id, page_number)`
  means the sheet is always "write" or "edit", never a thread. Saving a page
  again edits the same row; `POST` reports `created` so the audit log can tell
  the two apart. A unique-key race between two identical submissions is caught
  (`IntegrityError` → rollback → re-read → update).
- **Ownership**: the client is only ever resolved from the session cookie. The
  media item must belong to that client's album (create requires `media_id` and
  a live `page_number` in `1..100000`); a foreign album/media answers
  `ALBUM_FORBIDDEN` / `MEDIA_FORBIDDEN`, and another client's note is an
  indistinguishable `COMMENT_NOT_FOUND`. Notes are readable only through their
  own album, so one client never sees another's feedback.
- **Review loop**: a client edit (or re-save) sets `status` back to `open`, so
  changed wording is re-reviewed. Admins resolve/reopen from the album list
  modal, which groups notes by page and shows the page thumbnail. Admin routes
  skip the album-expiry gate on purpose: feedback must stay reviewable after a
  gallery closes.
- **Text rules**: trimmed, non-blank, max 2000 characters. Status is limited to
  `open` / `resolved`.
- **Lifecycle**: deleting the photo keeps the note with `media_id = NULL` (the
  feedback still matters); deleting the album or client cascades. Every write
  is audited as `resource_type="album_comment"` with
  `comment_added` / `comment_updated` / `comment_deleted`.
- **Counts**: both album lists carry `comment_count` from one grouped subquery
  (admin: whole album; client: that client's notes), so the badges never N+1.
- **Client UX**: a note button in the Book View toolbar shows a dot when the
  page already has one; submitting saves and turns to the next page. Autoplay
  and keyboard page turns pause while the sheet is open.
- **Migration**: `9b3f82e6a7c4` (creates `album_comments` + its indexes).

---

## Frontend Architecture

### Routing

```
/                            → Home: platform logo + the two ways in (client gallery link, studio sign-in)
/admin/login              → Sign-in for super admins and studio admins (accepts ?redirect=<in-app-path>);
                            a super admin is sent on to /super-admin/dashboard
/admin/dashboard          → Dashboard with area chart
/admin/activity           → Audit log feed
/admin/clients            → Client CRUD
/admin/albums             → Album CRUD
/admin/albums/:albumId    → Album media management
/admin/uploads            → Drag-drop upload queue
/admin/downloads          → Download job monitoring
/admin/storage            → Studio storage usage and quota

/super-admin/dashboard   → Platform stats (RequireSuperAdmin; a studio admin is sent back to /admin/dashboard)
/super-admin/studios      → Studio list: create, edit (details + quota), the studio's login (a Login ▾ menu per row: edit login details / change login email / reset password / disable-enable)
/super-admin/studios/:id  → Studio detail: quota, details + logo image, suspend/reactivate, users
/super-admin/audit-logs   → Platform-wide audit trail
/super-admin/settings     → The super admin's own password
/admin/settings           → Studio profile, admin account (change password), security & download policy

/:studioSlug/gallery/:galleryId              → Client entrance (auto-opens passwordless galleries)
/:studioSlug/gallery/:galleryId/view         → Album picker: every album shared with the client
/:studioSlug/gallery/:galleryId/view/:albumId → Single album view
/:studioSlug/gallery/:galleryId/view/:albumId/book → Book View: the page-turning reader for one album
                                    (redirects to the plain album view unless the album's
                                    book_view_enabled flag is on)
/:studioSlug/gallery/:galleryId/wishlist     → The client's wishlist
```

`:studioSlug` is the studio's name in the link (`studios.slug`, e.g. `/acme-photo/gallery/<link id>`). The older
`/gallery/:galleryId/...` form still works: every client gallery route is wrapped in `GalleryUrlGate`, which asks the
public access check (it returns the studio's `slug`) and redirects an old link to the studio's address, corrects a wrong
name, and leaves a studio without a slug on the old form. Pages build their links from `useGalleryBase()`, so a client stays
on one form of URL.

Behavioral notes on the entrance routes:
- `/` is the public front door and needs no auth: it shows the studio mark (the `/ls-logo.png`
  logo image plus the shared `.login-brand` wordmark — the same wordmark `AdminLogin`,
  `ClientLogin` and `NotFound` reuse) and the only two ways into the app.
  The client card takes the link the photographer sent - a full `.../gallery/<id>` URL, a
  trailing `/view` or query, or a bare id - and navigates client-side to `/gallery/<id>` (the gate then moves it to `/<studio>/gallery/<id>`); it
  is not a server redirect and is not an open redirect, since only `/[A-Za-z0-9_-]+/` is ever
  appended to the in-app path.
- `/gallery/:galleryId` probes `GET /api/client/gallery/access/{id}` while rendering the
  entrance backdrop; a gallery with no password logs the visitor straight in (empty-password
  login) and navigates to `/view`, one with a password shows the password card, and an
  unknown id falls back to the form (a bogus link reports `Invalid gallery link or
  password.`). The demo ids `test-uuid` / `preview` / `demo` skip the probe.
- `/admin/login` honors `?redirect=<in-app-path>`: when an admin session expires mid-use,
  `api.ts` bounces to `/admin/login?redirect=<encoded path+query>` and the login page
  returns the admin exactly where they left off after signing back in. The target is
  validated by `safeRedirectTarget()` (must be a same-origin absolute path; `//`, `/\`,
  `/\%5c` and non-slash targets are rejected) so a crafted URL can't be an open redirect.
- Unknown routes render the dedicated `NotFound` 404 page instead of the old bare text.

**Admin route gate.** Every `/admin/*` page except `/admin/login` sits behind a layout route
(`<Route element={<RequireAdmin />}>` in `App.tsx`), so nothing in the admin area renders until
the server confirms an admin session. `RequireAdmin` (`frontend/src/components/RequireAdmin.tsx`)
calls `GET /api/auth/me` once on entering the area and renders the page behind an `admin` identity;
it redirects anyone else to `/admin/login?redirect=<path+query>`. Without it the shell was only
"protected" indirectly (each page's own API calls 401 a beat later), so a client-side navigation —
most visibly the 404 page's "Back to dashboard" button, which never triggers a fresh page load —
could mount the dashboard for an unauthenticated visitor first. It checks once per area entry
(the layout stays mounted across admin navigation, so there is no loader flash per click), fails
closed on network errors, treats an active *gallery* session as "not an admin", and leaves
sessions that expire mid-use to `api.ts`'s 401 handler.

### API Client (`services/`)
- `api.ts` — Fetch wrapper with `ApiError`, typed interfaces (`Page`, `MediaItem`, `DownloadJob`);
  exports `API_BASE_URL`, read from `VITE_API_BASE_URL` (frontend `.env`) and prefixed onto every
  request - empty by default (same-origin, today's behavior), set only when the frontend is deployed
  on a different origin than the backend
- `auth.ts` — Login/me/logout calls (login/logout also reset the cached studio branding)
- `superAdmin.ts` — All `/api/super-admin/*` calls (studios, quota, users, logo upload via `api.postForm`, audit logs, change password)
- `studioBranding.ts` — Small store (read with `useSyncExternalStore` through `hooks/useStudioBranding.ts`) holding the logged-in studio's name and logo from `GET /api/studio/profile`; `assetUrl()` in `api.ts` resolves backend-served paths such as the logo against `API_BASE_URL`
- `admin.ts` — All admin endpoints (incl. `getSettings`/`updateStudioProfile`/`updateSecurityPolicy`/`changeAdminPassword`)
- `gallery.ts` — All client-facing endpoints (incl. `checkGalleryAccess` on `/client/gallery/access/{id}`, `thumbnailUrl`, `listWishlist`/`addToWishlist`/`removeFromWishlist`)

### Key Components
- `AdminLayout` + `Sidebar` — Studio admin shell; `StudioBrandMark` shows the studio's own name and logo in the sidebar and the mobile top bar (and `AdminDashboard`'s profile chip)
- `SuperAdminLayout` (+ `RequireSuperAdmin`, `components/superadmin/*`) — The console shell. It reuses the studio admin look (same sidebar, search pill and profile chip pattern) with every CSS class `sa-` prefixed and its design tokens scoped to a `.sa` wrapper, so it cannot affect the studio pages. Dialogs (`Modal`) are rendered into the `.sa` root through a portal and are stack-aware (Escape closes only the top one). One-time secrets (temporary passwords) are shown in `SecretModal`; a password reset uses the editable `ResetPasswordModal`, which starts empty, generates a password only on **Generate**, and keeps **Update password** disabled until something is entered (the old password is stored hashed and can never be shown). Suspend / reactivate / delete confirmations for a studio live in the `useStudioLifecycle` hook (`StudioLifecycleDialogs.tsx`), shared by the studios list (**More ▾**) and the studio detail page. The studios list's **Users ▾** button is `StudioUsersMenu` (each user with Edit / Reset password / Disable / Delete, plus Add user, and Manage all users when there is more than one); the dialogs behind every user action are shared through the `useAdminDialogs` hook in `StudioAdminsPanel.tsx`. Per-user actions live in `RowActionsMenu` (an **Actions ▾** button whose menu is portaled into `.sa` with fixed positioning, so dialogs and scrolling tables never clip it)
- `UploadContext` — Global upload queue manager mounted at admin root, maintaining in-flight transfers across page navigation
- `GlobalUploadBadge` — Floating status badge displayed across admin screens when background uploads are in progress
- `ClientLogin` — Probes gallery access first (`checkGalleryAccess`); opens passwordless galleries directly with a blank-password login, otherwise shows the password card (demo ids skip the probe)
- `AdminLogin` — Sign-in card that honors the `?redirect=` return target written by the session-expired handler (open-redirect guarded), showing an "expired" note when returning that way
- `NotFound` — The themed 404 page for unknown routes
- `Home` — The unauthenticated landing page at `/`: the platform logo lockup (`/ls-logo.png` + `.login-brand`), a hero, and the two
  portal cards (paste-a-gallery-link, and the studio sign-in)
- `ClientNav` — Gallery navigation
- `MediaLightbox` — Filmstrip + zoom + keyboard nav; optional `isWishlisted`/`onToggleWishlist` props add the heart (the admin lightbox passes neither)
- `WishlistHeart` — The one heart button (tile overlay / list row / lightbox variants); `hooks/useWishlist.ts` owns the state: optimistic toggle with rollback, one in-flight request per photo, seeded from the server flags of freshly loaded pages
- `DownloadJobModal` — Creates ZIP job, polls every 1.5s until completion
- `DownloadPasswordModal` — Gate for download-protected galleries
- `BookView` — The client-facing page-turning reader (`/gallery/:galleryId/view/:albumId/book`);
  loads the album through the normal client endpoints, re-checks `book_view_enabled` on entry,
  and renders the spread/leaf animation (see *Book View*)
- `BookCommentPanel` — The client's note sheet for the page on show (upsert on save, delete,
  length limit); `BookView` renders it above the book and pauses autoplay while it is open
- `AlbumCommentsModal` — Admin review of one album's page notes: grouped by page with thumbnail,
  status filter, resolve/reopen and delete; reports the new count back to the Albums list badge
- `RequireAdmin` — Layout-route session gate wrapping every `/admin/*` page; confirms the
  session with `GET /api/auth/me` before rendering and redirects non-admins to the login screen
  (see *Routing*)
- `PoweredBy` — The one shared credit line (`Powered by madgen` + `Version V0.4` / a date),
  rendered on the Home footer, both login pages (`.login-powered-wrap`), and the bottom of the
  admin sidebar; the version/date strings live only here

### Styling
- Plain CSS (no Tailwind/UI framework) split across `index.css` (global) + `styles/admin.css` / `styles/gallery.css` / `styles/book-view.css` / `styles/super-admin.css` per view
- Wedding typography: Alex Brush, Cormorant Garamond, Montserrat (Google Fonts, imported at the top of the per-view stylesheets)
- Reusable pieces in the shared sheets: `.powered-by` (credit line, in `index.css`; restyled for
  the sidebar in `admin.css`) and `.toggle-switch` (the generic on/off pill used by the Edit
  Album Book View control)

---

## Background Jobs

No task queue (by design — single-VPS, single-process). Background work uses FastAPI `BackgroundTasks`:

| Job | Mechanism | Notes |
|---|---|---|
| ZIP download creation | `BackgroundTasks` + threading | Snaps media list, prefetches files concurrently (`ZIP_JOB_PARALLEL_DOWNLOADS=4`), builds ZIP incrementally, TTL from `studio_settings.download_link_ttl_hours` (admin-configurable, default 24h) |
| Download analytics recording | Starlette `BackgroundTask` | Own DB session, non-blocking |
| Thumbnail generation | Client-side (WebP) with server fallback | Video posters and photo thumbnails are generated in the browser during direct upload; PIL and server-side FFmpeg are retained for fallbacks & backfills |
| Orphan reconciliation | Cron script (`python -m app.reconcile_orphans --apply`) | Deletes stored objects of uploads that never completed (no Media row) after `ORPHAN_FILE_GRACE_PERIOD_HOURS` (default 48h) grace; dry run without `--apply` |
| Quota reconciliation | Cron script (`python -m app.reconcile_quota [--apply]`) | Recomputes each studio's `used_bytes` / `reserved_bytes` from the database, releases reservations older than `UPLOAD_RESERVATION_TTL_MINUTES`; exit code 1 on drift |
| Expired job cleanup | Cron script (`python -m app.cleanup_download_jobs`) | Removes stale ZIPs; flips rows to `expired` |
| Stale upload sweep | On app boot (`lifespan`) | Marks `uploading`/`queued` sessions from a dead process as `failed` (`UPLOAD_STALE`) and releases their quota reservation |

---

## Third-Party Integrations

| Service | Purpose |
|---|---|
| Cloudflare R2 | Authoritative media storage (one bucket, one readable `studios/{studio-name}-{id}/` folder per studio) |
| FFmpeg | Video poster frame extraction (t=1.0s) |
| Google Fonts | Wedding-styled typography |
| MySQL 8 | Primary database |

---

## Deployment

### Origins

| | Origin | Notes |
|---|---|---|
| Frontend | `http://lovestoryphotography.in` | Static Vite build; `public/sitemap.xml` and `robots.txt` carry the same origin. Should move to `https://` once TLS terminates on the domain — sitemap `<loc>` and `robots.txt` `Sitemap:` are conventionally `https`, and search engines flag `http://` there |
| Backend | `https://api.madgen.space` | Must be in the backend's `CORS_ORIGINS`, **and** the frontend origin must be too for the API. The R2 bucket also needs its own CORS rule allowing the frontend origin to `PUT` (README, Setup step 4) |

The two are on different origins, so `CROSS_SITE_FRONTEND=true` and the Secure/SameSite=None session cookies apply. `main.py`'s boot check warns when `CROSS_SITE_FRONTEND=true` while `ENVIRONMENT=development`, because browsers silently reject those cookies over plain HTTP.

`vercel.json` hosts the frontend: `/:path*` → `/index.html` (SPA rewrite), `/api/:path*` → `https://api.madgen.space/api/:path*`, security headers on every response, and explicit `Content-Type` + `Cache-Control: public, max-age=86400` for `robots.txt` and `sitemap.xml`.

### Steps

- **Backend**: `uvicorn app.main:app` with Alembic migrations (`alembic upgrade head`)
- **Frontend**: `npm run build` → static files served from same origin
- **Platform owner**: `python -m app.create_super_admin` (min 4 characters); create studios and their admins in the console. An existing single-studio install is mapped with `python -m app.legacy_to_studio` (runbook in `MULTI_STUDIO.md` §3)
- **Pre-deploy sanity gate**: `python scripts/check_env.py` (DB connectivity, R2 settings and bucket access, writable `ZIP_TEMP_DIR`, ffmpeg on PATH; exits nonzero on any FAIL) and `python -m scripts.check_r2` (write/read-back and a presigned upload URL)
- **R2 bucket CORS**: allow the production frontend origin to `PUT`
- **Cron jobs**: `python -m app.cleanup_download_jobs`, `python -m app.reconcile_orphans --apply`, `python -m app.reconcile_quota`
- **Dev API access**: the app calls `VITE_API_BASE_URL` directly; optionally set `VITE_API_URL` so Vite proxies `/api` to that origin (e.g. `http://localhost:8000`)

### Branding

**Platform mark.** `frontend/public/ls-logo.png` is the platform logo, inlined by absolute URL rather than imported so Vite serves it from `public/` unhashed:

| Where | How |
|---|---|
| Favicon / apple-touch-icon | `index.html` `<link rel="icon" | "alternate icon" | "apple-touch-icon">` all point at `/ls-logo.png` (`type="image/png"`). The older `favicon.svg` heart-and-lens mark is still in `public/` but no longer referenced by anything |
| Home landing page | `Home.tsx` `.home-mark` renders the same file at 72×72 above the `.login-brand` wordmark |

`public/light-ls-logo.png` is a light-background variant, present but not yet referenced by any view.

**Per-studio logo.** Each studio has its own logo, uploaded by the super admin as an image (not a URL): checked, re-encoded to a PNG that fits 512 px with metadata stripped (SVG is refused, 5 MB limit), stored in R2 at `{studio folder}/branding/logo-{hash}.png` and served from `GET /api/studios/{id}/logo?v={hash}` (public, cached for a year; the hash changes with every upload). `studios.logo_url` holds that path, so no extra table is involved. The studio admin area reads it, with the studio name, from `GET /api/studio/profile` and shows it in the sidebar, the mobile top bar and the dashboard profile chip (`StudioBrandMark`, `useStudioBranding`); the old hard-coded logo in the admin header is gone. A studio without a logo shows its name, and the profile chip an initial.

Separately, the shared `PoweredBy` credit line (`Powered by madgen`, with the build's
version and date) appears in four places: the Home footer (replacing the old two-span
`.home-footer` tagline), both login cards via the `.login-powered-wrap` bottom anchor, and the
base of the admin sidebar (`.admin-sidebar__powered`). It is the single source of the displayed
version string.

---

## Testing

- 27 pytest test files in `backend/tests/` (+ shared `conftest.py` / `fakes.py` / `ms_helpers.py`)
- SQLite in-memory database + `FakeStorageService` / a fake S3 client for `R2Storage` (no real storage calls)
- Coverage: multi-studio behaviour (`test_multi_studio_*.py`, 130 tests: super admin API incl. studio logos, the one-login-per-studio rule at API and database level, the `consolidate_studio_logins` cleanup tool and the saved studio folder, tenant isolation across URL/body/query/bulk, suspension, client gallery shows the sharing studio's branding, quota reserve/commit/release and concurrency, R2 key handling, the readable studio/album/client folders and the tenant check, legacy mapping); auth (incl. the optional gallery-password flow and cookie security attributes), authorization & cross-client isolation, client search & selection summaries, admin/client/album management, album expiry, media management (search, pagination, metadata edits, move, delete), bulk ops, gallery totals, ZIP download jobs & analytics, upload hardening (idempotency, disk reservation, concurrency limits, stale-session recovery, orphan reconciliation), thumbnails & streaming (range requests, 416s, concurrency), the server-side thumbnail fallback, the thumbnail-folder migration, dashboard, storage integration (folder provisioning, storage overview), folder naming, FFmpeg availability, the legacy Drive client's cleanup-bug regression, studio settings/security policy (incl. self-service admin password change), page notes (`test_comments.py`: upsert, cross-client isolation, validation, expiry, admin review, album counts), book order (`test_media_order.py`: reorder, client-side ordering, complete-list validation, note renumbering, move-to-end, admin-only access)
- Suite status: **322 pass, 106 fail** (428 total). The failures are older tests that still drive the retired byte-relay `POST /api/admin/media/upload` route and the old Drive resumable helpers, which no longer exist in the direct-to-R2 app — a notable trap, because the SQLite-backed suite happily compiles queries (`count(...) FILTER (WHERE ...)`) that MySQL 8 rejects, so a green run is not proof a query works on the real database. The current upload path is exercised by `test_multi_studio_storage.py` / `test_multi_studio_quota.py` (R2 key, quota, completion). It was also checked end to end in a real browser against an S3-compatible stand-in (select a file, presigned PUT, thumbnail, confirmation, view/download, delete)
- No frontend tests

---

## Notable Design Decisions

1. **No task queue** — Deliberate choice for single-VPS simplicity; ZIP jobs run in-process via `BackgroundTasks`
2. **Cloudflare R2 as direct storage** — Bulk media uploads never touch the application server's disk or relay through its network interface; browsers upload directly to R2 via presigned PUT URLs signed for one server-chosen key and exact size, saving VPS bandwidth and disk space. Every key lives under `studios/{studio_id}/`. Only `r2_storage.py` imports boto3. Google Drive was the earlier backend and is no longer configurable
3. **Optional dual password system** — The gallery login password (Argon2) is optional (`NULL` = passwordless, opens straight in) and can be set, changed, or removed by an admin later; a separate, optional download password gates ZIP downloads when present. Both passwords can be cleared again via a nullable `password: null` on their respective change endpoints
4. **Client-scoped routes** — Every client route validates `galleryId` ownership; no cross-tenant access possible. The same holds one level up: the studio is always derived from the authenticated admin/client row, every studio-owned table has `studio_id`, and another studio's resource answers 404 so ids cannot be probed
5. **Upload idempotency** — `upload_sessions` table prevents duplicate uploads on retry
6. **Orphan reconciliation** — Background cron catches stored objects of uploads that never got a DB row
7. **Album expiry** — Enforced only on client routes; admins always see expired albums
8. **Studio settings as one lazily created row per studio** — `studio_settings` has at most one row
   per studio, created with defaults on first read rather than seeded by its migration, so a fresh
   install and an upgraded install behave identically with no data-seed step to keep in sync
9. **Circuit breaker over raw retries (Drive era)** — Retry-with-backoff alone couldn't stop a burst of
   failing Drive connectivity calls from exhausting the request thread pool; a process-wide circuit
   breaker (`circuit_breaker.py`) failed fast during a cooldown window instead. It now guards only the
   dormant Drive client; R2 calls use boto3's own retry configuration
10. **Client-side WebP thumbnail generation** — Generating video poster frames and photo thumbnails
    in the browser via HTML5 Canvas and WebP compression avoids expensive server-side video re-downloads
    and renders server-side FFmpeg optional (retained only for backfill tooling)
11. **No stored cover image** — Album art is the album's own first thumbnail, resolved at read
    time, and an album with no thumbnailed item falls back to a styled empty cover block. The
    earlier per-client automatic cover was removed outright: a second, parallel set of cover
    bytes meant a second storage location, a second claim/compare-and-set race, two more columns,
    two more endpoints, and a migration to reclaim the leftovers — all to produce an image that a
    thumbnail already provided. Deriving it removes the whole surface, and nothing is left to
    reconcile, replace, or go stale
12. **Wishlist as a plain relationship** — Favourites are rows, not files: no storage copies, no second
    gallery. Ownership is re-derived server-side from the session on every write
13. **Two kinds of logo** — the platform mark `ls-logo.png` is served from `public/` (favicon and
    home mark, no build hash, not bundled); each studio's own logo is an uploaded image stored in R2
    and served by a public, versioned, immutable-cache route, so a replaced logo is never stale and no
    new column or migration was needed (`studios.logo_url` holds the path)
14. **Book View reuses the grid's endpoints** — the page-turning reader adds no
    separate read path: it calls the same client album/media endpoints and access
    checks, plus two presentation columns on `albums` (`book_view_enabled`,
    `book_layout`) that decide whether the UI is offered. Making it a flag rather
    than a separate permission keeps one set of ownership and expiry rules to
    reason about, so the book can never expose media the grid wouldn't
15. **Page notes are a per-page upsert, not a chat** — one note per
    `(client, album, page)` keeps the table and both UIs simple: the client sheet
    is always "write" or "edit", and the admin list never has duplicate threads to
    merge. Editing a note reopens it so changed wording is re-reviewed, and the
    note outlives its photo (`media_id ON DELETE SET NULL`) because the feedback
    is still meaningful after the picture is removed
16. **Quota is enforced by the application, not by R2** — a studio's quota and the platform capacity are
    reserved in single conditional `UPDATE ... WHERE used+reserved+n <= quota` statements before a presigned
    URL is issued (race-safe on InnoDB), committed on confirmation and released on failure; R2 only
    enforces the exact signed `Content-Length`. `reconcile_quota` repairs drift
17. **One frontend for all roles** — the Super Admin console is part of the same React app, behind the
    same login and cookie, with role guards (`RequireAdmin` / `RequireSuperAdmin`) for UX only; the API
    enforces the role on every route (`SUPER_ADMIN_REQUIRED` / `STUDIO_ADMIN_REQUIRED`). Its CSS is
    `sa-` prefixed and scoped so it cannot leak into the studio or client pages
18. **Passwords cannot be shown** — all passwords are stored as Argon2 hashes, so the "old password" of a
    studio user can never be displayed. A super admin resets it instead: the new password is chosen or
    generated explicitly, shown once, and the user's other sessions are revoked (`session_version`)
