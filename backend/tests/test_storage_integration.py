from app.models.album import Album
from app.models.client import Client
from tests.conftest import login_as_admin, login_as_client

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0123456789" * 50  # valid JPEG signature, fake body


def test_create_client_provisions_drive_folder(client, seeded_admin, fake_storage, db_session):
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/clients", json={"client_name": "New Client", "password": "good"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(fake_storage.folders) == 1
    folder_id = next(iter(fake_storage.folders))
    db_client = db_session.query(Client).filter_by(id=data["id"]).first()
    assert fake_storage.folders[folder_id]["name"] == f"New Client_C_{db_client.folder_uid}"


def test_create_album_provisions_subfolder_under_client(
    client, seeded_admin, seeded_client, fake_storage, db_session
):
    login_as_admin(client, seeded_admin)
    resp = client.post("/api/admin/albums", json={"client_id": seeded_client.id, "album_name": "Reception"})
    assert resp.status_code == 200
    album_id = resp.json()["data"]["id"]
    db_album = db_session.query(Album).filter_by(id=album_id).first()
    expected_name = f"Reception_A_{db_album.folder_uid}"
    folder = next(f for f in fake_storage.folders.values() if f["name"] == expected_name)
    assert folder["parent_folder_id"] == seeded_client.drive_folder_id


def test_delete_client_deletes_drive_folder(client, seeded_admin, seeded_client, fake_storage):
    login_as_admin(client, seeded_admin)
    resp = client.delete(f"/api/admin/clients/{seeded_client.id}")
    assert resp.status_code == 200
    assert seeded_client.drive_folder_id in fake_storage.deleted_folder_ids


def test_delete_album_deletes_drive_folder(client, seeded_admin, seeded_album_for_client, fake_storage):
    login_as_admin(client, seeded_admin)
    resp = client.delete(f"/api/admin/albums/{seeded_album_for_client.id}")
    assert resp.status_code == 200
    assert seeded_album_for_client.drive_folder_id in fake_storage.deleted_folder_ids


def test_create_client_folder_failure_returns_502_and_no_client_created(client, seeded_admin, fake_storage):
    login_as_admin(client, seeded_admin)
    fake_storage.fail_next_create_folder = True
    resp = client.post("/api/admin/clients", json={"client_name": "Ghost", "password": "good"})
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "STORAGE_FOLDER_CREATE_FAILED"

    list_resp = client.get("/api/admin/clients")
    names = [c["client_name"] for c in list_resp.json()["data"]["items"]]
    assert "Ghost" not in names


def test_upload_media_success(client, seeded_admin, seeded_album_for_client, fake_storage):
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["file_type"] == "photo"
    assert body["status"] == "ready"
    assert len(fake_storage.files) == 1


