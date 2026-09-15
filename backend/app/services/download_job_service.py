"""
Background ZIP-generation jobs (Parts 7-9 of the spec).

Design notes worth reading before touching this file:

- No Celery/Redis - a job's actual work (process_download_job) runs as a
  plain synchronous function via FastAPI's BackgroundTasks, which FastAPI
  executes in its thread pool (same mechanism as every other blocking
  route/service in this codebase). That's enough for a single-VPS deployment
  at the scale this app targets; Section 46's "don't overengineer the MVP"
  applies here as much as anywhere else.
- The set of media ids included in a job is SNAPSHOTTED at creation time
  (stored in media_ids_json) rather than re-resolved when processing runs.
  Without this, "download the whole album" jobs could silently grow if
  someone uploads more files between job creation and processing, and the
  total_files/total_bytes shown to the user while queued would drift from
  what actually ends up in the ZIP.
- A ZIP is written incrementally to a real file on disk
  (`zipfile.ZipFile(path, "w")` + `zf.open(info, "w")` per entry, streaming
  each entry's bytes straight from StorageService.download()'s chunk
  iterator) - never fully buffered in memory, regardless of album size.
- If any single file fails to download mid-job, the WHOLE job is marked
  failed and the partial ZIP is deleted, rather than silently shipping an
  incomplete archive the person would only discover was missing files
  after downloading a multi-GB ZIP.
"""

import datetime
import json
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy.orm import Session as DbSession

from app.config.settings import get_settings
from app.database import connection as db_connection
from app.models.album import Album
from app.models.download_job import DownloadJob
from app.models.media import Media
from app.schemas.errors import ApiError, bad_request, forbidden, not_found
from app.services.storage_provider import get_storage_service
from app.services.studio_settings_service import get_studio_settings
from app.services.storage_service import StorageError, StorageService

logger = logging.getLogger("gallery.download_jobs")


class _JobCancelled(Exception):
    """
    Internal signal only - never leaves this module. Raised at one of
    process_download_job's cooperative-cancellation checkpoints once it
    notices (via a fresh DB read) that cancel_download_job() flipped this
    job's status out from under it. Caught separately from a real failure
    so a user-initiated cancel is cleaned up quietly instead of being
    logged/reported as an error.
    """


def _resolve_media_for_job(db: DbSession, album: Album, media_ids: list[int] | None) -> list[Media]:
    query = db.query(Media).filter(Media.album_id == album.id)
    if media_ids:
        # Defensive filter, not a hard error: any id that doesn't actually
        # belong to this album is silently dropped rather than included -
        # this is what "no unauthorized media included" means in practice
        # for a ZIP job (Part 14's test list).
        query = query.filter(Media.id.in_(media_ids))
    return query.order_by(Media.created_at.asc()).all()


