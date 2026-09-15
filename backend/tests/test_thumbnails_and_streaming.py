import io

from PIL import Image

from tests.conftest import login_as_admin, login_as_client
from app.api.media_streaming import content_disposition_header
from app.services.storage_service import StorageError

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0123456789" * 50  # valid signature, not a real decodable image


def _real_jpeg_bytes(size=(800, 600)) -> bytes:
    img = Image.new("RGB", size, color=(120, 60, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_upload_generates_thumbnail_for_real_image(client, seeded_admin, seeded_album_for_client, fake_storage):
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["has_thumbnail"] is True
    # original + thumbnail = 2 files in fake storage
    assert len(fake_storage.files) == 2


def test_upload_with_undecodable_image_bytes_has_no_thumbnail(
    client, seeded_admin, seeded_album_for_client, fake_storage
):
    # Passes signature validation (starts with FFD8FF) but isn't a real,
    # decodable JPEG - thumbnail generation should fail gracefully and the
    # upload itself should still succeed.
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["has_thumbnail"] is False
    assert len(fake_storage.files) == 1  # only the original, no thumbnail


def test_media_response_never_exposes_raw_drive_ids(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    body = resp.json()["data"]
    assert "google_drive_file_id" not in body
    assert "thumbnail_reference" not in body
    assert "has_thumbnail" in body


def test_client_can_view_and_download_own_media(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    media_id = upload_resp.json()["data"]["id"]
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")

    view_resp = client.get(f"/api/client/media/{media_id}/view")
    assert view_resp.status_code == 200
    assert view_resp.headers["content-disposition"].startswith("inline")

    download_resp = client.get(f"/api/client/media/{media_id}/download")
    assert download_resp.status_code == 200
    assert download_resp.headers["content-disposition"].startswith("attachment")
    assert "photo1.jpg" in download_resp.headers["content-disposition"]

    thumb_resp = client.get(f"/api/client/media/{media_id}/thumbnail")
    assert thumb_resp.status_code == 200


def _mp4_bytes(payload_size: int = 500) -> bytes:
    # Minimal but well-formed ISO-BMFF: one "ftyp" box, then one "mdat" box
    # padded out to payload_size so range slicing has something to test.
    ftyp = b"\x00\x00\x00\x14ftypisom\x00\x00\x02\x00isomiso2"
    mdat_payload = bytes(range(256)) * (payload_size // 256 + 1)
    mdat_payload = mdat_payload[:payload_size]
    mdat_size = (8 + len(mdat_payload)).to_bytes(4, "big")
    mdat = mdat_size + b"mdat" + mdat_payload
    return ftyp + mdat


def test_upload_and_view_video_full_response(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    video_bytes = _mp4_bytes()
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("clip.mp4", video_bytes, "video/mp4")},
    )
    assert upload_resp.status_code == 200
    media_id = upload_resp.json()["data"]["id"]

    view_resp = client.get(f"/api/admin/media/{media_id}/view")
    assert view_resp.status_code == 200
    assert view_resp.headers["accept-ranges"] == "bytes"
    assert view_resp.headers["content-length"] == str(len(video_bytes))
    assert view_resp.content == video_bytes


def test_view_video_with_range_header_returns_206_partial_content(
    client, seeded_admin, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    video_bytes = _mp4_bytes(1000)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("clip.mp4", video_bytes, "video/mp4")},
    )
    media_id = upload_resp.json()["data"]["id"]

    range_resp = client.get(
        f"/api/admin/media/{media_id}/view", headers={"Range": "bytes=100-199"}
    )
    assert range_resp.status_code == 206
    assert range_resp.headers["content-range"] == f"bytes 100-199/{len(video_bytes)}"
    assert range_resp.headers["content-length"] == "100"
    assert range_resp.content == video_bytes[100:200]


def test_view_video_with_suffix_range_header(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    video_bytes = _mp4_bytes(1000)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("clip.mp4", video_bytes, "video/mp4")},
    )
    media_id = upload_resp.json()["data"]["id"]

    # "bytes=-200" means "the last 200 bytes" - what a <video> player sends
    # when scrubbing to the very end to read duration/metadata.
    range_resp = client.get(
        f"/api/admin/media/{media_id}/view", headers={"Range": "bytes=-200"}
    )
    assert range_resp.status_code == 206
    assert range_resp.content == video_bytes[-200:]


def test_view_video_with_unsatisfiable_range_returns_416(client, seeded_admin, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    video_bytes = _mp4_bytes(500)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("clip.mp4", video_bytes, "video/mp4")},
    )
    media_id = upload_resp.json()["data"]["id"]

    range_resp = client.get(
        f"/api/admin/media/{media_id}/view",
        headers={"Range": f"bytes={len(video_bytes) + 100}-{len(video_bytes) + 200}"},
    )
    assert range_resp.status_code == 416
    assert range_resp.headers["content-range"] == f"bytes */{len(video_bytes)}"


def test_upload_mov_with_leading_free_box_before_ftyp_is_accepted(
    client, seeded_admin, seeded_album_for_client
):
    # Real-world QuickTime exports sometimes emit a small "free"/"wide" box
    # before "ftyp" - this used to get rejected because the old check only
    # looked at the first 32 raw bytes for the signature substring.
    free_box = (8).to_bytes(4, "big") + b"free"
    ftyp = b"\x00\x00\x00\x14ftypqt  \x00\x00\x02\x00qt  "
    mdat = (16).to_bytes(4, "big") + b"mdat" + b"x" * 8
    video_bytes = free_box + ftyp + mdat

    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("clip.mov", video_bytes, "video/quicktime")},
    )
    assert resp.status_code == 200


