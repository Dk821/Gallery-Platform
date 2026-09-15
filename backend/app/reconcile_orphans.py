"""
Usage (intended to be run via cron, e.g. daily):
    python -m app.reconcile_orphans            # dry run - detect & log only
    python -m app.reconcile_orphans --apply     # actually delete confirmed orphans

Finds Drive files that were successfully uploaded but never got a
matching Media row (Section 9 - e.g. the VPS crashed between "Drive
accepted the file" and "we saved the DB record"), logs them, and - only
with --apply - deletes the confirmed orphans after a grace period
(ORPHAN_FILE_GRACE_PERIOD_HOURS) so an upload that's still legitimately in
flight is never mistaken for one that's abandoned. Follows the same
cron-not-app-scheduler pattern as cleanup_download_jobs.py.

Suggested crontab entry (dry run first, add --apply once you trust it):
    0 4 * * * cd /path/to/backend && /path/to/venv/bin/python -m app.reconcile_orphans --apply >> /var/log/gallery-orphan-reconciliation.log 2>&1
"""

import sys

from app.config.settings import get_settings
from app.database.connection import SessionLocal
from app.services.orphan_reconciliation import reconcile_orphans
from app.services.storage_provider import get_storage_service


def main() -> None:
    apply = "--apply" in sys.argv[1:]
    settings = get_settings()
    db = SessionLocal()
    try:
        storage = get_storage_service()
        result = reconcile_orphans(db, storage, settings.orphan_file_grace_period_hours, dry_run=not apply)
        mode = "APPLY" if apply else "DRY RUN"
        print(
            f"[{mode}] candidates={result['candidates']} confirmed={len(result['confirmed'])} "
            f"deleted={len(result['deleted'])} cleanup_failed={len(result['cleanup_failed'])} "
            f"still_valid={len(result['still_valid'])}"
        )
        if result["cleanup_failed"]:
            print(
                f"WARNING: {len(result['cleanup_failed'])} confirmed orphan(s) could not be deleted "
                "- manual reconciliation required. See application logs for details.",
                file=sys.stderr,
            )
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Orphan reconciliation failed: {exc}", file=sys.stderr)
        sys.exit(1)