def test_upload_media_rejects_mismatched_signature(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", b"not-actually-a-jpeg-file-content", "image/jpeg")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FILE_SIGNATURE_MISMATCH"


def test_upload_media_rejects_disallowed_extension(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("virus.exe", b"MZ\x90\x00" + b"x" * 20, "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_media_rejects_empty_file(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", b"", "image/jpeg")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "EMPTY_FILE"


def test_upload_media_storage_failure_returns_502(client, seeded_admin, seeded_album_for_client, fake_storage):
    login_as_admin(client, seeded_admin)
    fake_storage.fail_next_upload = True
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "STORAGE_UPLOAD_FAILED"


def test_delete_media_removes_from_storage_and_db(client, seeded_admin, seeded_album_for_client, fake_storage):
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    media_id = upload_resp.json()["data"]["id"]

    delete_resp = client.delete(f"/api/admin/media/{media_id}")
    assert delete_resp.status_code == 200
    assert len(fake_storage.files) == 0


def test_client_can_see_uploaded_media_after_admin_upload(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get("/api/client/media")
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1


def test_storage_overview_endpoint(client, seeded_admin):
    login_as_admin(client, seeded_admin)
    resp = client.get("/api/admin/storage")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "our_metadata" in data
    assert "drive_quota" in data
    assert data["drive_quota"]["available"] is True  # FakeStorageService always reports available


def test_storage_overview_includes_vps_disk_headroom(client, seeded_admin):
    # This is the actual local disk on the server (where uploads are
    # spooled / ZIPs are written), distinct from drive_quota above which
    # is Google Drive's own storage quota.
    login_as_admin(client, seeded_admin)
    resp = client.get("/api/admin/storage")
    assert resp.status_code == 200
    vps_disk = resp.json()["data"]["vps_disk"]

    assert vps_disk["total_bytes"] > 0
    assert vps_disk["free_bytes"] >= 0
    assert vps_disk["used_bytes"] >= 0
    assert vps_disk["reserved_bytes"] == 0  # nothing mid-upload during this test
    assert 0 <= vps_disk["percent_used"] <= 100
    assert vps_disk["effective_available_bytes"] >= 0


def test_disk_headroom_accounts_for_active_reservations():
    from app.services.disk_service import DiskReservationTracker

    tracker = DiskReservationTracker()
    before = tracker.get_headroom(min_free_bytes=0)

    tracker.try_reserve("upload:1", 1_000_000, min_free_bytes=0)
    during = tracker.get_headroom(min_free_bytes=0)

    assert during["reserved_bytes"] == 1_000_000
    # effective_available should have dropped by roughly the reservation
    # (allow slack since real disk_usage() can shift between calls).
    assert during["effective_available_bytes"] <= before["effective_available_bytes"]

    tracker.release("upload:1")
    after = tracker.get_headroom(min_free_bytes=0)
    assert after["reserved_bytes"] == 0


def test_disk_headroom_never_reports_negative_available_bytes():
    from app.services.disk_service import DiskReservationTracker

    tracker = DiskReservationTracker()
    # An absurdly large min_free_bytes forces the "would-be-negative" path.
    headroom = tracker.get_headroom(min_free_bytes=10**18)
    assert headroom["effective_available_bytes"] == 0


def test_storage_overview_includes_analytics_sections(client, seeded_admin):
    login_as_admin(client, seeded_admin)
    resp = client.get("/api/admin/storage")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "daily_transfer" in data
    assert "storage_by_client" in data
    assert "storage_by_file_type" in data
    assert "upload_reliability" in data


def test_daily_transfer_series_is_zero_filled_and_ordered(client, seeded_admin):
    login_as_admin(client, seeded_admin)
    resp = client.get("/api/admin/storage?days=7")
    assert resp.status_code == 200
    series = resp.json()["data"]["daily_transfer"]

    assert len(series) == 7  # every day present, even with zero activity
    dates = [row["date"] for row in series]
    assert dates == sorted(dates)  # oldest first
    for row in series:
        assert row["upload_bytes"] == 0
        assert row["download_bytes"] == 0


def test_daily_transfer_series_reflects_completed_upload(
    client, seeded_admin, seeded_album_for_client, db_session
):
    from app.models.upload_session import UploadSession

    login_as_admin(client, seeded_admin)
    session = UploadSession(
        upload_id="analytics-test-1",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="photo.jpg",
        total_bytes=12_345,
        bytes_uploaded=12_345,
        status="completed",
    )
    db_session.add(session)
    db_session.commit()

    resp = client.get("/api/admin/storage?days=1")
    series = resp.json()["data"]["daily_transfer"]
    assert len(series) == 1
    assert series[0]["upload_bytes"] == 12_345
    assert series[0]["upload_count"] == 1


def test_daily_transfer_series_ignores_non_completed_uploads(
    client, seeded_admin, seeded_album_for_client, db_session
):
    from app.models.upload_session import UploadSession

    login_as_admin(client, seeded_admin)
    for status in ("failed", "cancelled", "uploading", "queued"):
        db_session.add(
            UploadSession(
                upload_id=f"analytics-{status}",
                admin_id=seeded_admin.id,
                album_id=seeded_album_for_client.id,
                filename="photo.jpg",
                total_bytes=99_999,
                status=status,
            )
        )
    db_session.commit()

    resp = client.get("/api/admin/storage?days=1")
    series = resp.json()["data"]["daily_transfer"]
    assert series[0]["upload_bytes"] == 0
    assert series[0]["upload_count"] == 0


def test_storage_by_client_reflects_uploaded_media(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )

    resp = client.get("/api/admin/storage")
    by_client = resp.json()["data"]["storage_by_client"]
    assert len(by_client) == 1
    assert by_client[0]["client_id"] == seeded_client.id
    assert by_client[0]["file_count"] == 1
    assert by_client[0]["total_bytes"] == len(JPEG_BYTES)


def test_storage_by_file_type_separates_photos_and_videos(
    client, seeded_admin, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )

    resp = client.get("/api/admin/storage")
    by_type = {row["file_type"]: row for row in resp.json()["data"]["storage_by_file_type"]}
    assert by_type["photo"]["file_count"] == 1
    assert by_type["photo"]["total_bytes"] == len(JPEG_BYTES)


def test_upload_reliability_reports_status_breakdown_and_success_rate(
    client, seeded_admin, seeded_album_for_client, db_session
):
    from app.models.upload_session import UploadSession

    login_as_admin(client, seeded_admin)
    statuses = ["completed", "completed", "completed", "failed"]
    for i, status in enumerate(statuses):
        db_session.add(
            UploadSession(
                upload_id=f"reliability-{i}",
                admin_id=seeded_admin.id,
                album_id=seeded_album_for_client.id,
                filename="photo.jpg",
                total_bytes=1000,
                status=status,
            )
        )
    db_session.commit()

    resp = client.get("/api/admin/storage?days=30")
    reliability = resp.json()["data"]["upload_reliability"]
    assert reliability["by_status"]["completed"] == 3
    assert reliability["by_status"]["failed"] == 1
    assert reliability["recent_total"] == 4
    assert reliability["recent_completed"] == 3
    assert reliability["recent_success_rate_percent"] == 75.0


def test_largest_files_ordered_by_size_descending(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    small = JPEG_BYTES
    large = JPEG_BYTES + b"0" * 500

    client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("small.jpg", small, "image/jpeg")},
    )
    client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("large.jpg", large, "image/jpeg")},
    )

    resp = client.get("/api/admin/storage")
    largest = resp.json()["data"]["largest_files"]
    assert len(largest) == 2
    assert largest[0]["file_name"] == "large.jpg"
    assert largest[0]["file_size"] == len(large)
    assert largest[0]["client_name"] == seeded_client.client_name
    assert largest[0]["album_name"] == seeded_album_for_client.album_name
    assert largest[1]["file_name"] == "small.jpg"


