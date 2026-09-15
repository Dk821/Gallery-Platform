"""
One place to shape the structured log events Section 11 asks for, so
every call site logs the same fields the same way instead of hand-rolling
a message string. Deliberately thin - it sits on top of the standard
`logging` module (Section 11: reuse the existing logging infrastructure),
it doesn't replace it.
"""

import logging

# Fields that must never reach a log line, regardless of what a caller
# passes in - a last-resort guard in addition to callers simply not
# passing these in the first place.
_FORBIDDEN_KEYS = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "session_token",
    "authorization",
    "secret",
}


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    safe_fields = {k: v for k, v in fields.items() if k.lower() not in _FORBIDDEN_KEYS and v is not None}
    rendered = " ".join(f"{k}={v!r}" for k, v in safe_fields.items())
    # Deliberately NOT passed via `extra=` - LogRecord reserves attribute
    # names like "filename"/"module"/"process" for its own use, and a
    # field here colliding with one of those raises inside the logging
    # module itself. Everything still ends up in the message text (and any
    # log-aggregation pipeline parsing "key=value" pairs out of the
    # message can extract these just as well as from `extra`).
    logger.log(level, "%s %s", event, rendered)
