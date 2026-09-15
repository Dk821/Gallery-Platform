from tests.conftest import login_as_admin, login_as_client
from tests.test_download_jobs import _upload


def _download_album(client, album_id, password: str | None = None):
    """Create a client download job and fetch its ZIP (records the download)."""
    job = client.post(f"/api/client/albums/{album_id}/download-jobs", json={}).json()["data"]
    url = f"/api/client/download-jobs/{job['id']}/file"
    if password:
        url += f"?password={password}"
    return client.get(url)


def _get_analytics(client, seeded_admin):
    client.post("/api/auth/logout")
    login_as_admin(client, seeded_admin)
    return client.get("/api/admin/downloads/analytics").json()["data"]


def test_client_download_records_analytics_row(client, seeded_admin, seeded_client, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    media_a = _upload(client, seeded_album_for_client.id, "a.jpg")
    media_b = _upload(client, seeded_album_for_client.id, "b.jpg")
    expected_bytes = media_a["file_size"] + media_b["file_size"]
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    file_resp = _download_album(client, seeded_album_for_client.id)
    assert file_resp.status_code == 200

    # The FileResponse background task records the served download.
    analytics = _get_analytics(client, seeded_admin)
    assert analytics["summary"]["total_downloads"] == 1
    assert analytics["summary"]["total_transferred_bytes"] == expected_bytes
    assert analytics["summary"]["recent_24h"] == 1

    assert len(analytics["albums"]) == 1
    album_stats = analytics["albums"][0]
    assert album_stats["album_name"] == "Wedding Day"
    assert album_stats["client_name"] == "John Wedding"
    assert album_stats["download_count"] == 1
    assert album_stats["total_bytes"] == expected_bytes
    assert album_stats["last_downloaded"] is not None

    assert len(analytics["history"]) == 1
    event = analytics["history"][0]
    assert event["client_name"] == "John Wedding"
    assert event["album_name"] == "Wedding Day"
    assert event["download_type"] == "all"
    assert event["file_count"] == 2
    assert event["total_bytes"] == expected_bytes
    assert event["status"] == "completed"


def test_multiple_downloads_increment_count(client, seeded_admin, seeded_client, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")
    client.post("/api/auth/logout")

    for _ in range(3):
        login_as_client(client, seeded_client.client_uuid, "client-pass-1")
        assert _download_album(client, seeded_album_for_client.id).status_code == 200
        client.post("/api/auth/logout")

    analytics = _get_analytics(client, seeded_admin)
    assert analytics["summary"]["total_downloads"] == 3
    assert analytics["albums"][0]["download_count"] == 3
    assert len(analytics["history"]) == 3


def test_selected_download_is_marked_selected(client, seeded_admin, seeded_client, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    media_a = _upload(client, seeded_album_for_client.id, "a.jpg")
    _upload(client, seeded_album_for_client.id, "b.jpg")
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    job = client.post(
        f"/api/client/albums/{seeded_album_for_client.id}/download-jobs",
        json={"media_ids": [media_a["id"]]},
    ).json()["data"]
    file_resp = client.get(f"/api/client/download-jobs/{job['id']}/file")
    assert file_resp.status_code == 200

    analytics = _get_analytics(client, seeded_admin)
    assert analytics["summary"]["total_downloads"] == 1
    assert analytics["history"][0]["download_type"] == "selected"
    assert analytics["history"][0]["file_count"] == 1


def test_dashboard_summary_includes_downloads_summary(client, seeded_admin):
    login_as_admin(client, seeded_admin)
    resp = client.get("/api/admin/dashboard").json()["data"]
    assert resp["downloads_summary"]["total_downloads"] == 0


def test_admin_download_file_also_records_analytics(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    _upload(client, seeded_album_for_client.id, "a.jpg")

    job = client.post(
        f"/api/admin/albums/{seeded_album_for_client.id}/download-jobs", json={}
    ).json()["data"]
    file_resp = client.get(f"/api/admin/download-jobs/{job['id']}/file")
    assert file_resp.status_code == 200

    analytics = client.get("/api/admin/downloads/analytics").json()["data"]
    assert analytics["summary"]["total_downloads"] == 1
    assert analytics["history"][0]["client_name"] == "John Wedding"


def test_download_analytics_requires_admin(client, seeded_client):
    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get("/api/admin/downloads/analytics")
    assert resp.status_code == 401