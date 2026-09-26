"""
One-shot ops pass that finishes the rename started by alembic revision
a5c7e3b1d9f8 ("replace the client cover columns with a single thumbnail
folder column").

That migration could only do half the job, and said so in its own docstring:
it renamed the `cover_folder_id` COLUMN, but the Drive folder it points at is
still *named* "Cover Images" for every client created before the change, while
new clients get a folder called "Thumbnails". So the same logical folder - the
one every item thumbnail in the gallery lives in - ended up with two different
names in Drive depending on when the client was created, and the code only
ever knew one of them.

Nothing is broken by that, which is why this is an ops task and not a bug fix:
the folder is addressed by the id on `Client.thumbnail_folder_id` everywhere in
the request-serving path, never by name, so every existing thumbnail resolves
exactly as before. This pass exists purely so the name in Drive matches what
the code calls the folder, and so the removed cover's leftover bytes are
reclaimed.

What it does, per client that has a thumbnail folder recorded:

  1. Reads the folder's current name from Drive.
  2. If it is already "Thumbnails", there is nothing to do.
  3. If it is "Cover Images" (the legacy name), renames it to "Thumbnails".
     rename_folder() is metadata-only, so the folder id - and therefore every
     thumbnail already inside it - is untouched. No DB write is needed or
     wanted: `thumbnail_folder_id` already holds this id and does not change.
  4. Deletes a leftover `cover.webp` from the folder. That file is the removed
     automatic cover: unreferenced since `cover_drive_file_id` was dropped, and
     unambiguously identifiable because item thumbnails are always named
     `thumb_{uuid}.webp` (see media_service). As a belt-and-braces guard, a
     file by that name is still skipped if any Media row references its id as
     a thumbnail - so a surprise can never turn into a broken image.
  5. If the folder is gone from Drive entirely, clears the now-dangling
     `thumbnail_folder_id` so the next upload lazily recreates it under the
     correct name, rather than every future upload failing against a deleted
     folder.

Runs dry by default; pass --apply to write anything. Per-client failures are
recorded and the pass continues, so one bad folder can't strand the rest, and
the summary printed at the end reports exactly what was and wasn't done.
"""

import logging

from sqlalchemy.orm import Session as DbSession

from app.models.client import Client
from app.models.media import Media
from app.services.folder_naming import (
    LEGACY_COVER_FILE_NAME,
    LEGACY_COVER_FOLDER_NAME,
    THUMBNAIL_FOLDER_NAME,
)
from app.services.storage_service import StorageError, StorageNotFoundError, StorageService
from app.services.upload_logging import log_event

logger = logging.getLogger("gallery.storage.thumbnail_folder_migration")


def _is_still_referenced(db: DbSession, drive_file_id: str) -> bool:
    """
    True if any Media row still points at this Drive file as a thumbnail.
    The legacy `cover.webp` should never match (nothing references it once
    cover_drive_file_id is gone), but checking costs one indexed query and
    makes deleting a file that IS still serving an image impossible.
    """
    return (
        db.query(Media.id).filter(Media.thumbnail_reference == drive_file_id).first() is not None
    )


