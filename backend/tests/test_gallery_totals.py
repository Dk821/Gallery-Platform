"""Gallery totals are counted in the database, not derived from loaded rows.

The client landing page used to work out its photo/video counts and sizes
from whichever page of media it happened to have in memory, so any album
bigger than one page silently under-reported itself. These tests pin the
numbers to the SQL aggregates instead, including the cross-client
isolation that the aggregates must not break.
"""

from sqlalchemy.dialects import mysql

from app.models.album import Album
from app.models.media import Media
from app.services.media_aggregates import photo_count_column, total_bytes_column, video_count_column
from tests.conftest import login_as_client, login_as_admin


def test_media_aggregates_compile_for_mysql():
    """The counts must be spelled in a way MySQL can actually run.

    `func.count(Media.id).filter(...)` renders as `count(...) FILTER
    (WHERE ...)`, which SQLite (the test database) and Postgres accept but
    MySQL 8 rejects with a 1064 syntax error. Compiling against the MySQL
    dialect here is the only thing that catches it before production.
    """
    for column in (photo_count_column(), video_count_column(), total_bytes_column()):
        sql = str(column.compile(dialect=mysql.dialect())).upper()
        assert "FILTER (WHERE" not in sql, sql
        assert "SUM(" in sql, sql
    for column in (photo_count_column(), video_count_column()):
        assert "CASE WHEN" in str(column.compile(dialect=mysql.dialect())).upper()


def _add_media(db, client, album, name, file_type, size):
    media = Media(
        client_id=client.id,
        album_id=album.id,
        file_uuid=f"{name}-uuid",
        file_name=name,
        file_type=file_type,
        mime_type="image/jpeg" if file_type == "photo" else "video/mp4",
        file_size=size,
        google_drive_file_id=f"drive-{name}",
        status="ready",
    )
    db.add(media)
    db.commit()
    return media


def test_gallery_totals_count_the_clients_own_media_only(client, db_session, seeded_client, seeded_client_b):
    album = Album(
        client_id=seeded_client.id,
        album_uuid="dddddddd-dddd-dddd-dddd-dddddddddddd",
        album_name="Totals",
        status="active",
        drive_folder_id="folder-totals",
    )
    other_album = Album(
        client_id=seeded_client_b.id,
        album_uuid="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        album_name="Someone Else",
        status="active",
        drive_folder_id="folder-totals-b",
    )
    db_session.add_all([album, other_album])
    db_session.commit()

    _add_media(db_session, seeded_client, album, "a1.jpg", "photo", 1000)
    _add_media(db_session, seeded_client, album, "a2.jpg", "photo", 2000)
    _add_media(db_session, seeded_client, album, "a3.mp4", "video", 3000)
    # Same studio, different client: must not appear in A's totals.
    _add_media(db_session, seeded_client_b, other_album, "b1.jpg", "photo", 9000)

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    data = client.get("/api/client/gallery").json()["data"]

    assert data["total_files"] == 3
    assert data["total_photos"] == 2
    assert data["total_videos"] == 1
    assert data["total_bytes"] == 6000


def test_gallery_totals_are_zero_for_an_empty_gallery(client, seeded_client):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    data = client.get("/api/client/gallery").json()["data"]

    assert data["total_files"] == 0
    assert data["total_photos"] == 0
    assert data["total_videos"] == 0
    assert data["total_bytes"] == 0


def test_album_list_reports_counts_and_bytes_per_album(
    client, db_session, seeded_client, seeded_album_for_client, seeded_second_album_for_client
):
    _add_media(db_session, seeded_client, seeded_album_for_client, "w1.jpg", "photo", 1000)
    _add_media(db_session, seeded_client, seeded_album_for_client, "w2.jpg", "photo", 2000)
    _add_media(db_session, seeded_client, seeded_album_for_client, "w3.mp4", "video", 3000)
    _add_media(db_session, seeded_client, seeded_second_album_for_client, "r1.jpg", "photo", 500)

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    items = client.get("/api/client/albums").json()["data"]["items"]
    by_id = {item["id"]: item for item in items}

    wedding = by_id[seeded_album_for_client.id]
    assert wedding["media_count"] == 3
    assert wedding["photo_count"] == 2
    assert wedding["video_count"] == 1
    assert wedding["total_bytes"] == 6000

    reception = by_id[seeded_second_album_for_client.id]
    assert reception["media_count"] == 1
    assert reception["photo_count"] == 1
    assert reception["video_count"] == 0
    assert reception["total_bytes"] == 500


def test_empty_album_reports_zeroes_not_missing_keys(client, seeded_album_for_client, seeded_client):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    data = client.get(f"/api/client/albums/{seeded_album_for_client.id}").json()["data"]

    assert data["media_count"] == 0
    assert data["photo_count"] == 0
    assert data["video_count"] == 0
    assert data["total_bytes"] == 0


def test_album_totals_exceed_a_single_page_of_media(
    client, db_session, seeded_client, seeded_album_for_client
):
    # The whole point of the aggregate: an album with more media than the
    # page the page-sized listing would return still reports the real count.
    for i in range(7):
        _add_media(db_session, seeded_client, seeded_album_for_client, f"p{i}.jpg", "photo", 100)

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    listed = client.get("/api/client/media?album_id=%s&page=1&limit=5" % seeded_album_for_client.id).json()["data"]
    assert len(listed["items"]) == 5

    album = client.get(f"/api/client/albums/{seeded_album_for_client.id}").json()["data"]
    assert album["media_count"] == 7
    assert album["photo_count"] == 7
    assert album["total_bytes"] == 700


def test_admin_album_list_also_carries_the_totals(
    client, db_session, seeded_admin, seeded_album_for_client, seeded_client
):
    _add_media(db_session, seeded_client, seeded_album_for_client, "a1.jpg", "photo", 1000)
    _add_media(db_session, seeded_client, seeded_album_for_client, "a2.mp4", "video", 4000)

    login_as_admin(client, seeded_admin)
    items = client.get("/api/admin/albums").json()["data"]["items"]
    album = next(item for item in items if item["id"] == seeded_album_for_client.id)

    assert album["media_count"] == 2
    assert album["photo_count"] == 1
    assert album["video_count"] == 1
    assert album["total_bytes"] == 5000
