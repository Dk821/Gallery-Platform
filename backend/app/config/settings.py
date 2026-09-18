from functools import lru_cache
from pathlib import Path
import tempfile
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str

    # Google Drive
    google_drive_client_id: str = ""
    google_drive_client_secret: str = ""
    google_drive_refresh_token: str = ""
    google_drive_root_folder_id: str = ""

    # Sessions
    secret_key: str
    session_ttl_minutes: int = 1440
    # Set to True when the frontend is hosted on a DIFFERENT origin than
    # this backend (e.g. frontend on Vercel, backend on a VPS under a
    # different domain). Cross-origin fetch/XHR calls only carry cookies
    # when they're marked SameSite=None - and browsers require Secure
    # (HTTPS) on any SameSite=None cookie, so this also forces `secure`.
    # Leave False for same-origin deployments (frontend and backend behind
    # the same domain/reverse proxy) to keep the stronger SameSite=Lax
    # default, which offers better baseline CSRF protection.
    cross_site_frontend: bool = False

    # CORS
    cors_origins: str = ""

    # Uploads
    max_upload_size_bytes: int = 10 * 1024 * 1024 * 1024
    allowed_image_types: str = "jpg,jpeg,png,webp,gif"
    allowed_video_types: str = "mp4,mov,webm"

    # ZIP download jobs
    zip_temp_dir: str = str(Path(tempfile.gettempdir()) / "gallery_zip_jobs")
    zip_job_ttl_hours: int = 24  # how long a completed ZIP stays downloadable before cleanup
    zip_job_max_files: int = 5000  # sanity ceiling on a single ZIP job's size
    # How many files the ZIP job prefetches from storage concurrently before
    # writing them into the archive. Downloads are network-bound, so a modest
    # concurrency multiplies throughput on multi-file jobs; memory stays flat
    # because each prefetch lands in a temp file on ZIP_TEMP_DIR.
    zip_job_parallel_downloads: int = 4

    # --- Resumable Google Drive upload hardening ---------------------------
    # How many uploads are allowed to be actively transferring to Google
    # Drive at once. Waiting uploads block (cheaply, on a semaphore) rather
    # than all firing at the provider simultaneously.
    upload_max_concurrent: int = 3
    # A second, OUTER limit on how many uploads may be in the
    # reserve-disk-space -> transfer-to-storage pipeline at once, server
    # wide - covers the case where a client fires many uploads in one
    # burst (e.g. selecting a whole shoot's worth of files at once in the
    # admin UI). This is looser than upload_max_concurrent: up to this
    # many requests can be holding a disk reservation and waiting their
    # turn, of which upload_max_concurrent are actually transferring to
    # Drive at any given moment. Must be >= upload_max_concurrent.
    upload_max_concurrent_requests: int = 8
    # How long an upload request will wait for a processing slot (see
    # upload_max_concurrent_requests) before giving up and returning a
    # clean 503 rather than hanging indefinitely under sustained overload.
    upload_queue_wait_seconds: float = 45.0
    # Resumable upload chunk size. Google requires chunk sizes to be a
    # multiple of 256 KiB (except the final chunk) - non-aligned values are
    # rounded up to the nearest 256 KiB multiple where this is used.
    upload_chunk_size_mb: float = 8
    upload_max_retries: int = 5
    upload_initial_backoff_seconds: float = 0.5
    upload_max_backoff_seconds: float = 20.0
    # Extra ceiling on a single file's size, independent of
    # max_upload_size_bytes, expressed in MB for convenience. The effective
    # limit is the smaller of the two.
    upload_max_file_size_mb: int = 10240
    # Minimum free disk space (GB) that must remain available, accounting
    # for every other upload's reservation, before a new upload is accepted.
    upload_min_free_disk_gb: float = 5.0
    # Per-chunk network timeout, and an overall ceiling for a single
    # upload's total transfer time.
    upload_chunk_timeout: int = 120
    upload_session_timeout: int = 3600
    # How long a Drive file with no matching database record is left alone
    # before it's eligible to be treated as a confirmed orphan.
    orphan_file_grace_period_hours: int = 48

    # --- Post-direct-upload thumbnail generation ----------------------------
    # Now that the original file goes Browser -> Drive directly, this
    # server never holds its bytes during upload. Thumbnail/poster
    # generation still needs actual pixel data, so it's done as a
    # deliberate, separate, best-effort step AFTER the file is already
    # safely in Drive: a small/bounded read-back of the just-uploaded
    # file, not a re-transfer of the original upload path. These caps keep
    # that read-back small and bound its impact on VPS bandwidth/disk.
    # A file over the relevant cap simply gets no thumbnail (Section 15/22:
    # already a non-fatal, best-effort feature).
    thumbnail_image_source_max_mb: float = 25
    # Videos are read back to a temp file (ffmpeg needs to seek a real
    # file) reusing disk_service's same reservation tracker used for the
    # old upload-spooling path, so this still can't run the VPS out of
    # disk even for a large video.
    thumbnail_video_source_max_mb: float = 1024

    environment: str = "development"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def effective_cors_origins(self) -> list[str]:
        # The single source of truth for "which origins does this
        # deployment actually trust" - cors_origin_list alone omits the
        # localhost:5173 dev fallback that main.py's CORSMiddleware falls
        # back to when CORS_ORIGINS is unset, so anything else that needs
        # to check "is this origin one we trust" (e.g. validating the
        # Origin forwarded to Drive's resumable-session initiation, see
        # admin_media.py) must use THIS, not cors_origin_list directly, or
        # it silently disagrees with what the CORS middleware itself
        # allows in local dev.
        return self.cors_origin_list or ["http://localhost:5173"]

    @property
    def allowed_image_extensions(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_image_types.split(",") if e.strip()}

    @property
    def allowed_video_extensions(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_video_types.split(",") if e.strip()}

    @property
    def upload_chunk_size_bytes(self) -> int:
        unit = 256 * 1024  # Drive's required chunk-size alignment
        raw = int(self.upload_chunk_size_mb * 1024 * 1024)
        aligned = (raw // unit) * unit
        return aligned if aligned > 0 else unit

    @property
    def upload_min_free_disk_bytes(self) -> int:
        return int(self.upload_min_free_disk_gb * 1024 * 1024 * 1024)

    @property
    def thumbnail_image_source_max_bytes(self) -> int:
        return int(self.thumbnail_image_source_max_mb * 1024 * 1024)

    @property
    def thumbnail_video_source_max_bytes(self) -> int:
        return int(self.thumbnail_video_source_max_mb * 1024 * 1024)

    @property
    def effective_max_upload_bytes(self) -> int:
        # The smaller of the two configured ceilings - lets an operator
        # tighten UPLOAD_MAX_FILE_SIZE_MB without having to also touch the
        # older MAX_UPLOAD_SIZE_BYTES setting, and vice versa.
        return min(self.max_upload_size_bytes, self.upload_max_file_size_mb * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()