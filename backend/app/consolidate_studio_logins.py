"""
Find and safely consolidate studios that have more than one studio-admin login.

One studio = one studio login. Studios created before that rule may still have several
admin accounts. This tool NEVER decides for you and NEVER deletes by default.

    # 1. Report only (default) - lists every studio with more than one login and their accounts:
    python -m app.consolidate_studio_logins

    # 2. Choose the account each studio keeps and see what would happen (still changes nothing):
    python -m app.consolidate_studio_logins --keep 4:8 --keep 6:12

    # 3. Apply. Every other account is disabled, signed out everywhere (sessions revoked), has its
    #    held upload reservations released and is UNASSIGNED from the studio - the row is kept:
    python -m app.consolidate_studio_logins --keep 4:8 --keep 6:12 --apply

    # Optional: --keep-oldest / --keep-newest decide for every studio you did not name with --keep.
    # Optional: --action delete removes the other accounts for good (explicit, asks for --yes).

When no studio has more than one login any more, the unique database index that enforces the rule
is created automatically (or run `--ensure-index` on its own). Clients, albums, media and storage
objects are never touched.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.database.connection import SessionLocal, engine
from app.services import studio_login_service as svc


def _parse_keep(values: list[str]) -> dict[int, int]:
    keep: dict[int, int] = {}
    for v in values:
        try:
            sid, aid = v.split(":", 1)
            keep[int(sid)] = int(aid)
        except ValueError:
            raise SystemExit(f"--keep expects STUDIO_ID:ADMIN_ID, got {v!r}")
    return keep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Consolidate studios that have more than one studio login.")
    ap.add_argument("--keep", action="append", default=[], metavar="STUDIO_ID:ADMIN_ID", help="the account a studio keeps (repeatable)")
    ap.add_argument("--keep-oldest", action="store_true", help="for studios not named with --keep, keep the oldest account")
    ap.add_argument("--keep-newest", action="store_true", help="for studios not named with --keep, keep the newest account")
    ap.add_argument("--action", choices=svc.ACTIONS, default="detach", help="what happens to the other accounts (default: detach = disable + unassign, row kept)")
    ap.add_argument("--apply", action="store_true", help="actually write changes (default: report / dry run)")
    ap.add_argument("--yes", action="store_true", help="required together with --action delete --apply")
    ap.add_argument("--ensure-index", action="store_true", help="only create the unique index if every studio is clean")
    args = ap.parse_args(argv)

    if args.keep_oldest and args.keep_newest:
        raise SystemExit("Choose either --keep-oldest or --keep-newest, not both.")
    strategy = "oldest" if args.keep_oldest else "newest" if args.keep_newest else None

    if args.ensure_index:
        print(f"unique index: {svc.ensure_unique_index(engine)}")
        return 0

    db = SessionLocal()
    try:
        dupes = svc.find_duplicates(db)
        if not dupes:
            print("No studio has more than one login. Nothing to clean up.")
            print(f"unique index: {svc.ensure_unique_index(engine)}")
            return 0

        keep = _parse_keep(args.keep)
        if not keep and strategy is None:
            print(json.dumps({"studios_with_multiple_logins": dupes}, indent=2))
            print(
                "\nReport only - nothing changed. Choose the account each studio keeps, e.g.\n"
                "  python -m app.consolidate_studio_logins --keep STUDIO_ID:ADMIN_ID [--keep ...] --apply",
                file=sys.stderr,
            )
            return 0

        try:
            keepers = svc.pick_keepers(dupes, keep, strategy)
        except svc.ConsolidationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

        plan = []
        for entry in dupes:
            kept = keepers[entry["studio_id"]]
            plan.append(
                {
                    "studio_id": entry["studio_id"],
                    "keep": kept,
                    "others": [a for a in entry["accounts"] if a["id"] != kept],
                    "action": args.action,
                }
            )
        print(json.dumps({"plan": plan}, indent=2))

        if not args.apply:
            print("\nDry run - nothing changed. Re-run with --apply to write.", file=sys.stderr)
            return 0
        if args.action == "delete" and not args.yes:
            print("ERROR: --action delete removes accounts for good; add --yes to confirm.", file=sys.stderr)
            return 2

        try:
            done = svc.consolidate(db, keepers, action=args.action)
        except svc.ConsolidationError as exc:
            db.rollback()
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"applied": done}, indent=2))
        print(f"unique index: {svc.ensure_unique_index(engine)}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
