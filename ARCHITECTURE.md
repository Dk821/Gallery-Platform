# Architecture — LoveStory PH (Private Wedding Gallery Platform)

## Overview

A private gallery platform for wedding photographers to manage clients, albums, and media. Two interfaces: an **admin panel** for the studio and a **client gallery** for viewing/downloading photos and videos.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite 8, React Router 7 |
| Backend | Python 3.12, FastAPI 0.115, Uvicorn |
| Database | MySQL 8 (via SQLAlchemy 2 + PyMySQL) |
| Migrations | Alembic |
| Storage | Google Drive v3 API (OAuth2 credentials) |
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
│   │   │   ├── admin_*.py    # Admin endpoints (clients, albums, media, dashboard, activity, storage, downloads, settings)
│   │   │   └── client_*.py   # Client endpoints (gallery, download jobs, wishlist)
│   │   ├── config/           # pydantic-settings (.env loader)
│   │   ├── database/         # SQLAlchemy engine, session, Base
│   │   ├── models/           # 12 ORM models + mixins
│   │   ├── schemas/          # Pydantic request/response models (auth, client, album, media, download_job, studio_settings, errors, pagination)
│   │   ├── security/         # Password hashing (Argon2), session tokens, reversible encryption (Fernet)
│   │   ├── services/         # Business logic layer (activity_service, admin_service, album_service, auth_service, circuit_breaker, client_service, comment_service, dashboard_service, disk_service, download_analytics_service, download_job_service, folder_naming, google_drive_service, media_aggregates, media_service, media_validation, orphan_reconciliation, retry, storage_analytics_service, storage_provider, storage_service, studio_settings_service, thumbnail_folder_migration, timeout_utils, upload_concurrency, upload_logging, wishlist_service)
│   │   ├── workers/          # Thumbnail generation (PIL + FFmpeg)
│   │   ├── main.py           # App factory, lifespan, middleware, error envelope
│   │   ├── create_admin.py   # First admin bootstrap (python -m app.create_admin)
│   │   ├── reconcile_orphans.py      # Cron: dry-run/--apply Drive orphan cleanup
│   │   ├── cleanup_download_jobs.py  # Cron: expired ZIP cleanup
│   │   └── migrate_thumbnail_folders.py  # Ops: dry-run/--apply "Cover Images" → "Thumbnails" rename + orphan cover purge
│   ├── scripts/              # check_env.py (env sanity gate), generate_drive_refresh_token.py
│   ├── alembic/              # Database migrations
│   ├── .env                  # Backend config (secrets - not committed)
│   ├── .env.example          # Config template (committed)
│   └── tests/                # 23 pytest test files + conftest/fakes
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
│   │   ├── ls-logo.png       # The studio logo — favicon, admin avatar, and home mark
│   │   ├── light-ls-logo.png # Light-background variant of the logo
│   │   ├── favicon.svg       # Legacy heart-and-lens mark (superseded by ls-logo.png)
│   │   ├── images/           # album-bg.webp, album-hero.webp (landing-page backdrops)
│   │   ├── robots.txt        # Allows /, blocks /admin, /api, /.git, /.env*
│   │   └── sitemap.xml       # Canonical public URLs (the site root + /gallery)
│   └── src/
│       ├── components/       # Shared UI (AdminLayout, Sidebar, Lightbox, Modals, GlobalUploadBadge, WishlistHeart,
│       │                         PoweredBy credit line, RequireAdmin route guard)
│       ├── contexts/         # React Contexts (UploadContext - global persistent upload queue)
│       ├── hooks/            # useWishlist (optimistic client wishlist state)
│       ├── pages/            # Admin + Client pages (incl. BookView - the client-facing page-turning reader)
│       ├── services/         # Typed API client (auth, admin, gallery)
│       ├── styles/           # Plain CSS: index.css + admin.css + gallery.css + book-view.css
│       ├── utils/            # format.ts, photoThumbnail.ts, videoPoster.ts
│       ├── vite-env.d.ts     # ImportMetaEnv typing for VITE_ vars
│       ├── App.tsx           # Route definitions
│       └── main.tsx          # Entry point
├── ARCHITECTURE.md           # This file
├── Upload-Pipeline.md        # Deep dive on direct-to-Drive upload pipeline
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

## Database Schema (12 Tables)

