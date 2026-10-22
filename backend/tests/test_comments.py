from app.models.media import Media
from tests.conftest import login_as_admin, login_as_client


def _seed_media_for_client_b(db_session, seeded_client_b, seeded_album_for_client_b):
    """A media item owned by client B - used to prove client A can't borrow it."""
    media = Media(
        client_id=seeded_client_b.id,
        album_id=seeded_album_for_client_b.id,
        file_uuid="dddddddd-dddd-dddd-dddd-dddddddddddd",
        file_name="client-b-photo.jpg",
        file_type="photo",
        mime_type="image/jpeg",
        file_size=2048,
        google_drive_file_id="fake-drive-id-b",
        status="ready",
    )
    db_session.add(media)
    db_session.commit()
    db_session.refresh(media)
    return media


def test_client_can_list_save_edit_delete_own_comment(
    client,
    seeded_client,
    seeded_album_for_client,
    seeded_media_for_client,
):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")

    # Initially no comments
    resp = client.get(f"/api/client/albums/{seeded_album_for_client.id}/comments")
    assert resp.status_code == 200
    assert resp.json()["data"] == []

    # Create/save first note on page 1
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 1, "comment": "Love this!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["created"] is True
    comment_id = body["data"]["id"]
    assert body["data"]["page_number"] == 1
    assert body["data"]["comment"] == "Love this!"
    assert body["data"]["status"] == "open"
    assert body["data"]["media_id"] == seeded_media_for_client.id
    assert body["data"]["media_file_name"] == seeded_media_for_client.file_name
    assert body["data"]["has_thumbnail"] is False

    # Re-submitting same page edits (not duplicate)
    resp2 = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={
            "media_id": seeded_media_for_client.id,
            "page_number": 1,
            "comment": "Actually prefer the one on the right",
        },
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["data"]["created"] is False
    assert body2["data"]["id"] == comment_id
    assert body2["data"]["comment"] == "Actually prefer the one on the right"
    assert body2["data"]["status"] == "open"

    # List returns the updated note
    resp = client.get(f"/api/client/albums/{seeded_album_for_client.id}/comments")
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) == 1
    assert items[0]["id"] == comment_id

    # Edit via PUT
    resp = client.put(
        f"/api/client/comments/{comment_id}",
        json={"comment": "Final note"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["comment"] == "Final note"
    assert resp.json()["data"]["status"] == "open"

    # Delete
    resp = client.delete(f"/api/client/comments/{comment_id}")
    assert resp.status_code == 200
    assert resp.json()["data"] is None

    # Gone
    resp = client.get(f"/api/client/albums/{seeded_album_for_client.id}/comments")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_client_cannot_comment_on_other_clients_album(
    client,
    seeded_client,
    seeded_client_b,
    seeded_album_for_client,
    seeded_media_for_client,
):
    login_as_client(client, seeded_client_b.client_uuid, "client-pass-2")
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 1, "comment": "hi"},
    )
    assert resp.status_code == 403


def test_client_cannot_comment_with_foreign_media(
    client,
    seeded_client,
    seeded_client_b,
    seeded_album_for_client,
    seeded_album_for_client_b,
    seeded_media_for_client,
    db_session,
):
    # A media item that belongs to client B must not be usable as the page
    # reference of client A's note, even though client A owns the album.
    media_b = _seed_media_for_client_b(db_session, seeded_client_b, seeded_album_for_client_b)
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": media_b.id, "page_number": 1, "comment": "hi"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "MEDIA_FORBIDDEN"


def test_client_cannot_edit_or_delete_other_clients_comment(
    client,
    seeded_client,
    seeded_client_b,
    seeded_album_for_client,
    seeded_media_for_client,
):
    # Client A writes a comment
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 2, "comment": "A's note"},
    )
    assert resp.status_code == 200
    comment_id = resp.json()["data"]["id"]

    # Client B tries to edit and delete it. Both must be reported as "not
    # found" so a note id can never be confirmed to exist by another client.
    login_as_client(client, seeded_client_b.client_uuid, "client-pass-2")
    resp = client.put(
        f"/api/client/comments/{comment_id}",
        json={"comment": "evil"},
    )
    assert resp.status_code == 404

    resp = client.delete(f"/api/client/comments/{comment_id}")
    assert resp.status_code == 404


