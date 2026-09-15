"""
Bounds how long a blocking call is allowed to take (Section 10). The
underlying Google API client library doesn't give us a clean per-call
deadline hook, so this runs the call on a small worker-thread pool and
gives up waiting after `timeout_seconds` - letting the request path fail
fast and cleanly (release its concurrency slot, its disk reservation,
mark the upload retryable) instead of hanging indefinitely on a stalled
socket.

Known limitation: cancelling a Future here does not forcibly kill the
underlying network call if it's already in flight - the abandoned thread
finishes (or errors out) on its own in the background. This is the
standard trade-off of thread-based timeouts in Python (there's no safe
way to hard-kill another thread), and it's still strictly better than the
request thread hanging forever: the caller gets control back promptly and
the upload is safely retryable because nothing was left half-recorded.
"""

import concurrent.futures

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=64, thread_name_prefix="upload-timeout")


class OperationTimeoutError(Exception):
    pass


def run_with_timeout(fn, timeout_seconds: float):
    future = _EXECUTOR.submit(fn)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()  # no-op if already running, but harmless
        raise OperationTimeoutError(f"Operation exceeded {timeout_seconds}s timeout") from exc
