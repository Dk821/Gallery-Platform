from tests.conftest import login_as_admin


def test_dashboard_requires_admin(client):
    resp = client.get("/api/admin/dashboard")
    assert resp.status_code == 401


def test_dashboard_counts(client, seeded_admin, seeded_client, seeded_client_b, seeded_album_for_client, seeded_media_for_client):
    login_as_admin(client, seeded_admin)
    resp = client.get("/api/admin/dashboard")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_clients"] == 2
    assert data["active_clients"] == 2
    assert data["total_albums"] == 1
    assert data["total_photos"] == 1
    assert data["total_videos"] == 0
    assert data["storage_used_bytes"] == 1024
    assert len(data["recent_clients"]) == 2
