"""
Covers the Drive folder naming rework:
  {client_name}_C_{unique_id}
  {album_name}_A_{unique_id}

See app/services/folder_naming.py for the format itself and
client_service.py / album_service.py for where it's applied.
"""

import re

from app.models.album import Album
from app.models.client import Client
from tests.conftest import login_as_admin

FOLDER_UID_RE = re.compile(r"^[0-9A-F]{12}$")


def _create_client(client, name="Kumar Photography"):
    resp = client.post("/api/admin/clients", json={"client_name": name, "password": "good"})
    assert resp.status_code == 200
    return resp.json()["data"]


def _create_album(client, client_id, name="Wedding 2026"):
    resp = client.post("/api/admin/albums", json={"client_id": client_id, "album_name": name})
    assert resp.status_code == 200
    return resp.json()["data"]


# 1. Correct client folder format --------------------------------------


def test_client_folder_name_format(client, seeded_admin, fake_storage, db_session):
    login_as_admin(client, seeded_admin)
    data = _create_client(client, "Kumar Photography")

    db_client = db_session.query(Client).filter_by(id=data["id"]).first()
    folder_id = db_client.drive_folder_id
    folder_name = fake_storage.folders[folder_id]["name"]

    prefix, sep, uid = folder_name.rpartition("_C_")
    assert sep == "_C_"
    assert prefix == "Kumar Photography"
    assert FOLDER_UID_RE.match(uid), f"unique id {uid!r} should be a 12-char uppercase hex token"
    # Never the DB numeric id, and never the public gallery uuid.
    assert uid != str(db_client.id)
    assert uid != db_client.client_uuid


# 2. Correct album folder format -----------------------------------------


def test_album_folder_name_format(client, seeded_admin, seeded_client, fake_storage, db_session):
    login_as_admin(client, seeded_admin)
    data = _create_album(client, seeded_client.id, "Wedding 2026")

    db_album = db_session.query(Album).filter_by(id=data["id"]).first()
    folder_id = db_album.drive_folder_id
    folder_name = fake_storage.folders[folder_id]["name"]

    prefix, sep, uid = folder_name.rpartition("_A_")
    assert sep == "_A_"
    assert prefix == "Wedding 2026"
    assert FOLDER_UID_RE.match(uid)
    assert uid != str(db_album.id)
    assert uid != db_album.album_uuid

    # Album folder must be created under its client's folder.
    assert fake_storage.folders[folder_id]["parent_folder_id"] == seeded_client.drive_folder_id


# 3. Unique IDs for duplicate names ---------------------------------------


def test_duplicate_client_names_get_different_unique_ids(client, seeded_admin, fake_storage, db_session):
    login_as_admin(client, seeded_admin)
    first = _create_client(client, "Kumar Photography")
    second = _create_client(client, "Kumar Photography")

    first_client = db_session.query(Client).filter_by(id=first["id"]).first()
    second_client = db_session.query(Client).filter_by(id=second["id"]).first()

    assert first_client.folder_uid != second_client.folder_uid
    assert first_client.drive_folder_id != second_client.drive_folder_id

    first_name = fake_storage.folders[first_client.drive_folder_id]["name"]
    second_name = fake_storage.folders[second_client.drive_folder_id]["name"]
    assert first_name != second_name
    # Same readable prefix, different folders.
    assert first_name.startswith("Kumar Photography_C_")
    assert second_name.startswith("Kumar Photography_C_")


def test_duplicate_album_names_get_different_unique_ids(
    client, seeded_admin, seeded_client, fake_storage, db_session
):
    login_as_admin(client, seeded_admin)
    first = _create_album(client, seeded_client.id, "Wedding 2026")
    second = _create_album(client, seeded_client.id, "Wedding 2026")

    first_album = db_session.query(Album).filter_by(id=first["id"]).first()
    second_album = db_session.query(Album).filter_by(id=second["id"]).first()

    assert first_album.folder_uid != second_album.folder_uid
    assert first_album.drive_folder_id != second_album.drive_folder_id

    first_name = fake_storage.folders[first_album.drive_folder_id]["name"]
    second_name = fake_storage.folders[second_album.drive_folder_id]["name"]
    assert first_name != second_name


# 4. ID remains unchanged after renaming -----------------------------------


def test_client_unique_id_unchanged_after_rename(client, seeded_admin, fake_storage, db_session):
    login_as_admin(client, seeded_admin)
    created = _create_client(client, "Kumar Photography")
    db_client = db_session.query(Client).filter_by(id=created["id"]).first()
    folder_id = db_client.drive_folder_id
    original_uid = db_client.folder_uid

    resp = client.put(f"/api/admin/clients/{created['id']}", json={"client_name": "Kumar Studios"})
    assert resp.status_code == 200

    db_session.refresh(db_client)
    assert db_client.folder_uid == original_uid  # suffix never changes
    assert db_client.drive_folder_id == folder_id  # same Drive folder, not recreated
    assert len(fake_storage.folders) == 1  # no new folder was created

    assert fake_storage.folders[folder_id]["name"] == f"Kumar Studios_C_{original_uid}"