def create_download_job(
    db: DbSession,
    album: Album,
    media_ids: list[int] | None,
    requested_by_type: str,
    requested_by_id: int,
) -> DownloadJob:
    settings = get_settings()

    media_rows = _resolve_media_for_job(db, album, media_ids)
    if not media_rows:
        raise bad_request("There is nothing to download for this selection.", code="DOWNLOAD_JOB_EMPTY")
    if len(media_rows) > settings.zip_job_max_files:
        raise bad_request(
            f"That's too many files for one ZIP (max {settings.zip_job_max_files}). "
            "Select fewer files or split into multiple downloads.",
            code="DOWNLOAD_JOB_TOO_LARGE",
        )

    resolved_ids = [m.id for m in media_rows]
    total_bytes = sum(m.file_size for m in media_rows)

    job = DownloadJob(
        client_id=album.client_id,
        album_id=album.id,
        status="queued",
        media_ids_json=json.dumps(resolved_ids),
        total_files=len(resolved_ids),
        completed_files=0,
        total_bytes=total_bytes,
        completed_bytes=0,
        requested_by_type=requested_by_type,
        requested_by_id=requested_by_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_download_job_for_client_or_403(db: DbSession, job_id: int, client_id: int) -> DownloadJob:
    job = db.query(DownloadJob).filter(DownloadJob.id == job_id).first()
    if job is None or job.client_id != client_id:
        raise forbidden("You do not have access to this download.", code="DOWNLOAD_JOB_FORBIDDEN")
    return job


def get_download_job_or_404(db: DbSession, job_id: int) -> DownloadJob:
    job = db.query(DownloadJob).filter(DownloadJob.id == job_id).first()
    if job is None:
        raise not_found("Download job not found.", code="DOWNLOAD_JOB_NOT_FOUND")
    return job


def cancel_download_job(db: DbSession, job: DownloadJob) -> DownloadJob:
    """
    Requests cancellation of a queued/preparing/processing job. This
    function itself doesn't stop anything - it only flips the DB row.
    process_download_job (running in a background thread, possibly on a
    completely different request/session) cooperatively checks for this at
    a few safe checkpoints and reacts by stopping and cleaning up its own
    temp files/partial ZIP once it notices. A job already in a terminal
    state (completed/failed/expired/cancelled) can't be cancelled
    retroactively - there's nothing left running to stop.
    """
    if job.status not in ("queued", "preparing", "processing"):
        raise bad_request(
            f"This download is already {job.status} and can't be cancelled.",
            code="DOWNLOAD_JOB_NOT_CANCELLABLE",
        )
    job.status = "cancelled"
    db.commit()
    db.refresh(job)
    return job


def _unique_zip_entry_name(used_names: set[str], file_name: str) -> str:
    if file_name not in used_names:
        used_names.add(file_name)
        return file_name
    stem, ext = os.path.splitext(file_name)
    counter = 2
    while f"{stem} ({counter}){ext}" in used_names:
        counter += 1
    unique = f"{stem} ({counter}){ext}"
    used_names.add(unique)
    return unique


def _mark_failed(db: DbSession, job: DownloadJob, message: str, zip_path: str | None) -> None:
    job.status = "failed"
    job.error_message = message[:500]
    db.commit()
    if zip_path and os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except OSError as exc:
            logger.error("Failed to remove partial ZIP file %s after job failure: %s", zip_path, exc)


def _prefetch_reservation(
    storage: StorageService, media_id: int, drive_file_id: str, temp_dir: str
) -> str:
    """
    Downloads one Media's bytes from storage into a temporary file,
    returning that file's path. Used as a worker unit for the parallel
    ZIP prefetch below: `storage.download()` streams chunks, we write them
    to disk so the caller can zip multiple files at its own pace without
    holding several multi-GB downloads in memory at once.

    The temp file lives in ZIP_TEMP_DIR and its path is collected by the
    caller, so a failure anywhere in the job removes every scratch file.

    Only plain scalar args (id + drive file id) are accepted - deliberately
    NOT a live Media instance. The Media objects loaded above are bound to
    the caller's Session, and every db.commit() in this worker expires them,
    so reading attributes off them from a pool thread would lazy-load that
    same Session concurrently with the main thread's db.refresh(job) ->
    "This session is provisioning a new connection" (SQLAlchemy isce).
    Snapshotting the two scalars on the main thread keeps the Session
    strictly single-threaded.
    """
    fd = tempfile.NamedTemporaryFile(
        dir=temp_dir, prefix=f"prefetch-{media_id}-", suffix=".part", delete=False
    )
    path = fd.name
    try:
        with fd:
            for chunk in storage.download(drive_file_id):
                fd.write(chunk)
        return path
    except BaseException:
        # Never leave a half-written prefetch file behind on failure.
        try:
            os.remove(path)
        except OSError:
            pass
        raise


def process_download_job(job_id: int, storage: StorageService | None = None) -> None:
    """
    The actual background worker. Runs detached from any request - opens
    its own DB session rather than reusing anything request-scoped (which
    would already be closed/torn down by the time a BackgroundTasks
    callback runs).

    `storage` is accepted as a parameter (rather than always calling
    get_storage_service() internally) specifically so tests can pass a
    FakeStorageService through - FastAPI's dependency_overrides only
    intercepts Depends()-resolved values in routes, not a plain function
    call made from inside a background task, so without this parameter
    the fake storage used everywhere else in the test suite would be
    silently bypassed here and it would try to build a real
    GoogleDriveStorage instead. Route handlers pass their own
    already-resolved (and override-respecting) storage dependency through
    when scheduling this task; production code with no override ends up
    calling get_storage_service() exactly as before.

    Similarly, this creates its DB session via `db_connection.SessionLocal()`
    - a module-attribute lookup at call time, NOT `from ... import
    SessionLocal` at the top of this file - specifically so the test suite
    can monkeypatch `app.database.connection.SessionLocal` to point at its
    isolated per-test SQLite engine and have that actually take effect here.
    A `from module import name` binding at import time would capture the
    original object forever and silently ignore any later monkeypatch,
    which would make every download-job test hit a different, empty
    database than the one the test itself set up.
    """
    settings = get_settings()
    db = db_connection.SessionLocal()
    storage = storage or get_storage_service()
    zip_path: str | None = None

    try:
        job = db.query(DownloadJob).filter(DownloadJob.id == job_id).first()
        if job is None:
            logger.error("process_download_job called with unknown job id %s", job_id)
            return
        if job.status == "cancelled":
            # Cancelled before this background task even got scheduled
            # (e.g. the user clicked Cancel in the instant between the
            # create-job response and FastAPI actually running the
            # BackgroundTasks callback). Nothing has started yet, so
            # there's nothing to clean up.
            logger.info("Download job %s was cancelled before processing started.", job_id)
            return

        job.status = "preparing"
        db.commit()

        media_ids: list[int] = json.loads(job.media_ids_json) if job.media_ids_json else []
        media_rows = db.query(Media).filter(Media.id.in_(media_ids)).all() if media_ids else []
        # Preserve the original snapshot order rather than whatever order
        # the IN(...) query happens to return.
        media_by_id = {m.id: m for m in media_rows}
        ordered_media = [media_by_id[mid] for mid in media_ids if mid in media_by_id]

        os.makedirs(settings.zip_temp_dir, exist_ok=True)
        zip_path = os.path.join(settings.zip_temp_dir, f"job-{job.id}-{uuid.uuid4().hex}.zip")

        job.status = "processing"
        db.commit()

        used_names: set[str] = set()
        prefetch_temp_dir = settings.zip_temp_dir
        os.makedirs(prefetch_temp_dir, exist_ok=True)
        parallel_downloads = max(1, settings.zip_job_parallel_downloads)

        # Phase A - parallel prefetch: download up to N files from storage
        # simultaneously into temp files, stripping the network latency off
        # the critical path. Order is preserved for the ZIP itself: entries
        # are written below in album order, but only after their bytes are
        # already sitting on local disk, so the slow per-file Drive round
        # trips overlap each other instead of chaining.
        prefetched_paths: dict[int, str] = {}
        try:
            with ThreadPoolExecutor(max_workers=parallel_downloads) as pool:

                def _submit(media: Media):
                    # Read the session-bound attributes here on the main
                    # thread BEFORE the worker touches them - the worker
                    # only gets plain scalars (see _prefetch_reservation).
                    return pool.submit(
                        _prefetch_reservation,
                        storage,
                        media.id,
                        media.google_drive_file_id,
                        prefetch_temp_dir,
                    )

                futures_to_media = {_submit(media): media for media in ordered_media}
                cancelled_mid_prefetch = False
                for future in as_completed(futures_to_media):
                    media = futures_to_media[future]
                    prefetched_paths[media.id] = future.result()

                    # Cooperative-cancellation checkpoint. db.refresh() forces
                    # an actual SELECT rather than reading this session's
                    # possibly-stale cached copy of `job` - the cancel
                    # request was committed by a totally different
                    # request/session, so without an explicit refresh this
                    # session might not see it until its own next commit
                    # happens to expire the object. Checked once per
                    # completed prefetch rather than in a tight loop, so
                    # this stays cheap even for a large album.
                    db.refresh(job)
                    if job.status == "cancelled" and not cancelled_mid_prefetch:
                        cancelled_mid_prefetch = True
                        # Best-effort only: ThreadPoolExecutor can't interrupt
                        # a prefetch that's already running, but .cancel()
                        # does drop any that haven't started yet, so nothing
                        # NEW begins once a cancellation has been seen.
                        for pending_future in futures_to_media:
                            pending_future.cancel()

                if cancelled_mid_prefetch:
                    raise _JobCancelled()

            with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_STORED) as zf:
                for media in ordered_media:
                    prefetch_path = prefetched_paths[media.id]
                    zinfo = zipfile.ZipInfo(
                        _unique_zip_entry_name(used_names, media.file_name),
                        date_time=media.created_at.timetuple()[:6],
                    )
                    with zf.open(zinfo, mode="w") as dest:
                        with open(prefetch_path, "rb") as src:
                            shutil.copyfileobj(src, dest)

                    job.completed_files += 1
                    job.completed_bytes += media.file_size
                    db.commit()

                    # db.commit() expires this session's cached copy of
                    # `job` by default, so this attribute access is itself
                    # a fresh read - catches a cancel request made while
                    # this entry was being written.
                    if job.status == "cancelled":
                        raise _JobCancelled()
        except StorageError as exc:
            raise RuntimeError(f"Failed to retrieve a file from storage: {exc}") from exc
        finally:
            # Whatever happened, the prefetched temp files are scratch data -
            # once the ZIP exists their content is inside it.
            for path in prefetched_paths.values():
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError as exc:
                        logger.error("Failed to remove prefetch temp file %s: %s", path, exc)

        job.status = "completed"
        job.zip_path = zip_path
        job.completed_at = datetime.datetime.utcnow()
        # The admin-configurable TTL (Settings > Security & download
        # policy) takes over from the env-var default here.
        # get_studio_settings() lazily creates the row, seeded from
        # settings.zip_job_ttl_hours, so this is a no-op change in
        # behavior until an admin actually edits the policy.
        ttl_hours = get_studio_settings(db).download_link_ttl_hours
        job.expires_at = job.completed_at + datetime.timedelta(hours=ttl_hours)
        db.commit()

    except _JobCancelled:
        logger.info("Download job %s was cancelled; cleaning up partial ZIP.", job_id)
        if zip_path and os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except OSError as exc:
                logger.error("Failed to remove partial ZIP file %s after cancellation: %s", zip_path, exc)
        # Status is already "cancelled" in the DB - cancel_download_job()
        # set it, and this worker only ever cooperatively READS that flag,
        # never overwrites it. In particular, don't route this through
        # _mark_failed(): that would misreport a user-initiated stop as an
        # error.
    except Exception as exc:  # noqa: BLE001 - any failure here must land the job in "failed", not crash silently
        logger.exception("Download job %s failed", job_id)
        try:
            job = db.query(DownloadJob).filter(DownloadJob.id == job_id).first()
            if job is not None:
                _mark_failed(db, job, str(exc), zip_path)
        except Exception:  # noqa: BLE001 - last-resort logging, never let cleanup itself crash the worker
            logger.critical("Failed to record failure state for download job %s", job_id)
    finally:
        db.close()


