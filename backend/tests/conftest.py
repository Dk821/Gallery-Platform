import os
import tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ZIP_TEMP_DIR", os.path.join(tempfile.gettempdir(), "gallery_zip_jobs_test"))

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import connection as db_connection
from app.database.connection import Base, get_db
from app.main import app
from app.models.admin import Admin
from app.models.album import Album
from app.models.client import Client
from app.models.media import Media
from app.security.password import hash_password
from app.services.circuit_breaker import get_drive_circuit_breaker
from app.services.storage_provider import get_storage_service
from tests.fakes import FakeStorageService


# Test-only DDL compatibility shim, not an application change: SQLite only
# treats a PK column as an alias for its auto-incrementing internal rowid
# when the column's declared type is exactly "INTEGER" - BigInteger (used
# throughout the models for MySQL, the real production DB) compiles to
# "BIGINT" and doesn't qualify, so autoincrement silently doesn't happen
# under sqlite:///:memory:. Compiling BigInteger to "INTEGER" for the
# sqlite dialect only (MySQL/other dialects are untouched) fixes that for
# the test DB without changing any model source.
@compiles(BigInteger, "sqlite")
def _big_integer_as_sqlite_integer(type_, compiler, **kw):
    return "INTEGER"


TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


@pytest.fixture()
def db_session():
    Base.metadata.create_all(TEST_ENGINE)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(TEST_ENGINE)


@pytest.fixture()
def fake_storage():
    return FakeStorageService()


@pytest.fixture(autouse=True)
def _reset_drive_circuit_breaker():
    # The Google Drive circuit breaker (app/services/circuit_breaker.py) is
    # a single process-wide singleton, same as the upload concurrency
    # limiter and disk reservation tracker. Without this, a test that
    # deliberately induces enough consecutive Drive connectivity failures
    # to trip it (see test_drive_resumable_upload.py /
    # test_httplib2_cleanup_bug.py) would leave it open for its cooldown
    # window, silently short-circuiting whatever unrelated test happens to
    # run next in the same pytest process.
    get_drive_circuit_breaker().reset()
    yield
    get_drive_circuit_breaker().reset()


@pytest.fixture()
def client(db_session, fake_storage, monkeypatch):
    def _override_get_db():
        yield db_session

    def _override_get_storage():
        return fake_storage

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_storage_service] = _override_get_storage
    # process_download_job (the ZIP background worker) runs detached from
    # any request and creates its own session via
    # app.database.connection.SessionLocal - patch that to point at the
    # same isolated per-test engine everything else here uses. Without
    # this, a DownloadJob row committed through the request's db_session
    # would be invisible to the worker, which would otherwise connect to a
    # different, empty in-memory SQLite database.
    monkeypatch.setattr(db_connection, "SessionLocal", TestSessionLocal)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_admin(db_session):
    admin = Admin(name="Studio Owner", email="owner@studio.dev", password_hash=hash_password("correct-horse-1"))
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


@pytest.fixture()
def seeded_client(db_session):
    c = Client(
        client_uuid="11111111-1111-1111-1111-111111111111",
        client_name="John Wedding",
        password_hash=hash_password("client-pass-1"),
        status="active",
        drive_folder_id="folder-test-client-a",
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c


@pytest.fixture()
def seeded_client_b(db_session):
    c = Client(
        client_uuid="22222222-2222-2222-2222-222222222222",
        client_name="Jane Portrait",
        password_hash=hash_password("client-pass-2"),
        status="active",
        drive_folder_id="folder-test-client-b",
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c


@pytest.fixture()
def seeded_album_for_client(db_session, seeded_client):
    album = Album(
        client_id=seeded_client.id,
        album_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        album_name="Wedding Day",
        status="active",
        drive_folder_id="folder-test-album-a",
    )
    db_session.add(album)
    db_session.commit()
    db_session.refresh(album)
    return album


@pytest.fixture()
def seeded_second_album_for_client(db_session, seeded_client):
    # A second album belonging to the SAME client as seeded_album_for_client -
    # used for "move media within the same client" tests.
    album = Album(
        client_id=seeded_client.id,
        album_uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        album_name="Reception",
        status="active",
        drive_folder_id="folder-test-album-a2",
    )
    db_session.add(album)
    db_session.commit()
    db_session.refresh(album)
    return album


@pytest.fixture()
def seeded_album_for_client_b(db_session, seeded_client_b):
    # Used for "cannot move media across clients" tests.
    album = Album(
        client_id=seeded_client_b.id,
        album_uuid="cccccccc-cccc-cccc-cccc-cccccccccccc",
        album_name="Portrait Session",
        status="active",
        drive_folder_id="folder-test-album-b",
    )
    db_session.add(album)
    db_session.commit()
    db_session.refresh(album)
    return album


@pytest.fixture()
def seeded_media_for_client(db_session, seeded_client, seeded_album_for_client):
    media = Media(
        client_id=seeded_client.id,
        album_id=seeded_album_for_client.id,
        file_uuid="ffffffff-ffff-ffff-ffff-ffffffffffff",
        file_name="photo1.jpg",
        file_type="photo",
        mime_type="image/jpeg",
        file_size=1024,
        google_drive_file_id="fake-drive-id-1",
        status="ready",
    )
    db_session.add(media)
    db_session.commit()
    db_session.refresh(media)
    return media


def login_as_client(test_client, gallery_id: str, password: str):
    return test_client.post("/api/auth/client/login", json={"gallery_id": gallery_id, "password": password})


def login_as_admin(test_client, seeded_admin):
    return test_client.post(
        "/api/auth/admin/login", json={"email": seeded_admin.email, "password": "correct-horse-1"}
    )