def test_album_unique_id_unchanged_after_rename(
    client, seeded_admin, seeded_client, fake_storage, db_session
):
    login_as_admin(client, seeded_admin)
    created = _create_album(client, seeded_client.id, "Wedding 2026")
    db_album = db_session.query(Album).filter_by(id=created["id"]).first()
    folder_id = db_album.drive_folder_id
    original_uid = db_album.folder_uid
    folders_before = len(fake_storage.folders)

    resp = client.put(f"/api/admin/albums/{created['id']}", json={"album_name": "Wedding Reception 2026"})
    assert resp.status_code == 200

    db_session.refresh(db_album)
    assert db_album.folder_uid == original_uid
    assert db_album.drive_folder_id == folder_id
    assert len(fake_storage.folders) == folders_before  # no new folder created

    assert fake_storage.folders[folder_id]["name"] == f"Wedding Reception 2026_A_{original_uid}"


def test_renaming_to_the_same_name_does_not_touch_storage(client, seeded_admin, fake_storage, db_session):
    login_as_admin(client, seeded_admin)
    created = _create_client(client, "Kumar Photography")
    db_client = db_session.query(Client).filter_by(id=created["id"]).first()
    folder_id = db_client.drive_folder_id
    name_before = fake_storage.folders[folder_id]["name"]

    resp = client.put(f"/api/admin/clients/{created['id']}", json={"client_name": "Kumar Photography"})
    assert resp.status_code == 200
    assert fake_storage.folders[folder_id]["name"] == name_before


# 5. Existing Drive folders continue working -------------------------------


def test_legacy_client_folder_keeps_working_after_this_change(
    client, seeded_admin, seeded_client, seeded_album_for_client, fake_storage
):
    """
    seeded_client/seeded_album_for_client simulate records that already
    existed before this change - their drive_folder_id was never produced
    by storage.create_folder() in this test run (fake_storage.folders
    starts empty). Uploading, renaming, and deleting must all keep working
    against that pre-existing folder id without requiring it to be
    recreated.
    """
    login_as_admin(client, seeded_admin)

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"0123456789" * 50
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", jpeg_bytes, "image/jpeg")},
    )
    assert upload_resp.status_code == 200

    rename_resp = client.put(
        f"/api/admin/clients/{seeded_client.id}", json={"client_name": "John Wedding Photography"}
    )
    assert rename_resp.status_code == 200
    assert (
        fake_storage.folders[seeded_client.drive_folder_id]["name"]
        == f"John Wedding Photography_C_{seeded_client.folder_uid}"
    )

    album_rename_resp = client.put(
        f"/api/admin/albums/{seeded_album_for_client.id}", json={"album_name": "Wedding Day Photos"}
    )
    assert album_rename_resp.status_code == 200
    assert (
        fake_storage.folders[seeded_album_for_client.drive_folder_id]["name"]
        == f"Wedding Day Photos_A_{seeded_album_for_client.folder_uid}"
    )


def test_client_rename_storage_failure_rolls_back_db(client, seeded_admin, fake_storage, db_session):
    login_as_admin(client, seeded_admin)
    created = _create_client(client, "Kumar Photography")
    db_client = db_session.query(Client).filter_by(id=created["id"]).first()

    fake_storage.fail_next_rename = True
    resp = client.put(f"/api/admin/clients/{created['id']}", json={"client_name": "Should Not Save"})
    assert resp.status_code == 502

    db_session.refresh(db_client)
    assert db_client.client_name == "Kumar Photography"  # DB name unchanged on storage failure


# 6. No Drive IDs exposed in API responses ---------------------------------


def test_client_api_responses_never_expose_drive_ids(client, seeded_admin, fake_storage):
    login_as_admin(client, seeded_admin)
    created = _create_client(client, "Kumar Photography")

    for payload in (created, client.get(f"/api/admin/clients/{created['id']}").json()["data"]):
        assert "drive_folder_id" not in payload
        assert "folder_uid" not in payload

    list_resp = client.get("/api/admin/clients")
    for item in list_resp.json()["data"]["items"]:
        assert "drive_folder_id" not in item
        assert "folder_uid" not in item


def test_album_api_responses_never_expose_drive_ids(client, seeded_admin, seeded_client, fake_storage):
    login_as_admin(client, seeded_admin)
    created = _create_album(client, seeded_client.id, "Wedding 2026")

    for payload in (created, client.get(f"/api/admin/albums/{created['id']}").json()["data"]):
        assert "drive_folder_id" not in payload
        assert "folder_uid" not in payload

    list_resp = client.get("/api/admin/albums")
    for item in list_resp.json()["data"]["items"]:
        assert "drive_folder_id" not in item
        assert "folder_uid" not in item
