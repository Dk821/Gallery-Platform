"""
Maps pre-multi-studio data to a studio. DRY RUN unless --apply is given.

    # 1) See what is unmapped (changes nothing)
    python -m app.legacy_to_studio

    # 2) Preview mapping everything to an EXISTING studio
    python -m app.legacy_to_studio --studio-id 1

    # 3) Create the studio and map everything to it, in one go
    python -m app.legacy_to_studio --create-studio "LoveStory PH" \\
        --quota-bytes 50000000000 --contact-email hello@example.com --apply

    # Several businesses on one legacy install: map subsets of clients
    python -m app.legacy_to_studio --studio-id 2 --client-ids 4,5,6 --admin-ids 3 --apply

The first studio admin account for a NEW studio is created through the
super-admin API (POST /api/super-admin/studios) - this command only maps
EXISTING admins, clients and their data.
"""

import argparse
import json
import sys

from app.config.settings import get_settings
from app.database.connection import SessionLocal
from app.models.studio import Studio
from app.services.legacy_mapping import LegacyMappingError, map_legacy_to_studio, report_unmapped
from app.services.storage_paths import build_studio_prefix
from app.services.studio_slug import build_studio_slug


def _ids(value: str | None) -> list[int] | None:
    if value is None:
        return None
    return [int(v) for v in value.split(",") if v.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Map legacy single-studio data to a studio.")
    parser.add_argument("--studio-id", type=int)
    parser.add_argument("--create-studio", metavar="NAME", help="create a new studio with this name and map to it")
    parser.add_argument("--quota-bytes", type=int, help="quota for --create-studio (default: DEFAULT_STUDIO_QUOTA_BYTES)")
    parser.add_argument("--contact-email")
    parser.add_argument("--client-ids", help="comma-separated; map only these clients (and their data)")
    parser.add_argument("--admin-ids", help="comma-separated; map only these admins")
    parser.add_argument("--apply", action="store_true", help="actually write changes (default: dry run)")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.studio_id is None and not args.create_studio:
            print(json.dumps(report_unmapped(db), indent=2))
            print("\nNothing changed. Choose a target with --studio-id N or --create-studio NAME.", file=sys.stderr)
            return 0

        studio_id = args.studio_id
        if args.create_studio:
            if not args.apply:
                print(f"[dry run] would create studio {args.create_studio!r} and map to it.")
                studio_id = -1
            else:
                studio = Studio(
                    slug=build_studio_slug(db, args.create_studio.strip()),
                    name=args.create_studio.strip(),
                    contact_email=args.contact_email,
                    status="active",
                    quota_bytes=args.quota_bytes or get_settings().default_studio_quota_bytes,
                    used_bytes=0,
                    reserved_bytes=0,
                )
                # flush, not commit: the studio only becomes permanent if the
                # mapping below also succeeds (one transaction).
                db.add(studio)
                db.flush()
                studio.storage_prefix = build_studio_prefix(studio.name, studio.id)
                studio_id = studio.id

        if studio_id == -1:
            print(json.dumps(report_unmapped(db), indent=2))
            return 0

        plan = map_legacy_to_studio(
            db, studio_id, client_ids=_ids(args.client_ids), admin_ids=_ids(args.admin_ids), apply=args.apply
        )
        if args.create_studio and args.apply:
            print(f"Created studio {studio_id} ({args.create_studio.strip()}).")
        print(json.dumps(plan, indent=2))
        if not args.apply:
            print("\nDry run - nothing changed. Re-run with --apply to write.", file=sys.stderr)
        return 0
    except LegacyMappingError as exc:
        db.rollback()  # also discards a studio created by this run
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