def get_ready_zip_path_or_error(job: DownloadJob) -> str:
    if job.status in ("queued", "preparing", "processing"):
        raise ApiError(409, "DOWNLOAD_NOT_READY", "This download is still being prepared.")
    if job.status == "cancelled":
        raise ApiError(410, "DOWNLOAD_CANCELLED", "This download was cancelled.")
    if job.status == "failed":
        raise ApiError(422, "DOWNLOAD_FAILED", job.error_message or "Download preparation failed.")
    if job.status == "expired" or not job.zip_path or not os.path.exists(job.zip_path):
        raise ApiError(410, "DOWNLOAD_EXPIRED", "This download has expired. Please start a new one.")
    return job.zip_path


def cleanup_expired_download_jobs(db: DbSession) -> int:
    """
    Deletes the on-disk ZIP for any completed job past its expiry and
    flips its status to "expired" (the DB row itself is kept for history/
    audit rather than deleted outright). Intended to be run periodically
    via cron calling `python -m app.cleanup_download_jobs` (see that
    module) rather than a persistent in-process scheduler - consistent
    with how MySQL backups are handled elsewhere in this project (Section
    43): cron on the VPS, not app-internal scheduling infrastructure.
    """
    now = datetime.datetime.utcnow()
    expired_jobs = (
        db.query(DownloadJob)
        .filter(DownloadJob.status == "completed")
        .filter(DownloadJob.expires_at.isnot(None))
        .filter(DownloadJob.expires_at <= now)
        .all()
    )

    cleaned = 0
    for job in expired_jobs:
        if job.zip_path and os.path.exists(job.zip_path):
            try:
                os.remove(job.zip_path)
            except OSError as exc:
                logger.error("Failed to remove expired ZIP for job %s: %s", job.id, exc)
                continue  # leave it as "completed" so cleanup retries next run rather than losing track of it
        job.status = "expired"
        job.zip_path = None
        cleaned += 1

    db.commit()
    return cleaned