def test_upload_video_with_garbage_bytes_still_rejected(client, seeded_admin, seeded_album_for_client):
    # Make sure loosening the check for legitimate leading boxes didn't
    # also loosen it for genuinely bogus content.
    login_as_admin(client, seeded_admin)
    resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("clip.mp4", b"not a real video file" * 10, "video/mp4")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FILE_SIGNATURE_MISMATCH"


def test_client_single_download_requires_download_password(
    client, seeded_admin, seeded_client, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    media_id = upload_resp.json()["data"]["id"]
    password_resp = client.post(
        f"/api/admin/clients/{seeded_client.id}/change-download-password",
        json={"password": "srt4"},
    )
    assert password_resp.status_code == 200
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    blocked = client.get(f"/api/client/media/{media_id}/download")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "DOWNLOAD_PASSWORD_REQUIRED"

    wrong = client.post("/api/client/verify-download-password", json={"password": "wrong"})
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "INVALID_DOWNLOAD_PASSWORD"

    verified = client.post("/api/client/verify-download-password", json={"password": "srt4"})
    assert verified.status_code == 200
    allowed = client.get(f"/api/client/media/{media_id}/download")
    assert allowed.status_code == 200


def test_client_cannot_download_other_clients_media(
    client, seeded_admin, seeded_client_b, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    media_id = upload_resp.json()["data"]["id"]
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client_b.client_uuid, "client-pass-2")

    for path in ("view", "download", "thumbnail"):
        resp = client.get(f"/api/client/media/{media_id}/{path}")
        assert resp.status_code == 403, f"{path} should be forbidden across clients"


def test_thumbnail_missing_returns_404(client, seeded_admin, seeded_client, seeded_album_for_client):
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", JPEG_BYTES, "image/jpeg")},  # undecodable -> no thumbnail
    )
    media_id = upload_resp.json()["data"]["id"]
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")
    resp = client.get(f"/api/client/media/{media_id}/thumbnail")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "THUMBNAIL_NOT_AVAILABLE"


def test_delete_media_removes_thumbnail_too(client, seeded_admin, seeded_album_for_client, fake_storage):
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    media_id = upload_resp.json()["data"]["id"]
    assert len(fake_storage.files) == 2  # original + thumbnail

    delete_resp = client.delete(f"/api/admin/media/{media_id}")
    assert delete_resp.status_code == 200
    assert len(fake_storage.files) == 0


def test_content_disposition_header_with_emoji_filename_is_latin1_safe():
    # A filename containing an emoji used to crash every view/download
    # response with UnicodeEncodeError - Starlette encodes HTTP headers as
    # latin-1, and the plain filename= fallback kept the raw (non-latin-1)
    # characters. The RFC 5987 filename* part must carry the full name.
    header = content_disposition_header("inline", "my \U0001f9f8 photo.jpg")

    header.encode("latin-1")  # must not raise UnicodeEncodeError
    assert "%F0%9F%A7%B8" in header  # percent-encoded emoji (UTF-8)
    assert 'filename="my  photo.jpg"' in header  # ASCII fallback, non-ascii chars stripped


