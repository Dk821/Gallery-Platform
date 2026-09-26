"""
Regression cover for the server-side photo-thumbnail FALLBACK in
complete_direct_upload, and specifically for the fact that this fallback is
what creates the client's "Thumbnails" folder in Drive.

The bug: the fallback sat in the `else` of `if file_type in ("video", "photo")`,
so it could only ever run for file types that are NEITHER video nor photo - and
_generate_thumbnail_from_storage() returns None for anything that isn't a photo.
The branch was therefore unreachable dead code. The browser-thumbnail path
(attach_direct_upload_thumbnail) was consequently the only caller of
_thumbnail_storage_folder(), which is the only thing that ever calls
create_folder("Thumbnails") - so for any client whose photos the browser
couldn't thumb (HEIC, tainted canvas, over the decode/pixel guard, or the 15s
deadline), no imagery folder was ever created in Drive at all and every item
fell back to a placeholder tile.

complete_direct_upload's own docstring already promised the corrected
behaviour ("the bounded read-back only runs as a fallback when the browser
produced none"); these tests hold it to that.
"""

import io

import pytest
from PIL import Image

from app.config.settings import get_settings
from app.models.client import Client
from app.models.media import Media
from app.models.upload_session import UploadSession
from app.services.folder_naming import THUMBNAIL_FOLDER_NAME
from app.services.media_service import complete_direct_upload


