"""
Usage:
    python -m app.reconcile_quota                       # report drift only (default)
    python -m app.reconcile_quota --apply               # repair counters from the real rows
    python -m app.reconcile_quota --studio-id 3         # limit to one studio
    python -m app.reconcile_quota --verify-objects      # ALSO compare recorded sizes with the storage provider
    python -m app.reconcile_quota --verify-objects --limit 5000

Safe to run repeatedly (e.g. from cron, nightly, report-only; add --apply only
when you have looked at a report). Exit code 1 when drift is found and not
repaired, so a monitoring job can alert on it.
"""

import argparse
import json
import sys

from app.database.connection import SessionLocal
from app.services.quota_reconciliation import reconcile_quota, verify_objects
from app.services.storage_provider import get_storage_service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile studio storage counters with the database and storage.")
    parser.add_argument("--apply", action="store_true", help="repair counters (default: report only)")
    parser.add_argument("--studio-id", type=int, default=None)
    parser.add_argument("--verify-objects", action="store_true", help="compare recorded sizes with the provider")
    parser.add_argument("--limit", type=int, default=1000, help="max media rows to verify (default 1000)")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        result = reconcile_quota(db, apply=args.apply, studio_id=args.studio_id)
        if args.verify_objects:
            result["object_verification"] = verify_objects(
                db, get_storage_service(), studio_id=args.studio_id, limit=args.limit
            )
        print(json.dumps(result, indent=2, default=str))
        drift = result["studios_out_of_sync"] > 0 or not result["platform"]["in_sync"]
        if drift and not args.apply:
            print("\nDrift found. Re-run with --apply to repair the counters.", file=sys.stderr)
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
