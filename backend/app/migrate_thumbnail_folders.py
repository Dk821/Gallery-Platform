"""
Usage:
    python -m app.migrate_thumbnail_folders            # dry run - report only
    python -m app.migrate_thumbnail_folders --apply    # actually rename + purge

Finishes the Drive-side half of alembic revision a5c7e3b1d9f8, which renamed
the `cover_folder_id` column but could not rename the Drive folder itself: a
schema migration has no Drive credentials, so clients created before the
cover feature was removed still have a folder named "Cover Images" holding
their thumbnails, while every new client gets one called "Thumbnails".

Run dry first and read the output. Nothing here is destructive to anything
that matters - the rename is metadata-only (same folder id, so every
existing thumbnail keeps resolving) and the only file deleted is the
removed cover's `cover.webp`, which no column references any more.

Safe to run more than once: a folder already named "Thumbnails" is skipped,
and a `cover.webp` that is already gone simply isn't found.
"""

import sys

from app.database.connection import SessionLocal
from app.services.folder_naming import LEGACY_COVER_FOLDER_NAME, THUMBNAIL_FOLDER_NAME
from app.services.storage_provider import get_storage_service
from app.services.thumbnail_folder_migration import migrate_client_thumbnail_folders


def main() -> None:
    apply = "--apply" in sys.argv[1:]
    db = SessionLocal()
    try:
        storage = get_storage_service()
        result = migrate_client_thumbnail_folders(db, storage, dry_run=not apply)
        mode = "APPLY" if apply else "DRY RUN"
        print(
            f"[{mode}] scanned={result['clients_scanned']} "
            f"renamed={len(result['renamed'])} "
            f"already_current={len(result['already_current'])} "
            f"covers_deleted={len(result['covers_deleted'])} "
            f"dangling_cleared={len(result['dangling_cleared'])} "
            f"unexpected={len(result['unexpected'])} "
            f"failed={len(result['failed'])}"
        )
        if result["dangling_cleared"] and apply:
            print(
                f"NOTE: cleared a dangling thumbnail folder for client(s) "
                f"{result['dangling_cleared']} - it had been deleted from Drive. "
                "It will be recreated under the correct name on their next upload."
            )
        if result["unexpected"]:
            print(
                f"WARNING: these clients' thumbnail folders are not named "
                f"{THUMBNAIL_FOLDER_NAME!r} or {LEGACY_COVER_FOLDER_NAME!r} and were left "
                f"untouched: {result['unexpected']}. Their thumbnails still resolve (the "
                "folder is addressed by id, not name) - rename them by hand if "
                "that is unexpected.",
                file=sys.stderr,
            )
        if result["failed"]:
            print(
                f"WARNING: {len(result['failed'])} client(s) could not be migrated "
                "- see application logs. Re-running this command is safe.",
                file=sys.stderr,
            )
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Thumbnail folder migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