def _real_jpeg_bytes(color=(10, 20, 30), size=(120, 90)):
    """A genuinely decodable JPEG - generate_image_thumbnail needs a real one."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _seed_uploading_session(db_session, fake_storage, seeded_admin, album, upload_id, filename, content, mime_type):
    """
    A session mid-direct-upload whose file the "browser" has already PUT into
    the album's Drive folder, with NO browser thumbnail attached - the state
    that used to dead-end. Returns the real Drive file id the fake minted.
    """
    drive_file_id = fake_storage.upload(
        io.BytesIO(content), filename, mime_type, album.drive_folder_id
    ).provider_file_id
    session = UploadSession(
        upload_id=upload_id,
        admin_id=seeded_admin.id,
        album_id=album.id,
        filename=filename,
        total_bytes=len(content),
        bytes_uploaded=len(content),
        status="uploading",
        drive_file_id=drive_file_id,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session, drive_file_id


def _provision_album_folder(db_session, fake_storage, album):
    """The album needs a real Drive folder of its own for the 'browser PUT' to land in."""
    album.drive_folder_id = fake_storage.create_folder(
        "Wedding Day_A_ABCDEF012345", parent_folder_id=album.drive_folder_id
    )
    db_session.commit()


# The headline bug: the imagery folder must exist in Drive afterwards.


def test_thumbnails_folder_is_created_when_browser_sent_no_thumbnail(
    db_session, fake_storage, seeded_admin, seeded_album_for_client
):
    settings = get_settings()
    _provision_album_folder(db_session, fake_storage, seeded_album_for_client)

    client_row = db_session.get(Client, seeded_album_for_client.client_id)
    assert client_row.thumbnail_folder_id is None, "precondition: no imagery folder yet"

    content = _real_jpeg_bytes()
    _, drive_file_id = _seed_uploading_session(
        db_session, fake_storage, seeded_admin, seeded_album_for_client, "no-browser-thumb", "photo.jpg", content, "image/jpeg"
    )

    media = complete_direct_upload(
        db_session, fake_storage, settings, seeded_admin.id, "no-browser-thumb", drive_file_id, len(content), "image/jpeg"
    )

    assert media.thumbnail_reference, "a photo with no browser thumbnail must still get a server-side one"

    db_session.refresh(client_row)
    folder_id = client_row.thumbnail_folder_id
    assert folder_id is not None, "the client's imagery folder must have been created in Drive"
    assert fake_storage.folders[folder_id]["name"] == THUMBNAIL_FOLDER_NAME
    # ...directly under the client folder, as a sibling of the album folders.
    assert fake_storage.folders[folder_id]["parent_folder_id"] == client_row.drive_folder_id


# The folder is created once and reused, not per upload.


def test_imagery_folder_is_reused_across_uploads(
    db_session, fake_storage, seeded_admin, seeded_album_for_client
):
    settings = get_settings()
    _provision_album_folder(db_session, fake_storage, seeded_album_for_client)
    content = _real_jpeg_bytes()

    folder_ids = []
    for n in (1, 2):
        upload_id = f"reuse-{n}"
        _, drive_file_id = _seed_uploading_session(
            db_session, fake_storage, seeded_admin, seeded_album_for_client, upload_id, f"photo{n}.jpg", content, "image/jpeg"
        )
        complete_direct_upload(
            db_session, fake_storage, settings, seeded_admin.id, upload_id, drive_file_id, len(content), "image/jpeg"
        )
        folder_ids.append(db_session.get(Client, seeded_album_for_client.client_id).thumbnail_folder_id)

    assert folder_ids[0] == folder_ids[1]
    assert len([f for f in fake_storage.folders.values() if f["name"] == THUMBNAIL_FOLDER_NAME]) == 1


# The fallback must not disturb the browser path.


def test_browser_thumbnail_is_preferred_and_no_second_file_is_written(
    db_session, fake_storage, seeded_admin, seeded_album_for_client
):
    settings = get_settings()
    _provision_album_folder(db_session, fake_storage, seeded_album_for_client)

    content = _real_jpeg_bytes()
    session, drive_file_id = _seed_uploading_session(
        db_session, fake_storage, seeded_admin, seeded_album_for_client, "browser-thumb", "photo.jpg", content, "image/jpeg"
    )

    # The browser already uploaded its own thumb for this session.
    from app.services.media_service import attach_direct_upload_thumbnail

    thumb = Image.new("RGB", (40, 30), color=(200, 10, 10))
    thumb_buf = io.BytesIO()
    thumb.save(thumb_buf, format="JPEG")
    attach_direct_upload_thumbnail(
        db_session, fake_storage, settings, seeded_admin.id, "browser-thumb", thumb_buf.getvalue()
    )
    browser_thumb_id = db_session.get(UploadSession, session.id).thumbnail_drive_file_id
    assert browser_thumb_id

    media = complete_direct_upload(
        db_session, fake_storage, settings, seeded_admin.id, "browser-thumb", drive_file_id, len(content), "image/jpeg"
    )

    assert media.thumbnail_reference == browser_thumb_id
    assert len([f for f in fake_storage.files.values() if f["name"].startswith("thumb_")]) == 1


# Videos must NOT gain a server-side read-back (that was the point of the
# browser poster), so they legitimately have no imagery folder of their own.


def test_video_with_no_poster_is_left_without_a_thumbnail(
    db_session, fake_storage, seeded_admin, seeded_album_for_client
):
    settings = get_settings()
    _provision_album_folder(db_session, fake_storage, seeded_album_for_client)

    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"0123456789" * 40
    _, drive_file_id = _seed_uploading_session(
        db_session, fake_storage, seeded_admin, seeded_album_for_client, "no-poster", "clip.mp4", mp4, "video/mp4"
    )

    media = complete_direct_upload(
        db_session, fake_storage, settings, seeded_admin.id, "no-poster", drive_file_id, len(mp4), "video/mp4"
    )

    assert media.file_type == "video"
    assert media.thumbnail_reference is None
    # No multi-GB read-back, and no stray folder created for a poster-less video.
    assert db_session.get(Client, seeded_album_for_client.client_id).thumbnail_folder_id is None


# A thumbnail failure must still never fail the upload.


def test_thumbnail_failure_does_not_fail_the_upload(
    db_session, fake_storage, seeded_admin, seeded_album_for_client, monkeypatch
):
    settings = get_settings()
    _provision_album_folder(db_session, fake_storage, seeded_album_for_client)

    content = _real_jpeg_bytes()
    _, drive_file_id = _seed_uploading_session(
        db_session, fake_storage, seeded_admin, seeded_album_for_client, "thumbs-fail", "photo.jpg", content, "image/jpeg"
    )

    from app.services.storage_service import StorageError

    def boom(*args, **kwargs):
        raise StorageError("simulated thumbnail storage failure")

    monkeypatch.setattr(fake_storage, "create_folder", boom)

    media = complete_direct_upload(
        db_session, fake_storage, settings, seeded_admin.id, "thumbs-fail", drive_file_id, len(content), "image/jpeg"
    )

    assert isinstance(media, Media)
    assert media.thumbnail_reference is None


# 502 diagnosability. The folder-creation failure raised as an ApiError does
# NOT subclass StorageError, so it bypasses attach_direct_upload_thumbnail's
# `except StorageError` handler - which is the only place that used to log a
# cause. A Drive-side 403/429 therefore reached the client as a bare
# "502 Bad Gateway" access-log line with nothing in the application log.


def test_folder_creation_failure_logs_its_underlying_cause(
    db_session, fake_storage, seeded_admin, seeded_album_for_client, monkeypatch, caplog
):
    import logging

    from app.schemas.errors import ApiError
    from app.services.storage_service import StorageQuotaExceededError

    settings = get_settings()
    _provision_album_folder(db_session, fake_storage, seeded_album_for_client)

    content = _real_jpeg_bytes()
    session, _ = _seed_uploading_session(
        db_session, fake_storage, seeded_admin, seeded_album_for_client, "folder-denied", "photo.jpg", content, "image/jpeg"
    )

    def boom(*args, **kwargs):
        raise StorageQuotaExceededError("insufficientFilePermissions on the client folder")

    monkeypatch.setattr(fake_storage, "create_folder", boom)

    from app.services.media_service import attach_direct_upload_thumbnail

    with caplog.at_level(logging.ERROR, logger="gallery.media"):
        with pytest.raises(ApiError) as exc_info:
            attach_direct_upload_thumbnail(
                db_session, fake_storage, settings, seeded_admin.id, "folder-denied", content
            )

    assert exc_info.value.status_code == 502
    # Distinguishable from "the file upload into the folder failed".
    assert exc_info.value.detail["code"] == "THUMBNAIL_FOLDER_FAILED"
    # ...and the real reason is now in the application log.
    assert "thumbnail_folder.create_failed" in caplog.text
    assert "insufficientFilePermissions on the client folder" in caplog.text


# The actual production failure: Client.thumbnail_folder_id held an id whose
# Drive folder had been deleted/trashed. Uploading into it 404s with
# "File not found: <id>" (reason notFound, location fileId = the PARENT), on
# every upload, forever - retrying never helped, because the recorded id was
# returned without ever being re-validated.


def test_stale_recorded_folder_id_self_heals(
    db_session, fake_storage, seeded_admin, seeded_album_for_client, caplog
):
    import logging

    settings = get_settings()
    _provision_album_folder(db_session, fake_storage, seeded_album_for_client)
    client_row = db_session.get(Client, seeded_album_for_client.client_id)

    # A folder that existed once and was then removed in Drive, but whose id is
    # still recorded on the client - exactly the unrecoverable state.
    dead_folder_id = fake_storage.create_folder(THUMBNAIL_FOLDER_NAME, parent_folder_id=client_row.drive_folder_id)
    client_row.thumbnail_folder_id = dead_folder_id
    db_session.commit()
    fake_storage.folders.pop(dead_folder_id)
    assert client_row.thumbnail_folder_id == dead_folder_id

    content = _real_jpeg_bytes()
    _, drive_file_id = _seed_uploading_session(
        db_session, fake_storage, seeded_admin, seeded_album_for_client, "stale-folder", "photo.jpg", content, "image/jpeg"
    )

    with caplog.at_level(logging.WARNING, logger="gallery.media"):
        media = complete_direct_upload(
            db_session, fake_storage, settings, seeded_admin.id, "stale-folder", drive_file_id, len(content), "image/jpeg"
        )

    assert media.thumbnail_reference, "a stale folder id must not permanently cost the client its thumbnails"
    db_session.refresh(client_row)
    new_folder_id = client_row.thumbnail_folder_id
    assert new_folder_id is not None and new_folder_id != dead_folder_id
    assert fake_storage.folders[new_folder_id]["name"] == THUMBNAIL_FOLDER_NAME
    assert "thumbnail_folder.stale_id_cleared" in caplog.text


def test_stale_recorded_folder_id_self_heals_on_the_browser_path(
    db_session, fake_storage, seeded_admin, seeded_album_for_client
):
    """Same self-heal for the browser-thumbnail route, which is where it bit you."""
    settings = get_settings()
    _provision_album_folder(db_session, fake_storage, seeded_album_for_client)
    client_row = db_session.get(Client, seeded_album_for_client.client_id)

    dead_folder_id = fake_storage.create_folder(THUMBNAIL_FOLDER_NAME, parent_folder_id=client_row.drive_folder_id)
    client_row.thumbnail_folder_id = dead_folder_id
    db_session.commit()
    fake_storage.folders.pop(dead_folder_id)

    content = _real_jpeg_bytes()
    session, _ = _seed_uploading_session(
        db_session, fake_storage, seeded_admin, seeded_album_for_client, "stale-browser", "photo.jpg", content, "image/jpeg"
    )

    from app.services.media_service import attach_direct_upload_thumbnail

    attach_direct_upload_thumbnail(
        db_session, fake_storage, settings, seeded_admin.id, "stale-browser", content
    )

    assert db_session.get(UploadSession, session.id).thumbnail_drive_file_id
    db_session.refresh(client_row)
    assert client_row.thumbnail_folder_id not in (None, dead_folder_id)


def test_a_genuinely_missing_parent_is_not_retried_forever(
    db_session, fake_storage, seeded_admin, seeded_album_for_client
):
    """
    If the CLIENT's own folder is gone, creating a fresh imagery folder under
    it fails too. That is a real problem to report, not something to loop on -
    the second attempt's failure propagates and the upload still completes.
    """
    from app.services.media_service import attach_direct_upload_thumbnail
    from app.schemas.errors import ApiError

    settings = get_settings()
    _provision_album_folder(db_session, fake_storage, seeded_album_for_client)
    client_row = db_session.get(Client, seeded_album_for_client.client_id)
    # No imagery folder recorded, and the client folder itself is not in Drive.
    assert client_row.thumbnail_folder_id is None

    def create_raises(*args, **kwargs):
        from app.services.storage_service import StorageNotFoundError

        raise StorageNotFoundError("File not found: client-root")

    original = fake_storage.create_folder
    fake_storage.create_folder = lambda name, parent_folder_id=None: (
        create_raises() if name == THUMBNAIL_FOLDER_NAME else original(name, parent_folder_id)
    )
    try:
        content = _real_jpeg_bytes()
        session, _ = _seed_uploading_session(
            db_session, fake_storage, seeded_admin, seeded_album_for_client, "dead-parent", "photo.jpg", content, "image/jpeg"
        )
        with pytest.raises(ApiError) as exc_info:
            attach_direct_upload_thumbnail(
                db_session, fake_storage, settings, seeded_admin.id, "dead-parent", content
            )
    finally:
        fake_storage.create_folder = original

    assert exc_info.value.status_code == 502
    assert db_session.get(UploadSession, session.id).thumbnail_drive_file_id is None
