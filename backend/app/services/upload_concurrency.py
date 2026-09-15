"""
Caps how many uploads may be actively transferring to the storage provider
at once (Section 3 of the upload-hardening spec). Deliberately a plain
in-process threading primitive, not a new queueing/task system: FastAPI
runs sync `def` route handlers in a thread pool, so a blocking
`Semaphore.acquire()` here parks the worker thread without blocking the
event loop, and Section 46's "don't overengineer the MVP" applies just as
much to this as it did to the existing ZIP job system.

Known limitation: this coordinates concurrency within a single process
only. If the app is ever run with multiple worker processes, each process
gets its own independent limit (so the real ceiling becomes
UPLOAD_MAX_CONCURRENT * worker_count). Cross-process coordination would
need a shared external lock (e.g. a DB-backed counter or Redis) - not
added here per the "minimum necessary changes" instruction, but worth
knowing before scaling out.
"""

import threading
from contextlib import contextmanager
from functools import lru_cache


class UploadQueueTimeoutError(Exception):
    """
    Raised when a caller asks for a slot with a timeout and none becomes
    free in time - distinct from just blocking forever, so the request
    layer can turn sustained overload into a clean 503 instead of a
    request that hangs until the client or proxy gives up on its own.
    """


class UploadConcurrencyLimiter:
    def __init__(self, max_concurrent: int):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._max_concurrent = max_concurrent
        self._sem = threading.BoundedSemaphore(max_concurrent)
        self._active = 0
        self._lock = threading.Lock()

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active

    @contextmanager
    def slot(self, timeout: float | None = None):
        """
        Blocks until a slot is free, then yields. The slot is ALWAYS
        released - on success, on any exception (including timeouts and
        cancellations), no matter what - because the release lives in a
        `finally`.

        timeout, if given, caps how long to wait for a slot: if none opens
        up in time, raises UploadQueueTimeoutError instead of blocking
        forever. Default (None) preserves the original block-forever
        behavior for existing callers.
        """
        acquired = self._sem.acquire(timeout=timeout) if timeout is not None else self._sem.acquire()
        if not acquired:
            raise UploadQueueTimeoutError(
                f"No upload slot became free within {timeout}s (max_concurrent={self._max_concurrent})."
            )
        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._sem.release()


@lru_cache(maxsize=8)
def get_upload_limiter(max_concurrent: int) -> UploadConcurrencyLimiter:
    # Cached per distinct max_concurrent value so the whole process shares
    # one limiter instance (and therefore one real semaphore) as long as
    # configuration doesn't change at runtime.
    return UploadConcurrencyLimiter(max_concurrent)
