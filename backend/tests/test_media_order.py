import datetime
import uuid

from app.models.album import Album
from app.models.media import Media
from app.services.media_service import next_media_sort_order
from tests.conftest import login_as_admin, login_as_client


def _media(db_session, album, client, name: str, sort_order: int, minute: int = 0) -> Media:
    media = Media(
        client_id=client.id,
        album_id=album.id,
        file_uuid=str(uuid.uuid4()),
        file_name=name,
        file_type="photo",
        mime_type="image/jpeg",
        file_size=1024,
        google_drive_file_id=f"drive-{name}",
        status="ready",
        sort_order=sort_order,
        created_at=datetime.datetime(2026, 1, 1, 12, minute),
    )
    db_session.add(media)
    db_session.commit()
    db_session.refresh(media)
    return media


def _seed_three(db_session, album, client):
    return [
        _media(db_session, album, client, "a.jpg", 1, 1),
        _media(db_session, album, client, "b.jpg", 2, 2),
        _media(db_session, album, client, "c.jpg", 3, 3),
    ]


def test_admin_can_reorder_album_media(
    client,
    db_session,
    seeded_admin,
    seeded_client,
    seeded_album_for_client,
):
    a, b, c = _seed_three(db_session, seeded_album_for_client, seeded_client)
    login_as_admin(client, seeded_admin)

    resp = client.put(
        f"/api/admin/albums/{seeded_album_for_client.id}/media/order",
        json={"media_ids": [c.id, a.id, b.id]},
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/media")
    items = resp.json()["data"]["items"]
    assert [m["file_name"] for m in items] == ["c.jpg", "a.jpg", "b.jpg"]
    assert [m["sort_order"] for m in items] == [1, 2, 3]

    # The client's gallery reads the same order.
    client.post("/api/auth/logout")
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get(f"/api/client/media?album_id={seeded_album_for_client.id}")
    assert [m["file_name"] for m in resp.json()["data"]["items"]] == ["c.jpg", "a.jpg", "b.jpg"]


def test_reorder_renumbers_page_notes_with_their_photo(
    client,
    db_session,
    seeded_admin,
    seeded_client,
    seeded_album_for_client,
):
    a = _media(db_session, seeded_album_for_client, seeded_client, "a.jpg", 1, 1)
    b = _media(db_session, seeded_album_for_client, seeded_client, "b.jpg", 2, 2)
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")

    client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": a.id, "page_number": 1, "comment": "note on a"},
    )
    client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": b.id, "page_number": 2, "comment": "note on b"},
    )

    login_as_admin(client, seeded_admin)
    # Swapping the two photos must not trip the one-note-per-page constraint.
    resp = client.put(
        f"/api/admin/albums/{seeded_album_for_client.id}/media/order",
        json={"media_ids": [b.id, a.id]},
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/comments")
    by_page = {item["page_number"]: item for item in resp.json()["data"]}
    assert by_page[1]["comment"] == "note on b"
    assert by_page[1]["media_id"] == b.id
    assert by_page[2]["comment"] == "note on a"
    assert by_page[2]["media_id"] == a.id


def test_reorder_rejects_incomplete_or_foreign_lists(
    client,
    db_session,
    seeded_admin,
    seeded_client,
    seeded_album_for_client,
    seeded_album_for_client_b,
):
    a, b, c = _seed_three(db_session, seeded_album_for_client, seeded_client)
    foreign = _media(db_session, seeded_album_for_client_b, seeded_client, "foreign.jpg", 1)
    login_as_admin(client, seeded_admin)

    url = f"/api/admin/albums/{seeded_album_for_client.id}/media/order"
    assert client.put(url, json={"media_ids": [a.id, b.id]}).status_code == 400
    assert client.put(url, json={"media_ids": [a.id, a.id, b.id]}).status_code == 400
    assert client.put(url, json={"media_ids": [a.id, b.id, foreign.id]}).status_code == 400
    # Nothing moved on the rejected requests.
    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/media")
    assert [m["file_name"] for m in resp.json()["data"]["items"]] == ["a.jpg", "b.jpg", "c.jpg"]


def test_reorder_requires_an_admin_session(client, seeded_client, seeded_album_for_client):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.put(
        f"/api/admin/albums/{seeded_album_for_client.id}/media/order",
        json={"media_ids": []},
    )
    assert resp.status_code == 401


def test_next_media_sort_order_appends_after_the_highest(
    db_session, seeded_client, seeded_album_for_client
):
    _seed_three(db_session, seeded_album_for_client, seeded_client)
    assert next_media_sort_order(db_session, seeded_album_for_client.id) == 4


def test_moved_media_lands_at_the_end_of_the_target_order(
    client, db_session, fake_storage, seeded_admin, seeded_client, seeded_album_for_client
):
    a = _media(db_session, seeded_album_for_client, seeded_client, "a.jpg", 1)
    fake_storage.files[a.google_drive_file_id] = {
        "name": a.file_name,
        "mime_type": a.mime_type,
        "parent_folder_id": seeded_album_for_client.drive_folder_id,
        "content": b"",
        "upload_id": a.file_uuid,
    }
    target = Album(
        client_id=seeded_client.id,
        album_uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        album_name="Second Album",
        status="active",
        drive_folder_id="folder-test-album-second",
    )
    db_session.add(target)
    db_session.commit()
    db_session.refresh(target)
    _media(db_session, target, seeded_client, "existing.jpg", 1)

    login_as_admin(client, seeded_admin)
    resp = client.post(f"/api/admin/media/{a.id}/move", json={"target_album_id": target.id})
    assert resp.status_code == 200

    resp = client.get(f"/api/admin/albums/{target.id}/media")
    items = resp.json()["data"]["items"]
    assert [m["file_name"] for m in items] == ["existing.jpg", "a.jpg"]
    assert [m["sort_order"] for m in items] == [1, 2]
