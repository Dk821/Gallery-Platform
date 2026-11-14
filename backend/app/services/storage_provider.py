from functools import lru_cache

from app.config.settings import get_settings
from app.services.storage_service import StorageError, StorageService


@lru_cache
def _build_storage_service() -> StorageService:
    # One process-wide instance is fine: it holds no per-request state, just a
    # configured API client. The SDKs are imported lazily so only the selected
    # backend's dependencies are needed.
    settings = get_settings()
    provider = (settings.storage_provider or "google_drive").strip().lower()
    if provider == "google_drive":
        from app.services.google_drive_service import GoogleDriveStorage

        return GoogleDriveStorage(settings)
    if provider == "r2":
        from app.services.r2_storage import R2Storage

        return R2Storage(settings)
    raise StorageError(f"Unknown STORAGE_PROVIDER '{settings.storage_provider}' (use google_drive or r2).")


def get_storage_service() -> StorageService:
    """
    FastAPI dependency. In tests, override this with
    `app.dependency_overrides[get_storage_service] = lambda: FakeStorageService()`
    so nothing ever calls the real storage API from the test suite
    (spec Section 44).
    """
    return _build_storage_service()
