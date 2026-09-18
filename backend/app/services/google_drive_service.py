"""
The only module in the codebase allowed to import googleapiclient/google.auth.
Everything else talks to StorageService's abstract interface.

Credentials come from Settings (env vars) and never touch the frontend -
this class is only ever instantiated server-side.
"""

import http.client
import io
import json
import logging
import time
from typing import BinaryIO, Iterator

import httplib2
from google_auth_httplib2 import AuthorizedHttp

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from app.config.settings import Settings
from app.services.retry import RETRYABLE_HTTP_STATUSES, retry_with_backoff
from app.services.storage_service import (
    ProgressCallback,
    StorageError,
    StorageNotFoundError,
    StorageQuotaExceededError,
    StorageService,
    StorageTimeoutError,
    StoredFile,
)
from app.services.circuit_breaker import CircuitOpenError, get_drive_circuit_breaker
from app.services.timeout_utils import OperationTimeoutError, run_with_timeout
from app.services.upload_concurrency import get_upload_limiter
from app.services.upload_logging import log_event

logger = logging.getLogger("gallery.storage.google_drive")

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

# Same upload endpoint upload()'s MediaIoBaseUpload talks to under the
# hood - called directly here (raw HTTP, not through the discovery client)
# because we only want Drive to hand back a resumable SESSION URL, not to
# exchange any file bytes with US at all. supportsAllDrives=true so this
# keeps working if the target folder is ever a Shared Drive rather than a
# My Drive folder.
DRIVE_RESUMABLE_UPLOAD_ENDPOINT = (
    "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true"
)

# Fallback download chunk size when nothing more specific is configured.
DOWNLOAD_CHUNK_SIZE_BYTES = 8 * 1024 * 1024


def _is_httplib2_cleanup_bug(exc: Exception) -> bool:
    """True for the known httplib2/CPython teardown crash.

    After a TLS failure mid-transfer, ``http.client.HTTPResponse`` raises
    ``IncompleteRead``.  Its internal ``_close_conn()`` sets ``self.fp =
    None`` and then calls ``fp.close()`` — on the second invocation (or
    during a double-close path) ``fp`` is already ``None``, producing
    ``AttributeError: 'NoneType' object has no attribute 'close'``.
    The error is always caused by a transient transport failure; it is
    safe to retry because both resumable uploads and chunked downloads
    continue from the last confirmed byte/offset.
    """
    return (
        isinstance(exc, AttributeError)
        and len(exc.args) >= 1
        and isinstance(exc.args[0], str)
        and "has no attribute 'close'" in exc.args[0]
    )


def _is_retryable_google_error(exc: Exception) -> bool:
    if isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", None)
        return status in RETRYABLE_HTTP_STATUSES
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, httplib2.HttpLib2Error):
        # Transport-level failure raised by httplib2 ITSELF (e.g.
        # RedirectMissingLocation, RedirectLimit, ServerNotFoundError) -
        # not a real HTTP response from Drive. Almost always caused by
        # something between this server and Google (a proxy, antivirus
        # SSL inspection, a flaky hop) rather than Drive itself. Safe to
        # retry - resumable upload continues from the last confirmed byte.
        return True
    if isinstance(exc, OSError):
        # Covers ssl.SSLError (WRONG_VERSION_NUMBER / UNEXPECTED_RECORD etc.)
        # which is frequently a transient connection/firewall hiccup - the
        # same endpoint routinely succeeds moments later. Safe to retry
        # because the resumable-upload protocol continues from the last
        # byte-range Drive confirmed, so a partial chunk is never re-sent
        # twice. (retry_with_backoff re-raises if attempts are exhausted.)
        return True
    if _is_httplib2_cleanup_bug(exc):
        # httplib2/CPython double-close bug triggered by an IncompleteRead
        # after a TLS-level failure (antivirus/proxy SSL inspection on
        # Windows). Not an HttpLib2Error, so the catch above doesn't
        # cover it. Safe to retry for the same resumability reason.
        return True
    if isinstance(exc, http.client.HTTPException):
        # http.client.HTTPException is what the stdlib raises when a real
        # HTTP response is malformed or TRUNCATED - most importantly
        # IncompleteRead ("peer closed the connection before Content-Length
        # bytes arrived") and BadStatusLine. These are pure transport
        # failures, not Drive errors: exactly what antivirus/proxy SSL
        # inspection or a flaky hop produces when it resets a connection
        # mid-response. They are NOT an OSError/ConnectionError/HttpLib2Error
        # (verified: IncompleteRead subclasses neither), so without this
        # branch they were never classified as retryable and - worse - were
        # never translated to StorageError inside _retry() below. That let a
        # raw IncompleteRead escape out of download()'s generator after the
        # StreamingResponse headers were already committed, so uvicorn
        # aborted the connection and the reverse proxy/client saw a bare
        # connection reset (ECONNRESET) instead of a truncated-but-finished
        # response - the classic "thumbnail failed to load" for a gallery
        # grid firing dozens of concurrent thumbnail requests. Safe to retry:
        # fixture-style GETs are idempotent and a resumable download's
        # next_chunk() continues from the last byte Drive confirmed.
        return True
    return False


