# System requirements (outside `requirements.txt`)

Everything in `requirements.txt` is a Python package `pip` can install. This
file covers the one external dependency that **isn't**: a system binary that may
optionally be installed at the OS level.

## ffmpeg (optional — server-side poster backfill tooling)

**Current Status: Optional.**

In the current direct-to-Drive upload architecture, **video poster frames (and photo thumbnails) are generated client-side by the browser during upload** (`frontend/src/utils/videoPoster.ts` and `photoThumbnail.ts`) using HTML5 `<video>` / `<img>` and `<canvas>`, then uploaded directly to `POST /api/admin/media/upload-session/{id}/thumbnail` as lightweight WebP images. Because of this, the server never has to read a multi-GB video file from Google Drive to generate a poster, and uploads do not require FFmpeg on the server.

**What it's for on the server:**
- Serves as backfill tooling (`app/workers/thumbnail_worker.py:generate_video_poster`) for administrative scripts or future tasks to generate poster frames for videos that were uploaded without one.
- Evaluated during the application boot probe and reported in `GET /api/health` and the admin dashboard (`ffmpeg_available`).

**What happens if it's missing:**
Nothing breaks. Video uploads continue to succeed normally with browser-extracted thumbnails. If a browser cannot extract a frame (e.g. unsupported client codec) and FFmpeg is not installed on the server, the gallery grid simply falls back to a placeholder icon for that video.

**How to check if it's already installed:**
```bash
ffmpeg -version
```
or check `GET /api/health` once the app is running — it returns `"ffmpeg_available": true/false`. Logged-in admins also see this on the dashboard (`ffmpeg_available` field). The app logs an informational message at startup if ffmpeg isn't found.

**How to install it (if server-side backfill capability is desired):**

- **Debian/Ubuntu (most VPS deployments):**
  ```bash
  sudo apt-get update && sudo apt-get install -y ffmpeg
  ```
- **Docker:** add to your Dockerfile, e.g. for a `python:3.12-slim` base:
  ```dockerfile
  RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
      && rm -rf /var/lib/apt/lists/*
  ```
- **macOS (local dev):**
  ```bash
  brew install ffmpeg
  ```
- **RHEL/CentOS/Amazon Linux:**
  ```bash
  sudo dnf install -y ffmpeg   # or: sudo yum install -y ffmpeg (needs EPEL/RPM Fusion)
  ```

No specific version is required — any reasonably recent ffmpeg build (4.x+) works fine; the app only uses it to extract a single frame at ~1 second into the video (`-ss 1 -frames:v 1`).

