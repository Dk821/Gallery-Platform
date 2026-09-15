"""
Usage (intended to be run via cron, e.g. every 15-30 minutes):
    python -m app.cleanup_download_jobs

Removes expired ZIP files from disk and flips their DownloadJob rows to
"expired" (the row itself is kept for history). Consistent with how this
project handles MySQL backups (Section 43): a cron entry on the VPS, not
app-internal scheduling infrastructure - see Section 46's "don't
overengineer the MVP."

Suggested crontab entry:
    */15 * * * * cd /path/to/backend && /path/to/venv/bin/python -m app.cleanup_download_jobs >> /var/log/gallery-cleanup.log 2>&1
"""

import sys

from app.database.connection import SessionLocal
from app.services.download_job_service import cleanup_expired_download_jobs


def main() -> None:
    db = SessionLocal()
    try:
        count = cleanup_expired_download_jobs(db)
        print(f"Cleaned up {count} expired download job(s).")
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Cleanup failed: {exc}", file=sys.stderr)
        sys.exit(1)
