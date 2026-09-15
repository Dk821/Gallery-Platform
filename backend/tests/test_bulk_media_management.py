import io

from PIL import Image

from tests.conftest import login_as_admin


def _jpeg_bytes():
    img = Image.new("RGB", (100, 80), color=(1, 2, 3))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _upload(client, album_id, filename="photo.jpg"):
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(album_id)},
        files={"file": (filename, _jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_bulk_delete_multiple_items(client, seeded_admin, seeded_album_for_client, fake_storage):
    login_as_admin(client, seeded_admin)
    m1 = _upload(client, seeded_album_for_client.id, "a.jpg")
    m2 = _upload(client, seeded_album_for_client.id, "b.jpg")
    m3 = _upload(client, seeded_album_for_client.id, "c.jpg")

    resp = client.post("/api/admin/media/bulk-delete", json={"media_ids": [m1["id"], m2["id"], m3["id"]]})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data["deleted"]) == {m1["id"], m2["id"], m3["id"]}
    assert data["failed"] == []
    assert len(fake_storage.files) == 0  # originals + thumbnails all gone

    for mid in (m1["id"], m2["id"], m3["id"]):
        assert client.get(f"/api/admin/media/{mid}").status_code == 404


def test_bulk_delete_reports_missing_ids_without_failing_others(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    m1 = _upload(client, seeded_album_for_client.id)

    resp = client.post("/api/admin/media/bulk-delete", json={"media_ids": [m1["id"], 999999]})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["deleted"] == [m1["id"]]
    assert len(data["failed"]) == 1
    assert data["failed"][0]["id"] == 999999
    assert data["failed"][0]["code"] == "MEDIA_NOT_FOUND"


def test_bulk_delete_rejects_empty_list(client, seeded_admin):
    login_as_admin(client, seeded_admin)
    resp = client.post("/api/admin/media/bulk-delete", json={"media_ids": []})
    assert resp.status_code == 422


def test_bulk_move_within_same_client(
    client, seeded_admin, seeded_album_for_client, seeded_second_album_for_client
):
    login_as_admin(client, seeded_admin)
    m1 = _upload(client, seeded_album_for_client.id, "a.jpg")
    m2 = _upload(client, seeded_album_for_client.id, "b.jpg")

    resp = client.post(
        "/api/admin/media/bulk-move",
        json={"media_ids": [m1["id"], m2["id"]], "target_album_id": seeded_second_album_for_client.id},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data["moved"]) == {m1["id"], m2["id"]}
    assert data["failed"] == []

    for mid in (m1["id"], m2["id"]):
        detail = client.get(f"/api/admin/media/{mid}").json()["data"]
        assert detail["album_id"] == seeded_second_album_for_client.id


def test_bulk_move_rejects_cross_client_items_individually(
    client, seeded_admin, seeded_album_for_client, seeded_album_for_client_b, seeded_second_album_for_client
):
    login_as_admin(client, seeded_admin)
    same_client_item = _upload(client, seeded_album_for_client.id, "a.jpg")
    other_client_item = _upload(client, seeded_album_for_client_b.id, "b.jpg")

    resp = client.post(
        "/api/admin/media/bulk-move",
        json={
            "media_ids": [same_client_item["id"], other_client_item["id"]],
            "target_album_id": seeded_second_album_for_client.id,  # belongs to seeded_client, not client_b
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["moved"] == [same_client_item["id"]]
    assert len(data["failed"]) == 1
    assert data["failed"][0]["id"] == other_client_item["id"]
    assert data["failed"][0]["code"] == "CROSS_CLIENT_MOVE_NOT_ALLOWED"

    # The cross-client item must remain in its original album - untouched.
    unchanged = client.get(f"/api/admin/media/{other_client_item['id']}").json()["data"]
    assert unchanged["album_id"] == seeded_album_for_client_b.id


def test_bulk_move_to_nonexistent_album_404s(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    m1 = _upload(client, seeded_album_for_client.id)

    resp = client.post(
        "/api/admin/media/bulk-move", json={"media_ids": [m1["id"]], "target_album_id": 999999}
    )
    assert resp.status_code == 404


def test_bulk_operations_require_admin(client):
    resp = client.post("/api/admin/media/bulk-delete", json={"media_ids": [1, 2]})
    assert resp.status_code == 401

    resp2 = client.post("/api/admin/media/bulk-move", json={"media_ids": [1], "target_album_id": 1})
    assert resp2.status_code == 401


def test_bulk_delete_never_exposes_drive_ids_in_response(
    client, seeded_admin, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    m1 = _upload(client, seeded_album_for_client.id)
    resp = client.post("/api/admin/media/bulk-delete", json={"media_ids": [m1["id"]]})
    assert "google_drive_file_id" not in resp.text
    assert "thumbnail_reference" not in resp.text


def test_admin_selection_summary_returns_all_ids_across_pagination(
    client, seeded_admin, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    ids = [_upload(client, seeded_album_for_client.id, f"f{i}.jpg")["id"] for i in range(5)]

    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/media/selection-summary")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_count"] == 5
    assert set(data["ids"]) == set(ids)
    assert data["total_bytes"] > 0


def test_admin_selection_summary_respects_search(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "Kumar_1.jpg")
    _upload(client, seeded_album_for_client.id, "Other.jpg")

    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/media/selection-summary?search=kumar")
    assert resp.json()["data"]["total_count"] == 1
