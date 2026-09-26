"""
Covers the Drive-side half of the cover removal: the one-shot ops pass in
app/services/thumbnail_folder_migration.py that renames a legacy "Cover Images"
folder to "Thumbnails" and purges the orphaned cover.

Background: alembic a5c7e3b1d9f8 renamed clients.cover_folder_id to
thumbnail_folder_id but could not rename the Drive folder itself, so clients
created before the change still have a folder with the old name. See that
migration's docstring and app/migrate_thumbnail_folders.py.
"""

import io

from app.models.client import Client
from app.services.folder_naming import (
    LEGACY_COVER_FILE_NAME,
    LEGACY_COVER_FOLDER_NAME,
    THUMBNAIL_FOLDER_NAME,
)
from app.services.storage_service import StorageError
from app.services.thumbnail_folder_migration import migrate_client_thumbnail_folders


def _seed_client_with_folder(db_session, fake_storage, folder_name, *, client_uuid):
    """A client whose recorded thumbnail folder is really named `folder_name` in Drive."""
    folder_id = fake_storage.create_folder(folder_name, parent_folder_id="folder-root")
    row = Client(
        client_uuid=client_uuid,
        client_name="Legacy Client",
        status="active",
        drive_folder_id="folder-root",
        thumbnail_folder_id=folder_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row, folder_id


def _put_file(fake_storage, folder_id, name, content=b"x"):
    return fake_storage.upload(io.BytesIO(content), name, "image/webp", folder_id).provider_file_id


# 1. The rename -------------------------------------------------------


def test_renames_legacy_folder_to_thumbnails(db_session, fake_storage):
    row, folder_id = _seed_client_with_folder(
        db_session, fake_storage, LEGACY_COVER_FOLDER_NAME, client_uuid="a1a1a1a1-1111-1111-1111-111111111111"
    )

    result = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)

    assert fake_storage.folders[folder_id]["name"] == THUMBNAIL_FOLDER_NAME
    assert result["renamed"] == [row.id]
    # Metadata-only: the id the gallery resolves thumbnails by must not move.
    assert db_session.get(Client, row.id).thumbnail_folder_id == folder_id


def test_dry_run_reports_but_writes_nothing(db_session, fake_storage):
    row, folder_id = _seed_client_with_folder(
        db_session, fake_storage, LEGACY_COVER_FOLDER_NAME, client_uuid="a2a2a2a2-2222-2222-2222-222222222222"
    )
    cover_id = _put_file(fake_storage, folder_id, LEGACY_COVER_FILE_NAME)

    result = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=True)

    assert result["dry_run"] is True
    # Full blast radius is reported so a dry run is worth reading...
    assert result["renamed"] == [row.id]
    assert result["covers_deleted"] == [cover_id]
    # ...but nothing actually happened.
    assert fake_storage.folders[folder_id]["name"] == LEGACY_COVER_FOLDER_NAME
    assert cover_id in fake_storage.files
    assert cover_id not in fake_storage.deleted_file_ids


def test_folder_already_current_is_skipped(db_session, fake_storage):
    row, folder_id = _seed_client_with_folder(
        db_session, fake_storage, THUMBNAIL_FOLDER_NAME, client_uuid="a3a3a3a3-3333-3333-3333-333333333333"
    )

    result = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)

    assert result["already_current"] == [row.id]
    assert result["renamed"] == []


def test_is_idempotent(db_session, fake_storage):
    _seed_client_with_folder(
        db_session, fake_storage, LEGACY_COVER_FOLDER_NAME, client_uuid="a4a4a4a4-4444-4444-4444-444444444444"
    )

    migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)
    second = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)

    assert second["renamed"] == []
    assert second["already_current"]


# 2. The orphaned cover -----------------------------------------------


def test_deletes_orphaned_cover_but_keeps_thumbnails(db_session, fake_storage):
    row, folder_id = _seed_client_with_folder(
        db_session, fake_storage, LEGACY_COVER_FOLDER_NAME, client_uuid="a5a5a5a5-5555-5555-5555-555555555555"
    )
    cover_id = _put_file(fake_storage, folder_id, LEGACY_COVER_FILE_NAME)
    thumb_id = _put_file(fake_storage, folder_id, "thumb_abc-123.webp")

    result = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)

    assert result["covers_deleted"] == [cover_id]
    assert cover_id in fake_storage.deleted_file_ids
    # The whole point of keeping the folder id: existing thumbs survive.
    assert thumb_id in fake_storage.files
    assert thumb_id not in fake_storage.deleted_file_ids


