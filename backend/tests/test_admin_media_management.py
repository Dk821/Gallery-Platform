import io

from PIL import Image

from tests.conftest import login_as_admin

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0123456789" * 50  # valid signature, not a real decodable image


def _real_jpeg_bytes(size=(400, 300)) -> bytes:
    img = Image.new("RGB", size, color=(90, 40, 160))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _upload(client, album_id, filename="photo1.jpg", content=None):
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(album_id)},
        files={"file": (filename, content or _real_jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# Listing media in an album (admin)
# ---------------------------------------------------------------------------


def test_admin_can_list_media_in_album(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    _upload(client, seeded_album_for_client.id, "b.jpg")

    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/media")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_admin_media_list_supports_search(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "wedding-ceremony.jpg")
    _upload(client, seeded_album_for_client.id, "reception-toast.jpg")

    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/media?search=ceremony")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["file_name"] == "wedding-ceremony.jpg"


def test_admin_media_list_paginates(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    for i in range(5):
        _upload(client, seeded_album_for_client.id, f"photo{i}.jpg")

    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/media?page=1&limit=2")
    data = resp.json()["data"]
    assert len(data["items"]) == 2
    assert data["total"] == 5
    assert data["has_more"] is True


def test_admin_media_list_for_nonexistent_album_404s(client, seeded_admin):
    login_as_admin(client, seeded_admin)
    resp = client.get("/api/admin/albums/999999/media")
    assert resp.status_code == 404


def test_unauthorized_request_rejected(client, seeded_album_for_client):
    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/media")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Preview / download (admin)
# ---------------------------------------------------------------------------


def test_admin_can_preview_and_download_media(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)
    media_id = media["id"]

    view_resp = client.get(f"/api/admin/media/{media_id}/view")
    assert view_resp.status_code == 200
    assert view_resp.headers["content-disposition"].startswith("inline")

    download_resp = client.get(f"/api/admin/media/{media_id}/download")
    assert download_resp.status_code == 200
    assert download_resp.headers["content-disposition"].startswith("attachment")

    thumb_resp = client.get(f"/api/admin/media/{media_id}/thumbnail")
    assert thumb_resp.status_code == 200


def test_admin_get_single_media_detail(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)

    resp = client.get(f"/api/admin/media/{media['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == media["id"]


def test_invalid_media_id_returns_standard_error(client, seeded_admin):
    login_as_admin(client, seeded_admin)
    resp = client.get("/api/admin/media/999999")
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "MEDIA_NOT_FOUND"


# ---------------------------------------------------------------------------
# Never leak Drive ids
# ---------------------------------------------------------------------------


def test_drive_ids_never_appear_in_any_admin_media_response(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)

    for resp in (
        client.get(f"/api/admin/albums/{seeded_album_for_client.id}/media"),
        client.get(f"/api/admin/media/{media['id']}"),
    ):
        body_text = resp.text
        assert "google_drive_file_id" not in body_text
        assert "thumbnail_reference" not in body_text


# ---------------------------------------------------------------------------
# Edit metadata
# ---------------------------------------------------------------------------


def test_admin_can_edit_supported_metadata(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)

    resp = client.patch(
        f"/api/admin/media/{media['id']}",
        json={"file_name": "renamed.jpg", "title": "Golden Hour", "description": "By the lake"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["file_name"] == "renamed.jpg"
    assert body["title"] == "Golden Hour"
    assert body["description"] == "By the lake"


def test_edit_partial_update_leaves_other_fields_untouched(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)
    client.patch(f"/api/admin/media/{media['id']}", json={"title": "First Title"})

    resp = client.patch(f"/api/admin/media/{media['id']}", json={"description": "Added later"})
    body = resp.json()["data"]
    assert body["title"] == "First Title"
    assert body["description"] == "Added later"


def test_edit_rejects_blank_filename(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)

    resp = client.patch(f"/api/admin/media/{media['id']}", json={"file_name": "   "})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Move media
# ---------------------------------------------------------------------------


def test_admin_can_move_media_within_same_client(
    client, seeded_admin, seeded_album_for_client, seeded_second_album_for_client, fake_storage
):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)
    original_drive_id = next(iter(fake_storage.files))  # only one file so far

    resp = client.post(
        f"/api/admin/media/{media['id']}/move",
        json={"target_album_id": seeded_second_album_for_client.id},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["album_id"] == seeded_second_album_for_client.id

    # Physical file moved to the new album's Drive folder, not re-uploaded.
    assert fake_storage.files[original_drive_id]["parent_folder_id"] == seeded_second_album_for_client.drive_folder_id

    # Now visible in the new album's listing, gone from the old one.
    new_album_media = client.get(f"/api/admin/albums/{seeded_second_album_for_client.id}/media").json()["data"]
    old_album_media = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/media").json()["data"]
    assert new_album_media["total"] == 1
    assert old_album_media["total"] == 0


def test_admin_cannot_move_media_to_another_clients_album(
    client, seeded_admin, seeded_album_for_client, seeded_album_for_client_b
):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)

    resp = client.post(
        f"/api/admin/media/{media['id']}/move",
        json={"target_album_id": seeded_album_for_client_b.id},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CROSS_CLIENT_MOVE_NOT_ALLOWED"

    # Media must still be in its original album.
    unchanged = client.get(f"/api/admin/media/{media['id']}").json()["data"]
    assert unchanged["album_id"] == seeded_album_for_client.id


def test_move_to_same_album_is_a_no_op(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)

    resp = client.post(
        f"/api/admin/media/{media['id']}/move",
        json={"target_album_id": seeded_album_for_client.id},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["album_id"] == seeded_album_for_client.id


def test_move_to_nonexistent_album_404s(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)

    resp = client.post(f"/api/admin/media/{media['id']}/move", json={"target_album_id": 999999})
    assert resp.status_code == 404


def test_move_storage_failure_leaves_media_in_original_album(
    client, seeded_admin, seeded_album_for_client, seeded_second_album_for_client, fake_storage
):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)

    fake_storage.fail_next_move = True
    resp = client.post(
        f"/api/admin/media/{media['id']}/move",
        json={"target_album_id": seeded_second_album_for_client.id},
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "STORAGE_MOVE_FAILED"

    unchanged = client.get(f"/api/admin/media/{media['id']}").json()["data"]
    assert unchanged["album_id"] == seeded_album_for_client.id


# ---------------------------------------------------------------------------
# Delete media
# ---------------------------------------------------------------------------


def test_admin_can_delete_media(client, seeded_admin, seeded_album_for_client, fake_storage):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)
    assert len(fake_storage.files) == 2  # original + thumbnail

    resp = client.delete(f"/api/admin/media/{media['id']}")
    assert resp.status_code == 200
    assert len(fake_storage.files) == 0

    get_resp = client.get(f"/api/admin/media/{media['id']}")
    assert get_resp.status_code == 404


def test_delete_thumbnail_is_removed_alongside_original(client, seeded_admin, seeded_album_for_client, fake_storage):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)
    assert media["has_thumbnail"] is True
    assert len(fake_storage.files) == 2

    client.delete(f"/api/admin/media/{media['id']}")
    assert len(fake_storage.files) == 0


def test_storage_deletion_failure_does_not_silently_remove_db_record(
    client, seeded_admin, seeded_album_for_client, fake_storage, monkeypatch
):
    login_as_admin(client, seeded_admin)
    media = _upload(client, seeded_album_for_client.id)

    from app.services.storage_service import StorageError

    def _boom(*args, **kwargs):
        raise StorageError("simulated persistent storage failure")

    monkeypatch.setattr(fake_storage, "delete", _boom)

    resp = client.delete(f"/api/admin/media/{media['id']}")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "STORAGE_DELETE_FAILED"

    # The DB record must still exist - we never delete it if storage
    # deletion failed.
    still_there = client.get(f"/api/admin/media/{media['id']}")
    assert still_there.status_code == 200
