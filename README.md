# LoveStory PH — Private Wedding Gallery Platform

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
| Image Processing | Pillow (server-side fallbacks/resizing) + HTML5 Canvas/WebP (client-side) |
| Auth | Argon2 (passwords), itsdangerous (admin tokens), Fernet (reversible encryption) |

---

## Prerequisites

- **Python 3.12+**
- **Node.js 20.19+** (or 22.12+) and npm (Vite 8's engine requirement)
- **MySQL 8**
- **Google Drive API** credentials (OAuth2 Desktop app credentials with Drive access)
- **FFmpeg** (optional system binary — video poster frames are generated directly in the browser during upload; FFmpeg on the server is only used for administrative backfill tooling)

### FFmpeg (optional — server-side poster backfill tooling)

Video poster frames and photo thumbnails are generated client-side by the browser during upload (`videoPoster.ts` and `photoThumbnail.ts`), saving server bandwidth and memory. The server-side FFmpeg integration is retained as an optional fallback and for administrative backfill tooling.

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y ffmpeg

# macOS
brew install ffmpeg

# Docker (python:3.12-slim base)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
```

Verify: `ffmpeg -version` or check `GET /api/health` once running.

---

## Project Structure

```
final v2/
├── backend/
│   ├── app/
│   │   ├── api/              # Route handlers (admin, client, auth, media streaming)
│   │   ├── config/           # pydantic-settings (.env loader)
│   │   ├── database/         # SQLAlchemy engine, session, Base
│   │   ├── models/           # 12 ORM models + shared mixins
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── security/         # Password hashing, sessions, encryption
│   │   ├── services/         # Business logic layer (storage, direct upload, validation, etc.)
│   │   ├── workers/          # Thumbnail worker (PIL + FFmpeg fallback)
│   │   ├── main.py           # App factory, lifespan, middleware
│   │   ├── create_admin.py   # First admin bootstrap
│   │   ├── reconcile_orphans.py      # Cron: Drive orphan cleanup
│   │   ├── cleanup_download_jobs.py  # Cron: expired ZIP cleanup
│   │   └── migrate_thumbnail_folders.py  # Ops: "Cover Images" -> "Thumbnails" rename
│   ├── scripts/              # check_env.py, generate_drive_refresh_token.py
│   ├── alembic/              # Database migrations
│   ├── tests/                # pytest test files + conftest/fakes
│   ├── .env.example          # Backend config template
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/       # Shared UI (AdminLayout, Sidebar, Lightbox, GlobalUploadBadge,
│   │   │                     #   PoweredBy credit line, RequireAdmin route guard)
│   │   ├── contexts/         # React Contexts (UploadContext - persistent background queue)
│   │   ├── hooks/            # useWishlist (optimistic wishlist state)
│   │   ├── pages/            # Admin + Client pages
│   │   ├── services/         # Typed API client (auth, admin, gallery)
│   │   ├── styles/           # Plain CSS (index.css, admin.css, gallery.css, book-view.css)
│   │   ├── utils/            # format.ts, photoThumbnail.ts, videoPoster.ts
│   │   ├── App.tsx           # Route definitions
│   │   └── main.tsx          # Entry point
│   ├── public/               # Copied verbatim to dist/ (ls-logo.png, favicon.svg,
│   │   │                     #   images/, robots.txt, sitemap.xml)
│   ├── index.html            # SPA entry (<head>, favicon -> /ls-logo.png, #root mount)
│   ├── vite.config.ts        # React plugin + /api dev proxy
│   ├── vercel.json           # SPA rewrite, /api proxy, security headers
│   ├── .env.example          # Frontend config template
│   └── package.json
├── ARCHITECTURE.md
├── Upload-Pipeline.md
└── README.md
```

---

## Setup

### 1. Clone and enter the project

```bash
git clone <repo-url> && cd "final v2"
```

### 2. Backend

```bash
cd backend

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment config
cp .env.example .env
# Edit .env with your MySQL credentials, Google Drive API keys, and a random SECRET_KEY
```

### 3. Database

Create the MySQL database and user:

```sql
CREATE DATABASE gallery_db;
CREATE USER 'gallery_user' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON gallery_db.* TO 'gallery_user';
```

Run migrations:

```bash
alembic upgrade head
```

### 4. Google Drive Setup

1. Create a Google Cloud project with Drive API enabled
2. Create OAuth2 credentials (Desktop app type)
3. Run the token generator script to get a refresh token:
   ```bash
   python scripts/generate_drive_refresh_token.py
   ```
4. Create a "Clients" root folder in Drive, grant the OAuth account access, and paste its folder ID into `GOOGLE_DRIVE_ROOT_FOLDER_ID` in `.env`

### 5. Frontend

```bash
cd frontend
npm install

# Only needed if frontend/backend are on different origins:
cp .env.example .env
# Set VITE_API_BASE_URL if needed (see .env.example comments)
```

---

## Running

### Development

**Backend** (terminal 1):
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

**Frontend** (terminal 2):
```bash
cd frontend
npm run dev
```

By default the app calls the backend directly through `VITE_API_BASE_URL`
(`http://localhost:8000` in the local `.env`). Alternatively, set
`VITE_API_URL` in `frontend/.env` to have the Vite dev server proxy `/api`
requests to that origin (for example `http://localhost:8000`).

### Create First Admin

```bash
cd backend
python -m app.create_admin
```
Password must be exactly 8 characters.

### Admin Route Protection

Every `/admin/*` page except `/admin/login` is wrapped by a `RequireAdmin` route
guard, which calls `GET /api/auth/me` first and only renders the page once the server
confirms an admin session — otherwise it redirects to
`/admin/login?redirect=<the page you wanted>`. This closes the gap where a
client-side navigation (e.g. the 404 page's "Back to dashboard" button) could
mount an admin page before its own API calls 401'd.

### Client Gallery Passwords (optional)

Gallery passwords are optional. Creating a client with the gallery password
left blank (or omitting it) produces a **passwordless gallery**: the client
landing page probes `GET /api/client/gallery/access/{gallery_id}`, skips the
password prompt when none is required, logs the visitor straight in with an
empty-password login, and opens the gallery. A password-protected gallery
always rejects a missing or wrong password. Admins can set, change, or remove
a gallery password later — removal (`password: null` on the change-password
endpoint) clears it and the gallery becomes passwordless again; `password_hash
IS NULL` is the passwordless state.

### Pre-Deploy Sanity Check

```bash
python scripts/check_env.py
```
Verifies DB connectivity, Drive token, writable ZIP temp dir, and FFmpeg availability. Exits nonzero on any failure.

---

## Book View (page-turning photo book)

A per-album, client-facing presentation mode: instead of the normal photo grid,
the album opens as a 3D book with an animated page turn. Reachable at

```
/gallery/:galleryId/view/:albumId/book
```

**Turning it on (admin):** Edit Album → **Book View** toggle, plus an **Album
layout** choice (`square`, `portrait`, `landscape`) that sets the aspect ratio
of the spread. Both save with the normal "Save changes" button
(`PUT /api/admin/albums/{id}`), and both ride on every album response
(`book_view_enabled`, `book_layout`). Once on, the client sees an **Open as
Book** button on that album and can also reach the reader at the URL above.

**Storage:** two columns on `albums` — `book_view_enabled` (boolean, default
`false` for every existing and new album) and `book_layout` (string, default
`landscape`). Applied with:

```bash
alembic upgrade head
```

**Behaviour:**

- Off by default — the studio must opt an album in; when off, the client only
  ever sees the normal grid, and the `/book` route redirects back to the album.
- Presentation only: it is not a security boundary. Book View calls the exact
  same client endpoints (`GET /api/client/albums/{id}`,
  `GET /api/client/media?album_id=`) the grid uses, so album ownership,
  expiry, and every other access check apply unchanged.
- One photo = one spread (left half on the left page, right half on the right
  page); videos turn as their poster and play in an overlay across the spread.
- Autoplay (5s per page, pausable), arrow keys / swipe / click zones, a page
  scrubber, and preloading of the next/previous few pages.
- Reads in the studio's saved book order (`media.sort_order`, id as tie-break);
  the client gallery defaults to the same "Book Order" sort, with Newest /
  Oldest / Name still available per visit.
- Honours `prefers-reduced-motion` (the book starts open, turns are instant).
- Loads the whole album up to a hard cap of 2000 items.

The reader is implemented in `frontend/src/pages/BookView.tsx`, with its styles in
`frontend/src/styles/book-view.css`.

### Book order (drag & drop)

The studio controls the page order from **Album media → Reorder book**. The
modal (`MediaOrderModal.tsx`) loads the whole album, reorders it by drag & drop
(up/down buttons for touch and keyboard), and saves the complete list with

```
PUT /api/admin/albums/{id}/media/order
```

Every album's media carries a 1-based `sort_order`; uploads and moves append at
the end. The same order drives the admin grid, the client gallery's default
"Book Order" sort, and Book View. The request must list every item exactly once
or it is rejected with `MEDIA_ORDER_INVALID`, and page notes are renumbered
alongside their photo so feedback stays on the right page. Applied with
`alembic upgrade head` (migration `d3a7c9e1b5f6`).

### Page notes (client feedback)

While reading in Book View, the client can leave one note on the page in front
of them: a note button sits in the toolbar (a dot marks pages that already have
one), and saving closes the sheet and turns to the next page.

- **Client:** only the note's own author and the studio can see it. Notes are
  tied to the signed-in client, the album, and a 1-based page number; a note is
  at most 2000 characters and editing it reopens it for review.
- **Admin:** the Albums list shows a note count per album. Open it (the small
  note button, or the ⋯ menu → **Page notes**) to see notes grouped by page with
  a thumbnail, filter by Open/Resolved, correct the text, mark resolved or
  reopen, and delete. Reviews keep working after an album expires.
- **Storage:** one `album_comments` table, with
  `UNIQUE(client_id, album_id, page_number)` so re-saving a page edits the same
  note. Deleting a photo leaves its note (without a thumbnail); deleting the
  album or client removes the notes. Applied with `alembic upgrade head`
  (migration `9b3f82e6a7c4`).

---

## Environment Variables

### Backend (`.env`)

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | MySQL connection string | — |
| `GOOGLE_DRIVE_CLIENT_ID` | OAuth2 client ID | — |
| `GOOGLE_DRIVE_CLIENT_SECRET` | OAuth2 client secret | — |
| `GOOGLE_DRIVE_REFRESH_TOKEN` | OAuth2 refresh token | — |
| `GOOGLE_DRIVE_ROOT_FOLDER_ID` | Drive folder ID for client storage | — |
| `SECRET_KEY` | Random string for session signing | — |
| `SESSION_TTL_MINUTES` | Session lifetime | `1440` |
| `CROSS_SITE_FRONTEND` | `true` if frontend on different origin | `false` |
| `CORS_ORIGINS` | Comma-separated allowed origins (forwarded to Drive to authorize browser direct-PUTs) | — |
| `DEV_FRONTEND_ORIGIN` | Local frontend origin used as the CORS fallback when `CORS_ORIGINS` is empty | — |
| `MAX_UPLOAD_SIZE_BYTES` | Max upload size | `10737418240` (10 GB) |
| `ALLOWED_IMAGE_TYPES` | Accepted image extensions | `jpg,jpeg,png,webp,gif` |
| `ALLOWED_VIDEO_TYPES` | Accepted video extensions | `mp4,mov,webm` |
| `ZIP_TEMP_DIR` | Temp directory for ZIP jobs | `/tmp/gallery_zip_jobs` (OS temp dir) |
| `ZIP_JOB_TTL_HOURS` | ZIP download link TTL | `24` |
| `ZIP_JOB_MAX_FILES` | Max files in one ZIP job | `5000` |
| `ZIP_JOB_PARALLEL_DOWNLOADS` | Concurrent file fetches while building a ZIP | `4` |
| `UPLOAD_MAX_CONCURRENT` | Max uploads actively transferring to Drive | `3` |
| `UPLOAD_MAX_CONCURRENT_REQUESTS` | Max uploads holding an admission slot (must be ≥ `UPLOAD_MAX_CONCURRENT`) | `8` |
| `UPLOAD_QUEUE_WAIT_SECONDS` | Wait for an admission slot before returning 503 | `45` |
| `UPLOAD_CHUNK_SIZE_MB` | Resumable chunk size, rounded to a 256 KiB multiple | `8` |
| `UPLOAD_MAX_RETRIES` | Retry attempts for transient Drive failures | `5` |
| `UPLOAD_INITIAL_BACKOFF_SECONDS` | Initial retry backoff | `0.5` |
| `UPLOAD_MAX_BACKOFF_SECONDS` | Maximum retry backoff | `20` |
| `UPLOAD_MAX_FILE_SIZE_MB` | Per-file size ceiling (the smaller of this and `MAX_UPLOAD_SIZE_BYTES` wins) | `10240` |
| `UPLOAD_MIN_FREE_DISK_GB` | Free disk required before accepting an upload | `5` |
| `UPLOAD_CHUNK_TIMEOUT` | Per-chunk network timeout | `120` |
| `UPLOAD_SESSION_TIMEOUT` | Overall transfer deadline for one upload | `3600` |
| `ORPHAN_FILE_GRACE_PERIOD_HOURS` | Age before an unmatched Drive file is considered an orphan | `48` |
| `THUMBNAIL_IMAGE_SOURCE_MAX_MB` | Largest photo the server will read back to build a fallback thumbnail | `25` |
| `VIDEO_THUMBNAIL_UPLOAD_MAX_KB` | Max browser-uploaded video poster size | `2048` |
| `ENVIRONMENT` | `development` or `production` | `development` |

See `backend/app/config/settings.py` for the complete settings model and
`backend/.env.example` for a starting template. Note that for direct-to-Drive
uploads, your frontend origin (e.g. `http://localhost:5173`) must be present in
`CORS_ORIGINS` (or supplied via `DEV_FRONTEND_ORIGIN` when `CORS_ORIGINS` is
empty) so the backend can authorize the browser's origin with Google Drive when
opening resumable upload sessions.


### Frontend (`.env`)

| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | Backend origin URL baked into API requests (e.g. `https://api.yourdomain.com`); required when frontend and backend are on different origins |
| `VITE_API_URL` | Optional dev-server proxy target for `/api` (e.g. `http://localhost:8000`); used only by `vite.config.ts` |

---

## Cron Jobs

Run these periodically via crontab or your process manager:

```bash
# Clean up expired ZIP download files
python -m app.cleanup_download_jobs

# Delete orphaned Drive files (dry-run first, then --apply)
python -m app.reconcile_orphans --apply
```

---

## Testing

```bash
cd backend
pytest
```

23 test files covering auth (including the optional gallery-password flow),
authorization & cross-client isolation, client search & selection summaries,
admin/client/album management, album expiry, media management (search,
pagination, metadata edits, move, delete), bulk operations, gallery totals,
ZIP download jobs & analytics, upload hardening (idempotency, disk reservations,
concurrency limits, stale-session recovery, orphan reconciliation), thumbnails &
streaming (range requests, 416s, concurrency), the server-side thumbnail
fallback, the thumbnail-folder migration, the dashboard, storage integration
(Drive folder provisioning, storage overview), Drive folder naming, direct
resumable uploads, FFmpeg availability, the httplib2 cleanup-bug regression,
studio settings/security policy (incl. self-service admin password change),
page notes (`test_comments.py`: upsert, cross-client isolation, validation,
expiry, admin review, album counts), and book order (`test_media_order.py`:
reorder, client-side ordering, complete-list validation, note renumbering,
move-to-end, admin-only access).

Tests use an in-memory SQLite database and `FakeStorageService` — no real Drive calls.

> **Suite status:** 192 pass, 107 fail (299 total). A large part of the suite still drives the retired
> byte-relay `POST /api/admin/media/upload` route, which no longer exists in
> the direct-to-Drive app, so those tests currently fail. The original upload path under the current architecture is covered at
> the storage layer (`test_drive_resumable_upload.py`) and the session/ledger
> layer (`test_upload_hardening.py`).
>
> Caveat: the suite runs on SQLite, so it will happily compile SQL that MySQL 8
> rejects. `count(...) FILTER (WHERE ...)` passes here and returns a 1064 in
> production — which is why `media_aggregates.py` exists. A green run is not
> proof a query works on the real database.

---

## Deployment

```bash
# Backend
cd backend
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm run build    # outputs to dist/
```

Serve the frontend static files from the same origin as the backend (via reverse proxy like Nginx) or from a separate host (set `CROSS_SITE_FRONTEND=true` and `CORS_ORIGINS`).

### Production origins

| | Origin |
|---|---|
| Frontend | `http://lovestoryphotography.in` |
| Backend | `https://api.madgen.space` |

They are on different origins, so `CROSS_SITE_FRONTEND=true` and the backend's `CORS_ORIGINS` must contain the frontend origin — that same allowlist is what authorizes the browser's direct PUTs to Google Drive during upload.

`vercel.json` hosts the frontend (SPA rewrite, `/api` proxy to the backend, security headers). The frontend domain also appears in `public/sitemap.xml` and `public/robots.txt`; update all three together when it changes. Serve it over `https://` — sitemap `<loc>` and `robots.txt` `Sitemap:` entries are conventionally `https`, and search engines flag `http://` there.

### Branding

`frontend/public/ls-logo.png` is the single studio logo. It is the favicon (`index.html`), the admin header avatar (`AdminDashboard.tsx`, replacing a hard-coded `L` initial), and the Home landing-page mark (`Home.tsx`) — referenced by absolute URL from `public/` rather than imported, so it isn't hashed or duplicated into the JS bundle.

The shared `PoweredBy` component renders the `Powered by madgen` credit line (with the build's
version and date) on the Home footer, both login cards, and the base of the admin sidebar.

---

## License

Private — not for redistribution.