def test_largest_files_respects_limit(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    for i in range(12):
        client.post(
            "/api/admin/media/upload",
            data={"album_id": str(seeded_album_for_client.id)},
            files={"file": (f"photo{i}.jpg", JPEG_BYTES + bytes([i]) * 10, "image/jpeg")},
        )

    resp = client.get("/api/admin/storage")
    largest = resp.json()["data"]["largest_files"]
    assert len(largest) == 10  # default limit


def test_orphan_candidate_count_reflects_stale_upload_sessions(
    client, seeded_admin, seeded_album_for_client, db_session
):
    import datetime

    from app.models.upload_session import UploadSession

    login_as_admin(client, seeded_admin)

    # Baseline: no orphans yet.
    resp = client.get("/api/admin/storage")
    assert resp.json()["data"]["orphan_candidate_count"] == 0

    # A stale session with a drive_file_id but never completed, older than
    # the grace period - exactly what orphan_reconciliation looks for.
    stale = UploadSession(
        upload_id="orphan-candidate-1",
        admin_id=seeded_admin.id,
        album_id=seeded_album_for_client.id,
        filename="ghost.jpg",
        total_bytes=1000,
        status="uploading",
        drive_file_id="drive-file-ghost-1",
    )
    db_session.add(stale)
    db_session.commit()
    stale.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=72)
    db_session.commit()

    resp = client.get("/api/admin/storage")
    assert resp.json()["data"]["orphan_candidate_count"] == 1


def test_orphan_candidate_count_excludes_recent_and_completed_sessions(
    client, seeded_admin, seeded_album_for_client, db_session
):
    from app.models.upload_session import UploadSession

    login_as_admin(client, seeded_admin)

    # Recent (within grace period) - not yet a candidate.
    db_session.add(
        UploadSession(
            upload_id="recent-in-flight",
            admin_id=seeded_admin.id,
            album_id=seeded_album_for_client.id,
            filename="in_progress.jpg",
            total_bytes=1000,
            status="uploading",
            drive_file_id="drive-file-recent",
        )
    )
    # Completed - has a Media row, never an orphan regardless of age.
    db_session.add(
        UploadSession(
            upload_id="completed-old",
            admin_id=seeded_admin.id,
            album_id=seeded_album_for_client.id,
            filename="done.jpg",
            total_bytes=1000,
            status="completed",
            drive_file_id="drive-file-done",
        )
    )
    db_session.commit()

    resp = client.get("/api/admin/storage")
    assert resp.json()["data"]["orphan_candidate_count"] == 0
