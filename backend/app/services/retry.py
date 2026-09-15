import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger("gallery.storage")

T = TypeVar("T")

# Errors worth retrying: rate limits, transient 5xx, network timeouts.
# NOT retried: auth failures, not-found, permission errors - retrying those
# just wastes time and delays a real error surfacing to the caller.
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_attempts: int = 5,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 20.0,
    is_retryable: Callable[[Exception], bool] | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> T:
    """
    Calls fn() with exponential backoff + jitter. Re-raises the last
    exception once max_attempts is exhausted - callers must not retry
    indefinitely (spec Section 32).

    on_retry, if given, is invoked as (attempt, exception, delay_seconds)
    right before each sleep - purely an observability hook (e.g. for the
    caller to emit its own structured `upload_retry` log event alongside
    this module's own logging); it never affects retry/backoff behavior.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below if not retryable/exhausted
            retryable = is_retryable(exc) if is_retryable else True
            if not retryable or attempt >= max_attempts:
                logger.warning(
                    "Storage operation failed permanently after %d attempt(s): %s", attempt, exc
                )
                raise
            delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
            delay = delay * (0.5 + random.random())  # jitter, avoid thundering herd
            logger.info(
                "Storage operation failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt,
                max_attempts,
                delay,
                exc,
            )
            if on_retry:
                try:
                    on_retry(attempt, exc, delay)
                except Exception:  # noqa: BLE001 - an observability hook must never break a retry
                    logger.debug("on_retry hook raised; ignoring", exc_info=True)
            time.sleep(delay)
