from functools import lru_cache

from app.config.settings import get_settings
from app.services.google_drive_service import GoogleDriveStorage
from app.services.storage_service import StorageService


@lru_cache
def _build_storage_service() -> StorageService:
    # A single process-wide instance is fine: GoogleDriveStorage holds no
    # per-request state, just a configured API client.
    return GoogleDriveStorage(get_settings())


def get_storage_service() -> StorageService:
    """
    FastAPI dependency. In tests, override this with
    `app.dependency_overrides[get_storage_service] = lambda: FakeStorageService()`
    so nothing ever calls the real Google Drive API from the test suite
    (spec Section 44).
    """
    return _build_storage_service()
