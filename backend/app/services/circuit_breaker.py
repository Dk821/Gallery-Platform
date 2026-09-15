"""
Circuit breaker for Google Drive connectivity.

When Drive becomes unreachable for everyone at once - a local network,
antivirus, or proxy problem intercepting/breaking outbound HTTPS (the
classic symptom: repeated ssl.SSLError WRONG_VERSION_NUMBER in the logs),
or a real Google-side outage - every single storage call still pays the
FULL retry-with-backoff cost in google_drive_service.py's _retry() before
giving up: 5 attempts by default, several seconds of backoff between each.
Under a burst of concurrent requests (e.g. a gallery page loading dozens
of thumbnails at once, each a separate request), that ties up the
server's whole request-handling thread pool for the entire duration of
every one of those retries - which is what makes the server appear to
hang/crash for EVERY visitor, not just the ones whose request happened to
touch Drive.

This breaker sits in front of _retry(). Once enough calls have failed in
a row, it "opens" and makes every subsequent call fail immediately - no
network attempt, no backoff wait - for a cooldown window, so the rest of
the app (logins, any page that doesn't touch Drive) stays responsive
instead of every request queuing up behind a doomed retry loop. After the
cooldown, the next call is let through as a trial: success closes the
breaker again; failure reopens it.

Deliberately simple - a single process-wide breaker, no half-open
concurrency limiting, no per-endpoint breakers. This targets the specific
"systemic connectivity failure" scenario; routine one-off transient
errors are already handled fine by retry_with_backoff on its own.

Known limitation: in-process only, same caveat as upload_concurrency.py
and disk_service.py - multiple worker processes would each track failures
independently. Fine for the single-process deployment this project
targets.
"""

import logging
import threading
import time

logger = logging.getLogger("gallery.storage")


class CircuitOpenError(Exception):
    """Raised instead of even attempting a call while the breaker is open."""


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 20.0):
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def before_call(self) -> None:
        """
        Raises CircuitOpenError if the breaker is open and the cooldown
        hasn't elapsed yet - the caller should fail fast without even
        trying the network call. Does nothing (safe to proceed) once
        closed, or once the cooldown has elapsed and this call is being
        let through as a trial.
        """
        with self._lock:
            if self._opened_at is None:
                return
            elapsed = time.monotonic() - self._opened_at
            if elapsed < self._cooldown_seconds:
                raise CircuitOpenError(
                    f"Google Drive has failed {self._consecutive_failures} times in a row "
                    f"in the last few moments and is being given "
                    f"{self._cooldown_seconds - elapsed:.0f}s to recover before the next attempt."
                )
            # Cooldown elapsed: let this call through as a trial. A burst of
            # concurrent callers can all be treated as trials at once here -
            # acceptable (a handful of trial calls is still far better than
            # the full storm this exists to prevent) rather than adding the
            # complexity of a single-trial gate.

    def on_success(self) -> None:
        with self._lock:
            was_open = self._opened_at is not None
            self._consecutive_failures = 0
            self._opened_at = None
        if was_open:
            logger.info("Google Drive connectivity recovered - circuit breaker closed.")

    def on_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            newly_opened = (
                self._consecutive_failures >= self._failure_threshold and self._opened_at is None
            )
            if self._consecutive_failures >= self._failure_threshold:
                self._opened_at = time.monotonic()
        if newly_opened:
            logger.warning(
                "Google Drive has failed %d times in a row - circuit breaker open for %.0fs "
                "(further calls will fail immediately instead of retrying).",
                self._consecutive_failures,
                self._cooldown_seconds,
            )

    def reset(self) -> None:
        """
        Forces the breaker fully closed, discarding any failure count and
        any open/cooldown state. Not used by production code paths - this
        exists so tests that deliberately induce Drive failures (to test
        _retry()'s own translation/retry behavior) can reset the shared,
        process-wide breaker between tests, rather than one test's induced
        failures tripping the breaker and silently short-circuiting an
        unrelated later test for the rest of its cooldown window.
        """
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None


_drive_breaker = CircuitBreaker()


def get_drive_circuit_breaker() -> CircuitBreaker:
    return _drive_breaker