| Table | Purpose |
|---|---|
| `admins` | Admin/staff users (email, Argon2 password hash, status) |
| `clients` | Client accounts with `client_uuid` (public galleryId), Drive folder ID, a random `folder_uid` folder-name suffix, encrypted password copies, and `thumbnail_folder_id` (the client's dedicated `Thumbnails` Drive folder - a sibling of the album folders, never inside one - holding every item thumbnail; nullable, created lazily, never exposed by any API). `password_hash` is **nullable**: a `NULL` gallery password means the gallery has no password prompt (see *Client Auth*) |
| `albums` | Albums per client, with expiry (`expires_at`), Drive folder, and the two Book View presentation columns: `book_view_enabled` (boolean, default `false` - per-album opt-in to the client-facing page-turning reader) and `book_layout` (`square` / `portrait` / `landscape`, default `landscape` - the aspect ratio of the spread) |
| `media` | Photo/video records with Google Drive file IDs, metadata, type, and `sort_order` (1-based position inside the album's book order; ordering is `sort_order ASC, id ASC`, and uploads/moves append at `MAX(sort_order)+1`) |
| `sessions` | Client server-side sessions (SHA-256 hashed tokens, expiry, download password verification) |
| `media_wishlists` | A client's favourites: `(client_id, media_id)` with `UNIQUE(client_id, media_id)` and an index on `media_id`; both FKs `ON DELETE CASCADE`. Pure database relationship - nothing is ever copied in Drive |
| `album_comments` | Client page notes on a Book View album: 1-based `page_number`, free text (≤2000 chars), `status` (`open` / `resolved`), and an optional `media_id` (`ON DELETE SET NULL`, so the note survives its photo). `UNIQUE(client_id, album_id, page_number)` makes saving a page an upsert; the album/client FKs cascade |
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
| POST | `/api/auth/admin/login` | Admin login → HttpOnly cookie |
| POST | `/api/auth/client/login` | Client login → HttpOnly cookie |
| POST | `/api/auth/logout` | Clear session |
| GET | `/api/auth/me` | Current user info |

### Admin (`/api/admin/*`) — Cookie auth required
| Area | Endpoints |
|---|---|
| Clients | CRUD (gallery password optionally left blank → **passwordless** gallery), view passwords, change password, change/clear download password, disable/enable, regenerate gallery ID, client wishlist (`GET /{id}/wishlist?album_id=`, read-only) |
| Albums | CRUD, filter by client, list media (`?wishlist=all\|wishlisted\|not_wishlisted`, in book order), selection summary (same filter), wishlist counts (`GET /{id}/media/wishlist-counts`), drag-and-drop book order (`PUT /{id}/media/order` - the complete media-id list exactly once; `MEDIA_ORDER_INVALID` otherwise, page notes follow their photo). `PUT /{id}` also carries the Book View presentation flags (`book_view_enabled` - omit to leave untouched, explicit `false` to turn off - and `book_layout`) |
| Page notes | Per-album notes (`GET /{id}/comments`), resolve/reopen or correct the text (`PATCH /comments/{id}`, both fields optional), delete (`DELETE /comments/{id}`). Admin review deliberately ignores album expiry |
| Media | Direct upload session (`POST /upload-session`), thumbnail upload (`POST /upload-session/{id}/thumbnail`), completion confirmation (`POST /upload-complete`), progress ping (`POST /upload-progress/{id}`), abandonment (`POST /upload-session/{id}/abandon`), status (`GET /upload-status/{id}`), recent session list (`GET /upload-sessions`), bulk delete/move, stream, download, thumbnail, orphans |
| Dashboard | Stats summary |
| Activity | Audit log feed |
| Storage | Google Drive quota |
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

### Upload Hardening (Direct-to-Drive Architecture)
- **Direct-to-Drive transfers**: The browser transfers bytes directly to Google Drive via resumable session URLs (`adminService.uploadToDrive`). Large media payloads (up to 10 GB) never touch the application server's disk or relay through its network interface.
- **CORS Origin forwarding**: During session creation (`POST /api/admin/media/upload-session`), the server validates the incoming browser `Origin` against `settings.effective_cors_origins` and forwards it to Google Drive's resumable session initiator, enabling Google Drive to issue standard CORS headers to subsequent browser PUTs.
- **Client-Side WebP thumbnails**: Video poster frames (`videoPoster.ts`) and photo thumbnails (`photoThumbnail.ts`) are generated directly in the browser using HTML5 Canvas and WebP compression, then uploaded as small images to `POST /upload-session/{id}/thumbnail`. This eliminates heavy server-side video downloads and makes server-side FFmpeg optional. Both are stored in the client's dedicated `Thumbnails` Drive folder — a sibling of the album folders, never inside one (see *Album Covers*).
- **One thumbnail folder per client**: `media_service._ensure_thumbnail_folder` lazily creates (or reuses, via `clients.thumbnail_folder_id`) a single `Thumbnails` folder per client, so every video poster and photo thumbnail of that client lives in exactly one place. Clients created before the rename still have their folder called `Cover Images` in Drive; `migrate_thumbnail_folders.py` renames it and purges the removed cover's leftover `cover.webp`.
- **Portable aggregates**: `media_aggregates.py` builds the photo/video count and byte-total expressions as `SUM(CASE WHEN ...)` rather than `count(...) FILTER (WHERE ...)`, because MySQL 8 has no `FILTER` clause — the `FILTER` spelling compiles and passes on the SQLite test suite, then dies with a 1064 on the real database.
- **Ranged-read signature validation**: Upon completion (`POST /api/admin/media/upload-complete`), the server verifies the file with Drive and reads only the initial header bytes (range 0..511 bytes) to perform magic-byte and ISO-BMFF box-walk checks (`app/services/media_validation.py`) without downloading the bulk file.
- **Idempotency ledger (`upload_sessions`)**: Each upload uses a UUID-based `upload_id` decoupled from filename to prevent `VARCHAR(100)` column overflow. Duplicate submissions of completed uploads safely return the existing `Media` record without re-uploading.
- **Global queue persistence**: `UploadContext.tsx` maintains upload state globally across admin routes. Transfer progress is visible anywhere via `GlobalUploadBadge.tsx`. Memory is guarded by `withReleasedFile()`, which clears `File` object handles from React state upon upload completion or cancellation.
- **Client-side throttling**: The upload queue scheduler caps active transfers to `MAX_CONCURRENT_UPLOADS = 4` simultaneous connections to prevent network saturation.
- **Server admission control**: Tunable via `UPLOAD_MAX_CONCURRENT` (default `3`), `UPLOAD_MAX_CONCURRENT_REQUESTS` (default `8`), `UPLOAD_QUEUE_WAIT_SECONDS` (default `45`), `UPLOAD_CHUNK_TIMEOUT` (default `120`) and `UPLOAD_SESSION_TIMEOUT` (default `3600`). Override them in `.env` for larger batches or slower links.
- **Socket-level timeouts**: Every `httplib2.Http()` used to communicate with Google Drive has explicit socket timeouts (`timeout=settings.upload_chunk_timeout`), preventing hung TLS handshakes from permanently blocking worker threads.
- **Circuit breaker** (`app/services/circuit_breaker.py`): Wraps transport calls to Google Drive. Trips after 3 consecutive transport/connectivity failures with a 20-second cooldown, protecting the backend thread pool during Google Drive service degradation.


### Album Covers
There is no stored cover image anywhere in the system, and nothing to manage: no cover column, no cover upload route, no cover in any API response.

- **Derived per album, at read time**: the gallery album grid fetches `GET /api/client/media?album_id={id}&page=1&limit=1` and uses the first item's `has_thumbnail` flag — if set, that item's thumbnail URL becomes the album cover; if not, the card renders its styled empty cover block (`wedding-album-card__cover-empty`) over the album's gradient background.
- **One request per album, deliberately**: photo/video counts and byte totals already ride on the album list (aggregated in SQL), so the first media page is the only extra fetch the grid makes — and it asks for a single item.
- **Replacing a removed feature**: an earlier design gave each *client* one automatic cover, built by the browser from the first eligible photo and stored as `cover.webp` beside the album folders. It was removed (Alembic `a5c7e3b1d9f8`) along with `cover_service.py` and the `POST /upload-session/{id}/cover` + `GET /gallery/cover` endpoints; `cover_drive_file_id` was dropped, while `cover_folder_id` was renamed to `thumbnail_folder_id` (value preserved). Album art now comes from the album's own first thumbnail, so there is no cover that can go stale or need reconciling.
- **Legacy bytes**: `migrate_thumbnail_folders.py` (dry-run by default, `--apply` to write) renames each legacy `Cover Images` folder to `Thumbnails` — metadata-only, so the folder id and every thumbnail inside it are untouched — then deletes the orphaned `cover.webp`, which is unambiguously identifiable because item thumbnails are always named `thumb_{uuid}.webp`. A file by that name is still skipped if any `Media` row references it, and a folder missing from Drive has its now-dangling `thumbnail_folder_id` cleared so the next upload recreates it.

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
/                            → Home: studio logo + the two ways in (client gallery link, studio sign-in)
/admin/login              → Admin login (accepts ?redirect=<in-app-path>)
/admin/dashboard          → Dashboard with area chart
/admin/activity           → Audit log feed
/admin/clients            → Client CRUD
/admin/albums             → Album CRUD
/admin/albums/:albumId    → Album media management
/admin/uploads            → Drag-drop upload queue
/admin/downloads          → Download job monitoring
/admin/storage            → Drive quota usage
/admin/settings           → Studio profile, admin account (change password), security & download policy

/gallery/:galleryId              → Client entrance (auto-opens passwordless galleries)
/gallery/:galleryId/view         → Album picker: every album shared with the client
/gallery/:galleryId/view/:albumId → Single album view
/gallery/:galleryId/view/:albumId/book → Book View: the page-turning reader for one album
                                    (redirects to the plain album view unless the album's
                                    book_view_enabled flag is on)
/gallery/:galleryId/wishlist     → The client's wishlist
```

Behavioral notes on the entrance routes:
- `/` is the public front door and needs no auth: it shows the studio mark (the `/ls-logo.png`
  logo image plus the shared `.login-brand` wordmark — the same wordmark `AdminLogin`,
  `ClientLogin` and `NotFound` reuse) and the only two ways into the app.
  The client card takes the link the photographer sent - a full `.../gallery/<id>` URL, a
  trailing `/view` or query, or a bare id - and navigates client-side to `/gallery/<id>`; it
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
- `auth.ts` — Login/me/logout calls
- `admin.ts` — All admin endpoints (incl. `getSettings`/`updateStudioProfile`/`updateSecurityPolicy`/`changeAdminPassword`)
- `gallery.ts` — All client-facing endpoints (incl. `checkGalleryAccess` on `/client/gallery/access/{id}`, `thumbnailUrl`, `listWishlist`/`addToWishlist`/`removeFromWishlist`)

### Key Components
- `AdminLayout` + `Sidebar` — Admin shell
- `UploadContext` — Global upload queue manager mounted at admin root, maintaining in-flight transfers across page navigation
- `GlobalUploadBadge` — Floating status badge displayed across admin screens when background uploads are in progress
- `ClientLogin` — Probes gallery access first (`checkGalleryAccess`); opens passwordless galleries directly with a blank-password login, otherwise shows the password card (demo ids skip the probe)
- `AdminLogin` — Sign-in card that honors the `?redirect=` return target written by the session-expired handler (open-redirect guarded), showing an "expired" note when returning that way
- `NotFound` — The themed 404 page for unknown routes
- `Home` — The unauthenticated landing page at `/`: the studio logo lockup (`/ls-logo.png` + `.login-brand`), a hero, and the two
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
- Plain CSS (no Tailwind/UI framework) split across `index.css` (global) + `styles/admin.css` / `styles/gallery.css` / `styles/book-view.css` per view
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

### Origins

| | Origin | Notes |
|---|---|---|
| Frontend | `http://lovestoryphotography.in` | Static Vite build; `public/sitemap.xml` and `robots.txt` carry the same origin. Should move to `https://` once TLS terminates on the domain — sitemap `<loc>` and `robots.txt` `Sitemap:` are conventionally `https`, and search engines flag `http://` there |
| Backend | `https://api.madgen.space` | Must be in the backend's `CORS_ORIGINS`, **and** the frontend origin must be too — the same allowlist (`settings.effective_cors_origins`) is what authorizes the browser's direct PUTs to Google Drive (see *CORS Origin forwarding*) |

The two are on different origins, so `CROSS_SITE_FRONTEND=true` and the Secure/SameSite=None session cookies apply. `main.py`'s boot check warns when `CROSS_SITE_FRONTEND=true` while `ENVIRONMENT=development`, because browsers silently reject those cookies over plain HTTP.

`vercel.json` hosts the frontend: `/:path*` → `/index.html` (SPA rewrite), `/api/:path*` → `https://api.madgen.space/api/:path*`, security headers on every response, and explicit `Content-Type` + `Cache-Control: public, max-age=86400` for `robots.txt` and `sitemap.xml`.

### Steps

- **Backend**: `uvicorn app.main:app` with Alembic migrations (`alembic upgrade head`)
- **Frontend**: `npm run build` → static files served from same origin
- **First admin**: `python -m app.create_admin` (password must be exactly 8 chars)
- **Pre-deploy sanity gate**: `python scripts/check_env.py` (verifies DB connectivity, Drive token/root
  folder, writable `ZIP_TEMP_DIR`, ffmpeg on PATH; exits nonzero on any FAIL)
- **Drive token refresh**: `python scripts/generate_drive_refresh_token.py` (re-runs the OAuth consent
  flow after `invalid_grant: Token has been expired or revoked`)
- **Ops pass, once**: `python -m app.migrate_thumbnail_folders --apply` (renames legacy `Cover Images`
  folders to `Thumbnails` and purges the removed cover — see *Album Covers*); dry-run first
- **Cron jobs**: `python -m app.cleanup_download_jobs`, `python -m app.reconcile_orphans --apply`
- **Dev API access**: the app calls `VITE_API_BASE_URL` directly; optionally set `VITE_API_URL` so Vite proxies `/api` to that origin (e.g. `http://localhost:8000`)

### Branding

`frontend/public/ls-logo.png` is the single studio logo, referenced from three places and inlined
rather than imported so Vite serves it from `public/` unhashed:

| Where | How |
|---|---|
| Favicon / apple-touch-icon | `index.html` `<link rel="icon" | "alternate icon" | "apple-touch-icon">` all point at `/ls-logo.png` (`type="image/png"`). The older `favicon.svg` heart-and-lens mark is still in `public/` but no longer referenced by anything |
| Admin header chip | `AdminDashboard.tsx` `.admin-profile-avatar` renders `<img src="/ls-logo.png">` (circular via `border-radius: 50%` + `overflow: hidden` on a 28px box), in place of the old hard-coded `L` initial |
| Home landing page | `Home.tsx` `.home-mark` renders the same file at 72×72 above the `.login-brand` wordmark |

`public/light-ls-logo.png` is a light-background variant, present but not yet referenced by any view.

Separately from the logo, the shared `PoweredBy` credit line (`Powered by madgen`, with the
build's version and date) appears in four places: the Home footer (replacing the old two-span
`.home-footer` tagline), both login cards via the `.login-powered-wrap` bottom anchor, and the
base of the admin sidebar (`.admin-sidebar__powered`). It is the single source of the displayed
version string.

---

## Testing

- 23 pytest test files in `backend/tests/` (+ shared `conftest.py` / `fakes.py`)
- SQLite in-memory database + `FakeStorageService` (no real Drive calls)
- Coverage: auth (incl. the optional gallery-password flow and cookie security attributes), authorization & cross-client isolation, client search & selection summaries, admin/client/album management, album expiry, media management (search, pagination, metadata edits, move, delete), bulk ops, gallery totals, ZIP download jobs & analytics, upload hardening (idempotency, disk reservation, concurrency limits, stale-session recovery, orphan reconciliation), thumbnails & streaming (range requests, 416s, concurrency), the server-side thumbnail fallback, the thumbnail-folder migration, dashboard, storage integration (Drive folder provisioning, storage overview), Drive folder naming, direct resumable uploads, FFmpeg availability, httplib2 cleanup-bug regression, studio settings/security policy (incl. self-service admin password change), page notes (`test_comments.py`: upsert, cross-client isolation, validation, expiry, admin review, album counts), book order (`test_media_order.py`: reorder, client-side ordering, complete-list validation, note renumbering, move-to-end, admin-only access)
- Suite status: **192 pass, 107 fail** (299 total). The failures are older tests that still drive the retired byte-relay `POST /api/admin/media/upload` route, which no longer exists in the direct-to-Drive app — a notable trap, because the SQLite-backed suite happily compiles queries (`count(...) FILTER (WHERE ...)`) that MySQL 8 rejects, so a green run is not proof a query works on the real database. The current upload path is exercised at the storage layer (`test_drive_resumable_upload.py`) and the session/ledger layer (`test_upload_hardening.py`), not as an end-to-end HTTP upload
- No frontend tests

---

## Notable Design Decisions

1. **No task queue** — Deliberate choice for single-VPS simplicity; ZIP jobs run in-process via `BackgroundTasks`
2. **Google Drive as direct storage** — Bulk media uploads never touch the application server's disk or relay through its network interface; browsers upload directly to Google Drive via resumable upload URLs, saving VPS bandwidth and disk space. Media files are organized into client and album Drive folders. Only `google_drive_service.py` imports the Drive SDK
3. **Optional dual password system** — The gallery login password (Argon2) is optional (`NULL` = passwordless, opens straight in) and can be set, changed, or removed by an admin later; a separate, optional download password gates ZIP downloads when present. Both passwords can be cleared again via a nullable `password: null` on their respective change endpoints
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
12. **Wishlist as a plain relationship** — Favourites are rows, not files: no Drive copies, no second
    gallery. Ownership is re-derived server-side from the session on every write
13. **Logo served from `public/`, not bundled** — `ls-logo.png` is referenced by absolute URL from
    `index.html` and two views, so one file is the favicon, the admin avatar and the home mark
    without a build hash and without duplicating the binary into the JS bundle
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