def migrate_client_thumbnail_folders(db: DbSession, storage: StorageService, *, dry_run: bool = True) -> dict:
    """
    Renames every legacy "Cover Images" folder to "Thumbnails" and purges the
    orphaned cover from it. Returns a summary dict; writes nothing at all when
    dry_run=True.
    """
    clients = (
        db.query(Client).filter(Client.thumbnail_folder_id.isnot(None)).order_by(Client.id).all()
    )

    renamed: list[int] = []
    already_current: list[int] = []
    covers_deleted: list[str] = []
    dangling_cleared: list[int] = []
    unexpected: list[tuple[int, str]] = []
    failed: list[tuple[int, str]] = []

    for client in clients:
        folder_id = client.thumbnail_folder_id
        try:
            current_name = storage.get_file(folder_id).name
        except StorageNotFoundError:
            # The folder was deleted by hand (or trashed). Forget it so
            # _ensure_thumbnail_folder() lazily recreates a correctly-named
            # one on the next upload, instead of every future thumbnail
            # upload failing against an id that no longer resolves.
            if not dry_run:
                db.query(Client).filter(Client.id == client.id).update(
                    {Client.thumbnail_folder_id: None}, synchronize_session=False
                )
                db.commit()
            dangling_cleared.append(client.id)
            log_event(
                logger,
                "thumbnail_folder.dangling_cleared",
                logging.WARNING,
                client_id=client.id,
                folder_id=folder_id,
                dry_run=dry_run,
            )
            continue
        except StorageError as exc:
            failed.append((client.id, str(exc)))
            log_event(
                logger,
                "thumbnail_folder.lookup_failed",
                logging.ERROR,
                client_id=client.id,
                folder_id=folder_id,
                error=str(exc),
            )
            continue

        if current_name == THUMBNAIL_FOLDER_NAME:
            already_current.append(client.id)
            continue

        if current_name != LEGACY_COVER_FOLDER_NAME:
            # Not a name this app ever created. Renaming it would be guessing
            # at somebody else's folder, so report it and leave it alone -
            # the id is what matters, and it works regardless of the name.
            unexpected.append((client.id, current_name))
            log_event(
                logger,
                "thumbnail_folder.unexpected_name",
                logging.WARNING,
                client_id=client.id,
                folder_id=folder_id,
                current_name=current_name,
            )
            continue

        if not dry_run:
            try:
                storage.rename_folder(folder_id, THUMBNAIL_FOLDER_NAME)
            except StorageError as exc:
                failed.append((client.id, str(exc)))
                log_event(
                    logger,
                    "thumbnail_folder.rename_failed",
                    logging.ERROR,
                    client_id=client.id,
                    folder_id=folder_id,
                    error=str(exc),
                )
                continue

            log_event(
                logger,
                "thumbnail_folder.renamed",
                client_id=client.id,
                folder_id=folder_id,
                old_name=LEGACY_COVER_FOLDER_NAME,
                new_name=THUMBNAIL_FOLDER_NAME,
            )

        renamed.append(client.id)

        # Listed in both modes so a dry run reports the full blast radius
        # (which covers would go) rather than looking like a no-op - that's
        # the whole reason to run it dry first. Only the legacy filename
        # qualifies: a thumbnail-named file is never touched.
        try:
            for entry in storage.list_folder_contents(folder_id):
                if entry.name != LEGACY_COVER_FILE_NAME:
                    continue
                if _is_still_referenced(db, entry.provider_file_id):
                    log_event(
                        logger,
                        "thumbnail_folder.cover_still_referenced",
                        logging.WARNING,
                        client_id=client.id,
                        drive_file_id=entry.provider_file_id,
                    )
                    continue
                covers_deleted.append(entry.provider_file_id)
                if dry_run:
                    continue
                storage.delete(entry.provider_file_id)
                log_event(
                    logger,
                    "thumbnail_folder.cover_deleted",
                    client_id=client.id,
                    drive_file_id=entry.provider_file_id,
                )
        except StorageError as exc:
            # In apply mode the rename already landed, so this client is fixed
            # either way - the leftover is inert. Record and carry on.
            failed.append((client.id, f"cover cleanup: {exc}"))
            log_event(
                logger,
                "thumbnail_folder.cover_cleanup_failed",
                logging.ERROR,
                client_id=client.id,
                folder_id=folder_id,
                error=str(exc),
            )

    return {
        "clients_scanned": len(clients),
        "renamed": renamed,
        "already_current": already_current,
        "covers_deleted": covers_deleted,
        "dangling_cleared": dangling_cleared,
        "unexpected": unexpected,
        "failed": failed,
        "dry_run": dry_run,
    }