def test_upload_and_view_image_with_non_ascii_filename_succeeds(
    client, seeded_admin, seeded_album_for_client
):
    # End-to-end version of the fix: upload a file with a non-latin-1
    # character in its name and confirm the view/download endpoints return
    # 200 instead of 500.
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("my \U0001f9f8 photo.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    assert upload_resp.status_code == 200
    media_id = upload_resp.json()["data"]["id"]

    view_resp = client.get(f"/api/admin/media/{media_id}/view")
    assert view_resp.status_code == 200
    assert view_resp.headers["content-disposition"].encode("latin-1") is not None

    dl_resp = client.get(f"/api/admin/media/{media_id}/download")
    assert dl_resp.status_code == 200


# ---------------------------------------------------------------------------
# Thumbnail auth matrix + transport-failure streaming behavior
#
# The ECONNRESET the browser/Vite proxy saw on thumbnail grids: a Drive
# connection reset mid-response raised http.client.IncompleteRead (a pure
# transport failure, not an OSError/HttpLib2Error/ConnectionError), which
# google_drive_service._retry() never translated to StorageError - so it
# escaped download()'s generator AFTER the StreamingResponse headers were
# already committed, and uvicorn aborted the connection. The proxy saw an
# abrupt reset instead of a truncated-but-finished response.
#
# The fix lives at the ONE chokepoint every Drive call goes through:
# _is_retryable_google_error()/ _retry() in google_drive_service.py now
# classify http.client.HTTPException as retryable and translate it to
# StorageError once attempts are exhausted. These endpoint tests pin down
# the OTHER half of the contract: whatever the storage layer raises as
# StorageError, the thumbnail route must finish the response cleanly
# (truncated body / clean {success:false} JSON) rather than let a raw
# exception abort a committed response. Auth stays intact - nothing here
# weakens the cookie checks.
# ---------------------------------------------------------------------------


def test_admin_thumbnail_streams_200(client, seeded_admin, seeded_album_for_client):
    """The admin thumbnail URL (every album-grid cell for a logged-in
    studio) succeeds end-to-end."""
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    assert upload_resp.status_code == 200
    media_id = upload_resp.json()["data"]["id"]

    resp = client.get(f"/api/admin/media/{media_id}/thumbnail")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")


def test_thumbnail_endpoints_require_login(client, seeded_media_for_client):
    """Logged out, both thumbnail routes must 401 - the cookie checks are
    untouched by the transport fix."""
    admin_resp = client.get(f"/api/admin/media/{seeded_media_for_client.id}/thumbnail")
    assert admin_resp.status_code == 401
    client_resp = client.get(f"/api/client/media/{seeded_media_for_client.id}/thumbnail")
    assert client_resp.status_code == 401


def test_thumbnail_mid_stream_storage_error_truncates_cleanly(
    client, fake_storage, monkeypatch, seeded_admin, seeded_album_for_client
):
    """If the storage layer reports a transport failure mid-stream (post-fix
    IncompleteRead -> StorageError), the connection must FINISH normally with
    the bytes already sent - exactly what the browser needs instead of an
    ECONNRESET."""
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    assert upload_resp.status_code == 200
    media_id = upload_resp.json()["data"]["id"]

    def _flaky_download(provider_file_id, *, range_start=None, range_end=None):
        yield b"partial-thumbnail-"
        raise StorageError("simulated Drive truncated response (post-fix)")

    monkeypatch.setattr(fake_storage, "download", _flaky_download)
    resp = client.get(f"/api/admin/media/{media_id}/thumbnail")
    assert resp.status_code == 200
    assert resp.content == b"partial-thumbnail-"


def test_thumbnail_storage_error_before_stream_returns_502(
    client, fake_storage, monkeypatch, seeded_admin, seeded_album_for_client
):
    """A transport failure BEFORE the stream starts must be a clean
    {success:false} 502, not a traceback 500."""
    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("photo1.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    assert upload_resp.status_code == 200
    media_id = upload_resp.json()["data"]["id"]

    def _fail_get_file(provider_file_id):
        raise StorageError("simulated Drive outage")

    monkeypatch.setattr(fake_storage, "get_file", _fail_get_file)
    resp = client.get(f"/api/admin/media/{media_id}/thumbnail")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "STORAGE_DOWNLOAD_FAILED"


# ---------------------------------------------------------------------------
# Multiple simultaneous media requests
#
# Regression coverage for the download()-side thread-pool nesting fix in
# google_drive_service.py: next_chunk() used to be double-wrapped (the
# per-call httplib2 socket timeout AND a redundant run_with_timeout() on
# top of it, submitting to timeout_utils.py's small, GLOBAL, app-wide
# executor). A gallery grid firing dozens of concurrent thumbnail/view
# requests at once - exactly what this test does - saturated that shared
# pool, so unrelated chunk fetches (and even unrelated routes competing
# for the same underlying sync-route thread pool) could time out purely
# from queueing contention, not real network slowness, truncating
# already-committed StreamingResponses (ECONNRESET at the proxy, a video
# stuck at 0:00). These tests don't reproduce real Drive latency, but they
# do exercise the real concurrent-request path end-to-end and pin down
# that it still works correctly (no cross-request data mixing, correct
# per-item bytes, auth still enforced) with many requests in flight together.
# ---------------------------------------------------------------------------

import concurrent.futures


def test_multiple_simultaneous_thumbnail_and_view_requests_all_succeed(
    client, seeded_admin, seeded_album_for_client
):
    login_as_admin(client, seeded_admin)

    media_ids = []
    for i in range(8):
        resp = client.post(
            "/api/admin/media/upload",
            data={"album_id": str(seeded_album_for_client.id)},
            files={"file": (f"photo{i}.jpg", _real_jpeg_bytes(), "image/jpeg")},
        )
        assert resp.status_code == 200
        media_ids.append(resp.json()["data"]["id"])

    def _fetch(path_and_id):
        path, media_id = path_and_id
        return path, media_id, client.get(f"/api/admin/media/{media_id}/{path}")

    requests = [("thumbnail", mid) for mid in media_ids] + [("view", mid) for mid in media_ids]

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(requests)) as pool:
        results = list(pool.map(_fetch, requests))

    assert len(results) == len(requests)
    for path, media_id, resp in results:
        assert resp.status_code == 200, f"{path} for media {media_id} failed: {resp.text}"
        if path == "thumbnail":
            assert resp.headers["content-type"].startswith("image/jpeg")


def test_concurrent_client_media_requests_do_not_cross_client_boundaries(
    client, seeded_admin, seeded_client, seeded_client_b, seeded_album_for_client
):
    """Fires simultaneous requests from two independently-authenticated
    TestClient instances (each its own cookie jar, like two separate
    browser sessions) and confirms ownership scoping still holds under
    concurrency - ownership checks happen before any Drive/thread-pool
    work, so this pins down that the thread-pool change didn't blur
    request isolation between concurrently-served requests."""
    from starlette.testclient import TestClient

    from app.main import app

    login_as_admin(client, seeded_admin)
    upload_resp = client.post(
        "/api/admin/media/upload",
        data={"album_id": str(seeded_album_for_client.id)},
        files={"file": ("owned.jpg", _real_jpeg_bytes(), "image/jpeg")},
    )
    media_id = upload_resp.json()["data"]["id"]
    client.post("/api/auth/logout")

    login_as_client(client, seeded_client.client_uuid, "client-pass-1")

    # A second TestClient sharing the same app/dependency-overrides (the
    # `client` fixture already wired get_db/get_storage_service onto the
    # shared `app`) but with its OWN cookie jar - genuinely independent of
    # `client`'s session, the way a second browser tab would be.
    other_client = TestClient(app)
    login_as_client(other_client, seeded_client_b.client_uuid, "client-pass-2")

    def _fetch(which):
        c = client if which == "owner" else other_client
        return which, c.get(f"/api/client/media/{media_id}/thumbnail")

    requests = (["owner"] * 5) + (["other"] * 5)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_fetch, requests))

    owner_results = [r for which, r in results if which == "owner"]
    other_results = [r for which, r in results if which == "other"]
    assert all(r.status_code == 200 for r in owner_results)
    assert all(r.status_code == 403 for r in other_results)
