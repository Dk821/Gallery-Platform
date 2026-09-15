"""
Tests for the ffmpeg system-dependency check: SYSTEM_REQUIREMENTS.md and
app/workers/thumbnail_worker.is_ffmpeg_available() document/detect that
ffmpeg is an OS-level dependency, not something requirements.txt can pin.
These tests make sure the check itself is correct, cached, and actually
surfaced in the places an operator/admin would look (health endpoint,
admin dashboard) rather than only in scattered log lines.
"""

from app.workers import thumbnail_worker
from tests.conftest import login_as_admin


def _reset_ffmpeg_cache():
    thumbnail_worker.is_ffmpeg_available.cache_clear()


def test_is_ffmpeg_available_reflects_shutil_which(monkeypatch):
    _reset_ffmpeg_cache()
    monkeypatch.setattr(thumbnail_worker.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert thumbnail_worker.is_ffmpeg_available() is True
    _reset_ffmpeg_cache()


def test_is_ffmpeg_available_false_when_binary_missing(monkeypatch):
    _reset_ffmpeg_cache()
    monkeypatch.setattr(thumbnail_worker.shutil, "which", lambda name: None)
    assert thumbnail_worker.is_ffmpeg_available() is False
    _reset_ffmpeg_cache()


def test_is_ffmpeg_available_only_shells_out_once(monkeypatch):
    _reset_ffmpeg_cache()
    call_count = {"n": 0}

    def _fake_which(name):
        call_count["n"] += 1
        return "/usr/bin/ffmpeg"

    monkeypatch.setattr(thumbnail_worker.shutil, "which", _fake_which)
    for _ in range(5):
        thumbnail_worker.is_ffmpeg_available()
    assert call_count["n"] == 1  # lru_cache means shutil.which only ran once
    _reset_ffmpeg_cache()


def test_generate_video_poster_skips_subprocess_when_ffmpeg_missing(monkeypatch):
    import io

    _reset_ffmpeg_cache()
    monkeypatch.setattr(thumbnail_worker.shutil, "which", lambda name: None)

    called = {"ran": False}

    def _fake_run(*args, **kwargs):
        called["ran"] = True
        raise AssertionError("subprocess.run should never be called when ffmpeg is missing")

    monkeypatch.setattr(thumbnail_worker.subprocess, "run", _fake_run)

    result = thumbnail_worker.generate_video_poster(io.BytesIO(b"not a real video"), "clip.mp4")
    assert result is None
    assert called["ran"] is False
    _reset_ffmpeg_cache()


def test_health_endpoint_reports_ffmpeg_availability(client, monkeypatch):
    _reset_ffmpeg_cache()
    monkeypatch.setattr(thumbnail_worker.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["ffmpeg_available"] is True
    _reset_ffmpeg_cache()


def test_admin_dashboard_reports_ffmpeg_availability(client, seeded_admin, monkeypatch):
    _reset_ffmpeg_cache()
    monkeypatch.setattr(thumbnail_worker.shutil, "which", lambda name: None)

    login_as_admin(client, seeded_admin)
    resp = client.get("/api/admin/dashboard")
    assert resp.status_code == 200
    assert resp.json()["data"]["ffmpeg_available"] is False
    _reset_ffmpeg_cache()