def test_cover_still_referenced_by_a_thumbnail_is_kept(db_session, fake_storage, seeded_client, seeded_album_for_client):
    from app.models.media import Media

    row, folder_id = _seed_client_with_folder(
        db_session, fake_storage, LEGACY_COVER_FOLDER_NAME, client_uuid="a6a6a6a6-6666-6666-6666-666666666666"
    )
    cover_id = _put_file(fake_storage, folder_id, LEGACY_COVER_FILE_NAME)
    # Belt-and-braces: a cover.webp that some Media row still serves must
    # never be deleted, whatever the folder is called.
    db_session.add(
        Media(
            client_id=seeded_client.id,
            album_id=seeded_album_for_client.id,
            file_uuid="9c9c9c9c-9999-9999-9999-999999999999",
            file_name="photo.jpg",
            file_type="photo",
            mime_type="image/jpeg",
            file_size=10,
            google_drive_file_id="drive-photo-1",
            status="ready",
            thumbnail_reference=cover_id,
        )
    )
    db_session.commit()

    result = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)

    assert row.id in result["renamed"]
    assert cover_id not in fake_storage.deleted_file_ids
    assert result["covers_deleted"] == []


def test_subfolders_and_other_files_are_left_alone(db_session, fake_storage):
    _, folder_id = _seed_client_with_folder(
        db_session, fake_storage, LEGACY_COVER_FOLDER_NAME, client_uuid="a7a7a7a7-7777-7777-7777-777777777777"
    )
    subfolder_id = fake_storage.create_folder("some album", parent_folder_id=folder_id)
    other_id = _put_file(fake_storage, folder_id, "notes.txt")
    cover_id = _put_file(fake_storage, folder_id, LEGACY_COVER_FILE_NAME)

    migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)

    assert subfolder_id in fake_storage.folders
    assert other_id in fake_storage.files
    assert cover_id in fake_storage.deleted_file_ids


# 3. Safety rails -----------------------------------------------------


def test_unexpected_folder_name_is_not_renamed(db_session, fake_storage):
    row, folder_id = _seed_client_with_folder(
        db_session, fake_storage, "Photos", client_uuid="a8a8a8a8-8888-8888-8888-888888888888"
    )

    result = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)

    assert result["unexpected"] == [(row.id, "Photos")]
    assert fake_storage.folders[folder_id]["name"] == "Photos"


def test_deleted_folder_is_forgotten_so_it_gets_recreated(db_session, fake_storage):
    row, folder_id = _seed_client_with_folder(
        db_session, fake_storage, LEGACY_COVER_FOLDER_NAME, client_uuid="a9a9a9a9-9999-9999-9999-999999999999"
    )
    # Somebody emptied the folder in Drive by hand.
    fake_storage.folders.pop(folder_id)
    fake_storage.deleted_file_ids.clear()

    result = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)

    assert result["dangling_cleared"] == [row.id]
    # Cleared, not left pointing at a dead id - _ensure_thumbnail_folder()
    # lazily recreates a correctly-named folder on the next upload.
    assert db_session.get(Client, row.id).thumbnail_folder_id is None


def test_dangling_folder_is_not_cleared_on_a_dry_run(db_session, fake_storage):
    row, folder_id = _seed_client_with_folder(
        db_session, fake_storage, LEGACY_COVER_FOLDER_NAME, client_uuid="b1b1b1b1-1111-1111-1111-111111111111"
    )
    fake_storage.folders.pop(folder_id)

    result = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=True)

    assert result["dangling_cleared"] == [row.id]
    assert db_session.get(Client, row.id).thumbnail_folder_id == folder_id


def test_one_failing_folder_does_not_stop_the_others(db_session, fake_storage, monkeypatch):
    good_row, good_folder_id = _seed_client_with_folder(
        db_session, fake_storage, LEGACY_COVER_FOLDER_NAME, client_uuid="b2b2b2b2-2222-2222-2222-222222222222"
    )
    bad_row, _ = _seed_client_with_folder(
        db_session, fake_storage, LEGACY_COVER_FOLDER_NAME, client_uuid="b3b3b3b3-3333-3333-3333-333333333333"
    )

    real_rename = fake_storage.rename_folder

    def rename_or_fail(folder_id, new_name):
        if bad_row.thumbnail_folder_id == folder_id:
            raise StorageError("simulated Drive failure")
        return real_rename(folder_id, new_name)

    monkeypatch.setattr(fake_storage, "rename_folder", rename_or_fail)

    result = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)

    assert good_row.id in result["renamed"]
    assert fake_storage.folders[good_folder_id]["name"] == THUMBNAIL_FOLDER_NAME
    assert [client_id for client_id, _ in result["failed"]] == [bad_row.id]
    assert result["clients_scanned"] == 2


def test_clients_without_a_thumbnail_folder_are_not_scanned(db_session, seeded_client, fake_storage):
    assert seeded_client.thumbnail_folder_id is None

    result = migrate_client_thumbnail_folders(db_session, fake_storage, dry_run=False)

    assert result["clients_scanned"] == 0
    assert result["renamed"] == []