def _translate_http_error(exc: HttpError) -> StorageError:
    status = getattr(exc.resp, "status", None)
    if status == 404:
        return StorageNotFoundError(str(exc))
    if status in (403, 429):
        # Drive returns 403 for both permission errors and quota/rate-limit
        # errors; we treat both conservatively as quota-related here since
        # a permission error server-side is itself an operational problem,
        # not something to surface raw details about to the client.
        return StorageQuotaExceededError(str(exc))
    return StorageError(str(exc))


class GoogleDriveStorage(StorageService):
    def __init__(self, settings: Settings):
        if not settings.google_drive_refresh_token:
            raise StorageError(
                "Google Drive is not configured (missing GOOGLE_DRIVE_REFRESH_TOKEN)."
            )

        credentials = Credentials(
            token=None,
            refresh_token=settings.google_drive_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_drive_client_id,
            client_secret=settings.google_drive_client_secret,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        # googleapiclient refreshes expired tokens automatically per-request
        # using these credentials, so we don't need to manage token refresh
        # ourselves beyond handling RefreshError if the refresh_token itself
        # has been revoked.
        #
        # Explicit socket-level timeout on the underlying transport -
        # httplib2's own default is NO timeout at all. Without this, a
        # connection silently black-holed by a proxy/antivirus doing HTTPS
        # inspection (as opposed to one that fails fast with a clean SSL
        # error - see _is_retryable_google_error) can hang the calling
        # request thread FOREVER instead of raising and letting it return
        # to the pool. That - not a slow-but-eventually-failing call - is
        # what actually takes the whole server down until it's manually
        # restarted: the circuit breaker (circuit_breaker.py) only helps
        # once a call actually raises an exception; it can't unstick one
        # that never returns at all. build(http=...) is used instead of
        # build(credentials=...) specifically so this timeout applies -
        # passing credentials= lets googleapiclient construct its own
        # httplib2.Http() internally, with no way to configure it.
        metadata_http = httplib2.Http(timeout=settings.upload_chunk_timeout)
        authorized_metadata_http = AuthorizedHttp(credentials, http=metadata_http)
        self._service = build("drive", "v3", http=authorized_metadata_http, cache_discovery=False)
        self._credentials = credentials
        self._root_folder_id = settings.google_drive_root_folder_id or None

        # Upload-hardening configuration (Sections 2/3/6/10). Read once at
        # construction time, same lifetime as the underlying API client.
        self._chunk_size_bytes = settings.upload_chunk_size_bytes
        self._max_retries = settings.upload_max_retries
        self._initial_backoff = settings.upload_initial_backoff_seconds
        self._max_backoff = settings.upload_max_backoff_seconds
        self._chunk_timeout = settings.upload_chunk_timeout
        self._session_timeout = settings.upload_session_timeout
        self._limiter = get_upload_limiter(settings.upload_max_concurrent)




    def _retry(self, fn, *, on_retry=None):
        # Fail fast, before even attempting the network call, if Drive has
        # already failed repeatedly in a row (see circuit_breaker.py) -
        # this is what keeps a systemic outage (antivirus/proxy SSL
        # inspection breaking every HTTPS call, or a real Google-side
        # outage) from turning into a server-wide hang: without it, a
        # burst of concurrent requests (e.g. a gallery page loading dozens
        # of thumbnails) would each independently pay the full retry+
        # backoff cost below - several seconds per request - and exhaust
        # the server's request-handling thread pool in the process.
        breaker = get_drive_circuit_breaker()
        try:
            breaker.before_call()
        except CircuitOpenError as exc:
            raise StorageError(str(exc)) from exc

        try:
            result = retry_with_backoff(
                fn,
                max_attempts=self._max_retries,
                base_delay_seconds=self._initial_backoff,
                max_delay_seconds=self._max_backoff,
                is_retryable=_is_retryable_google_error,
                on_retry=on_retry,
            )
        except httplib2.HttpLib2Error as exc:
            # Once every retry is exhausted, translate here (one place)
            # so every method using _retry() gets a clean StorageError
            # instead of a raw unhandled exception escaping.
            breaker.on_failure()
            raise StorageError(f"Network error communicating with Google Drive: {exc}") from exc
        except AttributeError as exc:
            # The httplib2/CPython double-close bug (see
            # _is_httplib2_cleanup_bug) is not an HttpLib2Error, so the
            # catch above doesn't cover it. Translate the same way so
            # callers get a clean StorageError rather than an unhandled
            # AttributeError crashing the streaming generator.
            if _is_httplib2_cleanup_bug(exc):
                breaker.on_failure()
                raise StorageError(
                    f"Network error communicating with Google Drive: {exc}"
                ) from exc
            raise
        except OSError as exc:
            # _is_retryable_google_error() marks OSError (ssl.SSLError,
            # ConnectionResetError, etc. - e.g. antivirus/proxy SSL
            # inspection on Windows, see that function's docstring) as
            # worth retrying, but retry_with_backoff() re-raises the
            # ORIGINAL exception unchanged once attempts are exhausted -
            # so without this, a persistent network hiccup surfaces as a
            # raw OSError here instead of a StorageError. That's fatal for
            # any caller mid-way through a StreamingResponse (download(),
            # used by both the client "view"/"thumbnail" endpoints and the
            # ZIP job prefetch): an unhandled exception there crashes the
            # response after headers are already sent, which is what shows
            # up client-side as a bare connection reset instead of a
            # readable error. Translating it here - the same way the two
            # blocks above already do for other transport-level failures -
            # closes that gap for every _retry() caller at once.
            breaker.on_failure()
            raise StorageError(f"Network error communicating with Google Drive: {exc}") from exc
        except http.client.HTTPException as exc:
            # IncompleteRead / BadStatusLine / LineTooLong etc. - see
            # _is_retryable_google_error(). Not an OSError (so the block
            # above doesn't cover it), and unlike the OSError case this can
            # surface BOTH before a response commits (get_file metadata on
            # the thumbnail/view routes -> would 500 instead of a clean
            # {success:false} 502) and mid-stream inside download()'s
            # generator (-> uvicorn aborts the committed response, which
            # the proxy/browser reads as ECONNRESET). Same
            # transport-failure handling: count it against the breaker and
            # translate to StorageError so every caller's existing
            # `except StorageError` path handles it.
            breaker.on_failure()
            raise StorageError(f"Network error communicating with Google Drive: {exc}") from exc
        else:
            # A genuine Drive-side response (even an error one, like a 404
            # or a permission failure raised as HttpError above/elsewhere)
            # proves connectivity is fine - only pure transport/connectivity
            # failures (the three except blocks above) count against the
            # breaker, not application-level Drive errors.
            breaker.on_success()
            return result

    # ---- folders ----------------------------------------------------

    def create_folder(self, name: str, parent_folder_id: str | None = None) -> str:
        parent = parent_folder_id or self._root_folder_id
        metadata = {"name": name, "mimeType": FOLDER_MIME_TYPE}
        if parent:
            metadata["parents"] = [parent]

        def _do():
            return self._service.files().create(body=metadata, fields="id").execute()

        try:
            result = self._retry(_do)
        except HttpError as exc:
            raise _translate_http_error(exc) from exc
        except RefreshError as exc:
            raise StorageError(f"Google Drive authentication failed: {exc}") from exc
        return result["id"]

    def delete_folder(self, folder_id: str) -> None:
        self.delete(folder_id)  # trashing a folder trashes its contents too

    def rename_folder(self, folder_id: str, new_name: str) -> None:
        def _do():
            return self._service.files().update(
                fileId=folder_id, body={"name": new_name}, fields="id"
            ).execute()

        try:
            self._retry(_do)
        except HttpError as exc:
            raise _translate_http_error(exc) from exc
        except RefreshError as exc:
            raise StorageError(f"Google Drive authentication failed: {exc}") from exc

    # ---- files --------------------------------------------------------

    def upload(
        self,
        file_obj: BinaryIO,
        filename: str,
        mime_type: str,
        parent_folder_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        upload_id: str | None = None,
    ) -> StoredFile:
        # Resumable=True + an explicit chunksize (Section 2) means this
        # streams `file_obj` (the request's already-spooled
        # SpooledTemporaryFile) in bounded pieces - MediaIoBaseUpload never
        # reads the whole file into memory, and next_chunk() correctly
        # slices/handles the final partial chunk on its own.
        media = MediaIoBaseUpload(
            file_obj, mimetype=mime_type, chunksize=self._chunk_size_bytes, resumable=True
        )
        total_bytes = media.size() or 0
        metadata = {"name": filename, "parents": [parent_folder_id]}
        if upload_id:
            # appProperties tags this file as application-managed so an
            # orphan-reconciliation pass can identify it via Drive's own
            # metadata, not just filename guessing (Section 9).
            metadata["appProperties"] = {"gallery_managed": "true", "gallery_upload_id": upload_id}

        request = self._service.files().create(
            body=metadata, media_body=media, fields="id, name, size, mimeType"
        )

        # One dedicated, authorized HTTP client per upload. The shared
        # service client (`self._service`) is NOT safe for concurrent
        # resumable uploads - httplib2 maintains a single connection cache
        # keyed by host, so two uploads on two threads can borrow the same
        # socket at once, crossing responses/byte-streams between files and
        # producing Drive 400s like "final size N does not match expected
        # size M from an earlier request". Each upload talking to its own
        # client keeps the concurrent transfers fully isolated. The
        # explicit timeout closes the same "silent hang" gap described on
        # self._service's construction above - this call is additionally
        # wrapped in run_with_timeout() below, so this is belt-and-suspenders,
        # not the only guard.
        raw_http = httplib2.Http(timeout=self._chunk_timeout)
        # Google's resumable-upload protocol uses HTTP 308 to mean "chunk
        # received, send the next one" - NOT a real redirect. httplib2
        # treats 308 as a redirect status by default and, finding no
        # Location header (there never is one for this use), raises
        # RedirectMissingLocation on every multi-chunk upload. This is a
        # known googleapiclient/httplib2 interaction - their own
        # build_http() helper applies this exact same exclusion, but we
        # can't use build_http() here since we need our own httplib2.Http()
        # instance per upload for the connection-isolation reason above.
        # Single-chunk uploads (small files, finish in one 200/201
        # response with no intermediate 308) never hit this, which is why
        # it only ever showed up on larger files.
        raw_http.redirect_codes = raw_http.redirect_codes - {308}
        upload_http = AuthorizedHttp(self._credentials, http=raw_http)

        
        def _do_chunk():
            return request.next_chunk(http=upload_http)

        def _on_retry(attempt, exc, delay):
            log_event(
                logger,
                "upload_retry",
                upload_id=upload_id,
                filename=filename,
                attempt=attempt,
                error_type=type(exc).__name__,
                delay_seconds=round(delay, 2),
            )

        log_event(logger, "upload_started", upload_id=upload_id, filename=filename, file_size=total_bytes)
        session_start = time.monotonic()

        # Section 3: never more than upload_max_concurrent transfers to the
        # provider at once. The slot is released in the limiter's own
        # `finally`, so it's freed on success, on a StorageError/
        # StorageTimeoutError raised below, or on any other exception
        # (e.g. cancellation) that unwinds this block.
        with self._limiter.slot():
            try:
                response = None
                while response is None:
                    elapsed = time.monotonic() - session_start
                    if elapsed > self._session_timeout:
                        log_event(
                            logger,
                            "upload_timeout",
                            upload_id=upload_id,
                            filename=filename,
                            elapsed_time=round(elapsed, 1),
                            scope="session",
                        )
                        raise StorageTimeoutError(
                            f"Upload session exceeded {self._session_timeout}s timeout"
                        )

                    # next_chunk() itself makes one HTTP call per
                    # invocation; wrap each call in both a per-chunk
                    # timeout and retry-with-backoff so a transient
                    # failure - or a chunk that never comes back at all -
                    # doesn't abort (or hang) the whole multi-GB transfer.
                    # On a genuinely dropped connection, Drive's resumable
                    # protocol means the next successful next_chunk() call
                    # continues from the last byte range Drive actually
                    # confirmed, rather than restarting the file.
                    try:
                        status, response = run_with_timeout(
                            lambda: self._retry(_do_chunk, on_retry=_on_retry),
                            timeout_seconds=self._chunk_timeout,
                        )
                    except OperationTimeoutError as exc:
                        log_event(
                            logger,
                            "upload_timeout",
                            upload_id=upload_id,
                            filename=filename,
                            elapsed_time=round(time.monotonic() - session_start, 1),
                            scope="chunk",
                        )
                        raise StorageTimeoutError(str(exc)) from exc

                    if progress_callback:
                        uploaded = status.resumable_progress if status is not None else total_bytes
                        # Never claim 100% before the loop actually exits
                        # with a final `response` (Section 8).
                        uploaded = min(uploaded, total_bytes) if response is None else total_bytes
                        progress_callback(uploaded, total_bytes)
            except HttpError as exc:
                raise _translate_http_error(exc) from exc
            except RefreshError as exc:
                raise StorageError(f"Google Drive authentication failed: {exc}") from exc
            except TimeoutError as exc:
                # A chunk timeout that survived every retry surfaces here as
                # the builtin TimeoutError, not StorageTimeoutError. Map it
                # so the upload path returns 504, not an unhandled 500.
                raise StorageTimeoutError(str(exc)) from exc
            except ConnectionError as exc:
                raise StorageError(f"Connection lost while uploading: {exc}") from exc
            except OSError as exc:
                # Covers ssl.SSLError (e.g. [SSL: WRONG_VERSION_NUMBER]), which
                # retry-with-backoff correctly refuses to retry but which
                # still must surface as a StorageError, not an unhandled 500.
                raise StorageError(f"Network error while uploading: {exc}") from exc
            finally:
                upload_http.close()

        log_event(
            logger,
            "upload_completed",
            upload_id=upload_id,
            filename=filename,
            file_size=response.get("size", total_bytes),
            elapsed_time=round(time.monotonic() - session_start, 1),
        )

        return StoredFile(
            provider_file_id=response["id"],
            name=response.get("name", filename),
            size=int(response.get("size", 0)),
            mime_type=response.get("mimeType", mime_type),
        )

    def create_resumable_session(
        self,
        filename: str,
        mime_type: str,
        file_size: int,
        parent_folder_id: str,
        *,
        upload_id: str | None = None,
        origin: str | None = None,
    ) -> str:
        # A raw, one-shot POST to Drive's resumable-upload initiation
        # endpoint - deliberately NOT going through self._service.files()
        # .create(media_body=...), because that path always wants an
        # actual file-like object to read bytes from. Here we only want
        # the resumable SESSION URL back (the `Location` response header);
        # the browser sends every content byte directly to Drive from this
        # point on, this server never touches them (Section: direct
        # browser -> provider upload).
        metadata = {"name": filename, "parents": [parent_folder_id]}
        if upload_id:
            # Same tagging upload() applies, so a file created this way is
            # still identifiable as application-managed for orphan
            # reconciliation, even though this server never transferred
            # its bytes directly.
            metadata["appProperties"] = {"gallery_managed": "true", "gallery_upload_id": upload_id}
        body = json.dumps(metadata).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Content-Length": str(len(body)),
            # Tells Drive up front what's coming, so it can validate
            # against these once the browser actually PUTs the bytes,
            # without this server ever holding them itself.
            "X-Upload-Content-Type": mime_type,
            "X-Upload-Content-Length": str(file_size),
        }
        if origin:
            # THE fix for the browser's subsequent direct PUT being
            # blocked by CORS: Google bakes CORS support for a resumable
            # session into whichever Origin header was present on THIS
            # initiating request - a server-to-server call like this one
            # has no browser Origin of its own, so without forwarding the
            # real one, Google issues a session with no CORS allowance,
            # and the browser's later PUT gets rejected client-side before
            # it ever reaches Google. Already validated against our own
            # CORS allowlist by the caller (admin_media.py) - never call
            # this with an unvalidated, request-supplied value.
            headers["Origin"] = origin

        # One dedicated, authorized HTTP client for this call, same
        # per-call-isolation reasoning as upload()/download() above.
        raw_http = httplib2.Http(timeout=self._chunk_timeout,proxy_info=None, disable_ssl_certificate_validation=True)
        session_http = AuthorizedHttp(self._credentials, http=raw_http)

        def _do():
            resp, content = session_http.request(
                DRIVE_RESUMABLE_UPLOAD_ENDPOINT, method="POST", body=body, headers=headers
            )
            if int(resp.status) not in (200, 201):
                # httplib2's raw .request() doesn't raise on a non-2xx
                # status the way the discovery client's execute() does -
                # raise the same HttpError type ourselves so this
                # participates in the exact same retry/translate pipeline
                # (_is_retryable_google_error / _translate_http_error)
                # every other method here already uses.
                raise HttpError(resp, content, uri=DRIVE_RESUMABLE_UPLOAD_ENDPOINT)
            return resp

        try:
            resp = self._retry(_do)
        except HttpError as exc:
            raise _translate_http_error(exc) from exc
        except RefreshError as exc:
            raise StorageError(f"Google Drive authentication failed: {exc}") from exc
        finally:
            raw_http.close()

        location = resp.get("location")
        if not location:
            raise StorageError(
                "Google Drive accepted the resumable upload request but returned no session URL."
            )
        log_event(
            logger, "resumable_session_created", upload_id=upload_id, filename=filename, file_size=file_size
        )
        return location

    def download(
        self,
        provider_file_id: str,
        *,
        range_start: int | None = None,
        range_end: int | None = None,
    ) -> Iterator[bytes]:
        # One dedicated, authorized HTTP client per download call -
        # mirroring what upload() already does. httplib2 keeps a single
        # connection cache keyed by host per Http instance, so sharing
        # `self._service` across concurrent transfers (e.g. the ZIP job's
        # parallel prefetch) lets two threads borrow the same socket at
        # once and cross byte-streams. A per-call client keeps every
        # transfer fully isolated, with the side benefit of a fresh TLS
        # session each time - gentler on flaky/inspected connections (see
        # _is_httplib2_cleanup_bug). The explicit timeout closes the same
        # "silent hang" gap described on self._service's construction above.
        raw_http = httplib2.Http(timeout=self._chunk_timeout)
        download_http = AuthorizedHttp(self._credentials, http=raw_http)
        try:
            request = self._service.files().get_media(fileId=provider_file_id)
            # Route this request - and every next_chunk() beneath it, which
            # reads request.http off the HttpRequest - through the dedicated
            # client instead of the shared service one.
            request.http = download_http

            # Drive honors a standard HTTP Range header on the media-download
            # request itself - this is what lets a video seek/scrub without us
            # ever pulling the whole (possibly multi-GB) file server-side just
            # to serve a 10-second clip of it.
            if range_start is not None or range_end is not None:
                start = range_start if range_start is not None else 0
                end_part = str(range_end) if range_end is not None else ""
                request.headers["Range"] = f"bytes={start}-{end_part}"

            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request, chunksize=DOWNLOAD_CHUNK_SIZE_BYTES)

            done = False
            while not done:
                try:
                    # Deliberately NOT wrapped in run_with_timeout() the way
                    # upload()'s chunk loop is (see the "belt-and-suspenders"
                    # comment on upload()'s raw_http above) - that extra
                    # layer submits each chunk fetch to timeout_utils.py's
                    # own small, GLOBAL, app-wide ThreadPoolExecutor and then
                    # blocks *this* thread (itself borrowed from Starlette's
                    # shared sync-route thread pool, since every route in
                    # this app is a plain `def`, not `async def`) waiting on
                    # it - two threads held to do one unit of work, for the
                    # full chunk_timeout, on every single chunk. Upload
                    # concurrency is capped hard (client-side to 4, and
                    # server-side by UploadConcurrencyLimiter), so that
                    # double layer stays cheap there. Download has no such
                    # cap: a single gallery grid can fire dozens of
                    # concurrent thumbnail/view requests, each running this
                    # same loop. Under that load the two nested pools
                    # saturate each other - new chunk fetches then time out
                    # waiting merely for a free *pool slot*, not because
                    # Drive is actually slow, which was truncating
                    # already-committed StreamingResponses far more often
                    # than genuine network stalls ever would (the classic
                    # "video stuck at 0:00", ECONNRESET at the dev proxy,
                    # and - because it was starving the SAME shared thread
                    # pool that every other plain `def` route also needs,
                    # including unrelated ones like verify-download-password
                    # - errors on endpoints that never touch Drive at all).
                    # The httplib2 socket-level timeout already set on
                    # raw_http above (settings.upload_chunk_timeout) is
                    # sufficient on its own here: it bounds the real network
                    # operation directly, with no pool/queueing involved, so
                    # a genuinely stalled chunk still can't hang forever -
                    # it raises (translated to StorageError by _retry()'s
                    # own OSError handling) within chunk_timeout regardless.
                    _, done = self._retry(downloader.next_chunk)
                except HttpError as exc:
                    raise _translate_http_error(exc) from exc
                except RefreshError as exc:
                    # Same failure mode create_folder/upload/move_file already
                    # guard against (expired/revoked GOOGLE_DRIVE_REFRESH_TOKEN)
                    # - without this, it propagates raw out of this generator
                    # while a StreamingResponse is already mid-flight (headers
                    # already sent), which the client/proxy sees as an abrupt
                    # connection reset instead of a clean error. Translating it
                    # here lets callers' `except StorageError` around
                    # `yield from storage.download(...)` actually catch it.
                    raise StorageError(f"Google Drive authentication failed: {exc}") from exc
                buffer.seek(0)
                chunk = buffer.read()
                if chunk:
                    yield chunk
                buffer.seek(0)
                buffer.truncate(0)
        finally:
            download_http.close()

    def delete(self, provider_file_id: str) -> None:
        # Move to trash rather than a permanent files().delete(). The common
        # deployment shape here is: a human photographer owns the Drive
        # folder tree and shares it with this app's service account as an
        # Editor/Content-manager (so they can browse their own files in
        # Drive too), NOT as the owner. Google's API only grants "delete"
        # capability (files.delete - permanent, bypasses trash) to the
        # file's owner or a Shared Drive organizer; an Editor/writer on a
        # regular Drive folder can trash a file but cannot permanently
        # delete one they don't own. Calling files.delete() in that setup
        # fails with 403 insufficientFilePermissions on every single
        # deletion (client/album/media removal, orphan cleanup, and the
        # rollback-on-failure cleanup paths) - trashing achieves the same
        # outcome for this app (the file/folder disappears, its Drive
        # storage stops counting toward the owner's active files) and only
        # requires write access, which the service account always has by
        # the time it got here (it had to have write access to create the
        # file in the first place). The human owner can empty their own
        # trash, or Drive auto-purges it after 30 days.
        def _do():
            self._service.files().update(
                fileId=provider_file_id, body={"trashed": True}, fields="id"
            ).execute()

        try:
            self._retry(_do)
        except HttpError as exc:
            translated = _translate_http_error(exc)
            if isinstance(translated, StorageNotFoundError):
                return  # deleting something already gone is a no-op, not an error
            raise translated from exc
        except RefreshError as exc:
            raise StorageError(f"Google Drive authentication failed: {exc}") from exc

    # def get_file(self, provider_file_id: str) -> StoredFile:
    #     def _do():
    #         return self._service.files().get(
    #             fileId=provider_file_id, fields="id, name, size, mimeType"
    #         ).execute()

    #     try:
    #         result = self._retry(_do)
    #     except HttpError as exc:
    #         raise _translate_http_error(exc) from exc
    #     except RefreshError as exc:
    #         raise StorageError(f"Google Drive authentication failed: {exc}") from exc

    #     return StoredFile(
    #         provider_file_id=result["id"],
    #         name=result.get("name", ""),
    #         size=int(result.get("size", 0)),
    #         mime_type=result.get("mimeType", ""),
    #     )
    def get_file(self, provider_file_id: str) -> StoredFile:
        def _do():
            return self._service.files().get(
                fileId=provider_file_id,
                fields="id,name,size,mimeType",
                supportsAllDrives=True,
        ).execute()

        try:
            result = self._retry(_do)
        except HttpError as exc:
            raise _translate_http_error(exc) from exc
        except RefreshError as exc:
            raise StorageError(
                f"Google Drive authentication failed: {exc}"
            ) from exc

        if not isinstance(result, dict):
            logger.error(
                "Google Drive returned unexpected get_file response for file %s: %r",
                provider_file_id,
                result,
            )
            raise StorageError(
                "Google Drive returned an invalid file metadata response."
            )

        returned_file_id = result.get("id")

        if not returned_file_id:
            logger.error(
                "Google Drive get_file returned no file id. "
                "requested_file_id=%s response=%r",
                provider_file_id,
                result,
            )
            raise StorageError(
                "Google Drive returned file metadata without an id."
            )

        return StoredFile(
            provider_file_id=returned_file_id,
            name=result.get("name", ""),
            size=int(result.get("size", 0) or 0),
            mime_type=result.get("mimeType", ""),
        )

    def move_file(
        self,
        provider_file_id: str,
        new_parent_folder_id: str,
        old_parent_folder_id: str | None = None,
    ) -> None:
        # Drive files.update with addParents/removeParents is a metadata-only
        # operation - the file's content is never re-transferred, so this is
        # cheap even for a multi-GB video.
        def _do():
            kwargs = {"fileId": provider_file_id, "addParents": new_parent_folder_id, "fields": "id, parents"}
            if old_parent_folder_id:
                kwargs["removeParents"] = old_parent_folder_id
            return self._service.files().update(**kwargs).execute()

        try:
            self._retry(_do)
        except HttpError as exc:
            raise _translate_http_error(exc) from exc
        except RefreshError as exc:
            raise StorageError(f"Google Drive authentication failed: {exc}") from exc

    def get_metadata(self) -> dict:
        def _do():
            return self._service.about().get(fields="storageQuota").execute()

        try:
            result = self._retry(_do)
        except (HttpError, StorageError, RefreshError) as exc:
            logger.warning("Could not fetch Drive storage quota: %s", exc)
            return {"available": False}

        quota = result.get("storageQuota", {})
        if "usage" not in quota:
            return {"available": False}

        return {
            "available": True,
            "usage_bytes": int(quota.get("usage", 0)),
            "limit_bytes": int(quota["limit"]) if "limit" in quota else None,
        }