def test_comment_validation(
    client,
    seeded_client,
    seeded_album_for_client,
    seeded_media_for_client,
):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")

    # blank comment
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 1, "comment": "   "},
    )
    assert resp.status_code == 422

    # page 0 invalid
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 0, "comment": "hi"},
    )
    assert resp.status_code == 422

    # over-long comment
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 1, "comment": "x" * 2001},
    )
    assert resp.status_code == 422


def test_unauthenticated_client_comment_route_requires_login(
    client, seeded_album_for_client, seeded_media_for_client
):
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 1, "comment": "hi"},
    )
    assert resp.status_code == 401


def test_admin_comments_full_flow(
    client,
    seeded_admin,
    seeded_client,
    seeded_album_for_client,
    seeded_media_for_client,
):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 3, "comment": "Please retouch"},
    )
    assert resp.status_code == 200
    comment_id = resp.json()["data"]["id"]

    # Admin lists comments for album
    login_as_admin(client, seeded_admin)
    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/comments")
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) == 1
    assert items[0]["id"] == comment_id
    assert items[0]["page_number"] == 3
    assert items[0]["status"] == "open"
    assert items[0]["media_file_name"] == "photo1.jpg"

    # Resolve
    resp = client.patch(
        f"/api/admin/comments/{comment_id}",
        json={"status": "resolved"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "resolved"

    # Reopen
    resp = client.patch(
        f"/api/admin/comments/{comment_id}",
        json={"status": "open"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "open"

    # Admin deletes
    resp = client.delete(f"/api/admin/comments/{comment_id}")
    assert resp.status_code == 200
    assert resp.json()["data"] is None


def test_admin_comments_reflect_renamed_media(
    client,
    seeded_admin,
    seeded_client,
    seeded_album_for_client,
    seeded_media_for_client,
):
    """
    The note only stores media_id, so the admin list must always read the
    live media row: renaming a file updates the name the popup shows.
    """
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 1, "comment": "Retouch please"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["media_file_name"] == "photo1.jpg"

    login_as_admin(client, seeded_admin)
    resp = client.patch(
        f"/api/admin/media/{seeded_media_for_client.id}",
        json={"file_name": "renamed-page-one.jpg"},
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/comments")
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) == 1
    assert items[0]["media_file_name"] == "renamed-page-one.jpg"


def test_client_edit_reopens_resolved_comment(
    client,
    seeded_admin,
    seeded_client,
    seeded_album_for_client,
    seeded_media_for_client,
):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 1, "comment": "one"},
    )
    comment_id = resp.json()["data"]["id"]

    login_as_admin(client, seeded_admin)
    resp = client.patch(f"/api/admin/comments/{comment_id}", json={"status": "resolved"})
    assert resp.status_code == 200

    # The client changes their mind - the studio must see it again.
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.put(f"/api/client/comments/{comment_id}", json={"comment": "two"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "open"
    assert resp.json()["data"]["comment"] == "two"


def test_expired_album_blocks_client_but_not_admin(
    client,
    seeded_admin,
    seeded_client,
    seeded_album_for_client,
    seeded_media_for_client,
    db_session,
):
    import datetime

    # Create comment while the album is still active
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 1, "comment": "hi"},
    )
    assert resp.status_code == 200
    comment_id = resp.json()["data"]["id"]

    # Expire the album
    seeded_album_for_client.expires_at = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    db_session.commit()

    # The client can no longer reach the album (or its notes)
    resp = client.get(f"/api/client/albums/{seeded_album_for_client.id}/comments")
    assert resp.status_code == 403

    # The studio can still see and manage them
    login_as_admin(client, seeded_admin)
    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/comments")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1

    resp = client.patch(f"/api/admin/comments/{comment_id}", json={"status": "resolved"})
    assert resp.status_code == 200


def test_admin_route_rejects_client_session_for_comments(client, seeded_client, seeded_album_for_client):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get(f"/api/admin/albums/{seeded_album_for_client.id}/comments")
    assert resp.status_code == 401


def test_album_list_carries_comment_count(
    client,
    seeded_client,
    seeded_album_for_client,
    seeded_media_for_client,
):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/comments",
        json={"media_id": seeded_media_for_client.id, "page_number": 1, "comment": "hi"},
    )
    assert resp.status_code == 200

    resp = client.get("/api/client/albums")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["comment_count"] == 1
