# System requirements (outside `requirements.txt`)

Everything in `requirements.txt` is a Python package `pip` can install. This
file covers the one dependency that **isn't**: a system binary that has to
be installed at the OS level before deploying this app.

## ffmpeg (required for video thumbnails)

**What it's for:** generating the poster/thumbnail image shown in the
gallery grid for uploaded videos (`app/workers/thumbnail_worker.py`).

**What happens if it's missing:** nothing breaks. Video uploads still
succeed and the original file still streams/plays fine - only the poster
frame is skipped, and the gallery grid falls back to a placeholder icon for
videos. This is deliberate (a missing thumbnail should never fail an
upload) but it's easy to not notice until a client asks "why don't my
videos have a preview picture?"

**How to check if it's already installed:**
```bash
ffmpeg -version
```
or check `GET /api/health` once the app is running - it returns
`"ffmpeg_available": true/false`. Logged-in admins also see this on the
dashboard (`ffmpeg_available` field). The app also logs a loud warning at
startup if ffmpeg isn't found, so `journalctl`/your process manager's log
output will flag it immediately on boot.

**How to install it:**

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

No specific version is required - any reasonably recent ffmpeg build (4.x+)
works fine; the app only uses it to grab a single frame at ~1 second into
the video (`-ss 1 -frames:v 1`).
