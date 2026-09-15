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
| Storage | Google Drive v3 API (service account) |
| Video Processing | FFmpeg (system binary) |
| Image Processing | Pillow |
| Auth | Argon2 (passwords), itsdangerous (admin tokens), Fernet (reversible encryption) |

---

## Prerequisites

- **Python 3.12+**
- **Node.js 18+** and npm
- **MySQL 8**
- **FFmpeg** (installed at OS level, required for video thumbnail generation — see below)
- **Google Drive API** credentials (OAuth2 service account with Drive access)

### FFmpeg (required for video thumbnails)

Used to extract poster frames from uploaded videos. Without it, video uploads still work but videos show a placeholder icon instead of a preview thumbnail.

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
│   │   ├── api/              # Route handlers
│   │   ├── config/           # pydantic-settings (.env loader)
│   │   ├── database/         # SQLAlchemy engine, session, Base
│   │   ├── models/           # 10 ORM models
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── security/         # Password hashing, sessions, encryption
│   │   ├── services/         # Business logic layer
│   │   ├── workers/          # Thumbnail generation (PIL + FFmpeg)
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
│   │   ├── components/       # Shared UI (AdminLayout, Sidebar, Lightbox)
│   │   ├── pages/            # Admin + Client pages
│   │   ├── services/         # Typed API client
│   │   ├── styles/           # Plain CSS (index.css, admin.css, gallery.css)
│   │   ├── utils/            # Formatters
│   │   ├── App.tsx           # Route definitions
│   │   └── main.tsx          # Entry point
│   ├── .env.example          # Frontend config template
│   └── package.json
├── ARCHITECTURE.md
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
| `CORS_ORIGINS` | Comma-separated allowed origins | — |
| `MAX_UPLOAD_SIZE_BYTES` | Max upload size | `10737418240` (10GB) |
| `ZIP_TEMP_DIR` | Temp directory for ZIP jobs | `/tmp/gallery_zip_jobs` |
| `ZIP_JOB_TTL_HOURS` | ZIP download link TTL | `24` |
| `UPLOAD_MAX_CONCURRENT` | Max simultaneous Drive uploads | `3` |
| `ENVIRONMENT` | `development` or `production` | `development` |

See `backend/.env.example` for the full list with descriptions.

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

18 test files covering auth, authorization, client search, admin management, album expiry, media management, bulk ops, download jobs/analytics, upload hardening, thumbnails/streaming, dashboard, storage integration, Drive folder naming, resumable uploads, FFmpeg availability, httplib2 cleanup-bug regression, and studio settings.

Tests use an in-memory SQLite database and `FakeStorageService` — no real Drive calls.

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
