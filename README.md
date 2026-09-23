# LoveStory PH — Private Wedding Gallery Platform

A private gallery platform for wedding photographers to manage clients, albums, and media. Two interfaces: an **admin panel** for the studio and a **client gallery** for viewing/downloading photos and videos.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite 5, React Router 6 |
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
- **Node.js 18+** and npm
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
│   │   ├── models/           # 11 ORM models
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── security/         # Password hashing, sessions, encryption
│   │   ├── services/         # Business logic layer (storage, direct upload, validation, etc.)
│   │   ├── workers/          # Thumbnail worker (PIL + FFmpeg fallback)
│   │   ├── main.py           # App factory, lifespan, middleware
│   │   ├── create_admin.py   # First admin bootstrap
│   │   ├── reconcile_orphans.py      # Cron: Drive orphan cleanup
│   │   └── cleanup_download_jobs.py  # Cron: expired ZIP cleanup
│   ├── scripts/              # check_env.py, generate_drive_refresh_token.py
│   ├── alembic/              # Database migrations
│   ├── tests/                # pytest test files + conftest/fakes
│   ├── .env.example          # Backend config template
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/       # Shared UI (AdminLayout, Sidebar, Lightbox, GlobalUploadBadge)
│   │   ├── contexts/         # React Contexts (UploadContext - persistent background queue)
│   │   ├── pages/            # Admin + Client pages
│   │   ├── services/         # Typed API client (auth, admin, gallery)
│   │   ├── styles/           # Plain CSS (index.css, admin.css, gallery.css)
│   │   ├── utils/            # format.ts, photoThumbnail.ts, videoPoster.ts
│   │   ├── App.tsx           # Route definitions
│   │   └── main.tsx          # Entry point
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

The Vite dev server proxies `/api` requests to `http://localhost:8000`.

### Create First Admin

```bash
cd backend
python -m app.create_admin
```
Password must be exactly 8 characters.

### Client Gallery Passwords (optional)

Gallery passwords are optional. Creating a client with the gallery password
left blank (or omitting it) produces a **passwordless gallery**: the client
landing page probes `GET /api/client/gallery/access/{gallery_id}`, skips the
password prompt when none is required, logs the visitor straight in with an
empty-password login, and opens the gallery. A password-protected gallery
always rejects a missing or wrong password. Admins can always set or change a
gallery password later (once set, it can't be blanked again — only the
download password can be cleared); `password_hash IS NULL` is the
passwordless state.

### Pre-Deploy Sanity Check

```bash
python scripts/check_env.py
```
Verifies DB connectivity, Drive token, writable ZIP temp dir, and FFmpeg availability. Exits nonzero on any failure.

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
| `MAX_UPLOAD_SIZE_BYTES` | Max upload size | `10737418240` (10GB) |
| `ZIP_TEMP_DIR` | Temp directory for ZIP jobs | `/tmp/gallery_zip_jobs` |
| `ZIP_JOB_TTL_HOURS` | ZIP download link TTL | `24` |
| `UPLOAD_MAX_CONCURRENT` | Max simultaneous Drive uploads | `3` |
| `COVER_UPLOAD_MAX_KB` | Max size of the browser-generated automatic cover image a single request may send | `4096` |
| `ENVIRONMENT` | `development` or `production` | `development` |

See `backend/.env.example` for the full list with descriptions. Note that for direct-to-Drive uploads, your frontend origin (e.g. `http://localhost:5173`) must be present in `CORS_ORIGINS` so the backend can authorize the browser's origin with Google Drive when opening resumable upload sessions.


### Frontend (`.env`) — only if different origin

| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | Backend origin URL (e.g. `https://api.yourdomain.com`) |

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

18 test files covering auth (including the optional gallery-password flow),
authorization & cross-client isolation, client search & selection summaries,
admin/client/album management, album expiry, media management (search,
pagination, metadata edits, move, delete), bulk operations, ZIP download jobs
& analytics, upload hardening (idempotency, disk reservations, concurrency
limits, stale-session recovery, orphan reconciliation), thumbnails & streaming
(range requests, 416s, concurrency), the dashboard, storage integration (Drive
folder provisioning, storage overview), Drive folder naming, direct resumable
uploads, FFmpeg availability, the httplib2 cleanup-bug regression, and studio
settings/security policy (incl. self-service admin password change).

Tests use an in-memory SQLite database and `FakeStorageService` — no real Drive calls.

> **Suite status:** a large part of the suite still drives the retired
> byte-relay `POST /api/admin/media/upload` route, which no longer exists in
> the direct-to-Drive app, so those tests currently fail (~145 pass, ~107
> fail). The original upload path under the current architecture is covered at
> the storage layer (`test_drive_resumable_upload.py`) and the session/ledger
> layer (`test_upload_hardening.py`).

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

---

## License

Private — not for redistribution.
