"""
Shared between api/client_gallery.py and api/admin_media.py so there is
exactly one implementation of "stream a Media row's file/thumbnail out of
StorageService" - the two route modules differ only in which
authorization check they run before calling into this module (client
ownership vs admin access).
"""

import logging
import re
from urllib.parse import quote

from fastapi.responses import StreamingResponse

from app.models.media import Media
from app.schemas.errors import ApiError, not_found
from app.services.storage_service import StorageError, StorageNotFoundError, StorageService

logger = logging.getLogger("gallery.media_streaming")

# Matches a single-range "Range: bytes=START-END" header. Multi-range
# requests (e.g. "bytes=0-99,200-299") aren't something browsers send for
# <video>/<img> playback, so we deliberately only support one range and
# fall back to a full response for anything we don't recognize.
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def content_disposition_header(disposition: str, filename: str) -> str:
    # RFC 5987 filename* (percent-encoded UTF-8) handles non-ASCII names; the
    # plain filename= is a fallback for older clients that don't parse it.
    # Header values are written to the wire as latin-1, so the plain fallback
    # must be stripped down to ASCII - keeping the raw name here crashes every
    # stream/download response for a file whose name contains an emoji or
    # non-latin character (UnicodeEncodeError). Quotes/backslashes are
    # stripped rather than escaped - simplest safe option for a header.
    safe_fallback = filename.encode("ascii", "ignore").decode("ascii").replace('"', "").replace("\\", "")
    encoded = quote(filename)
    return f'{disposition}; filename="{safe_fallback}"; filename*=UTF-8\'\'{encoded}'


def _parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    """
    Parses a "Range: bytes=start-end" header into an inclusive (start, end)
    byte pair, clamped to the actual file size. Returns None if there's no
    header, or if it's present but unparseable/unsatisfiable - callers
    should treat None as "serve the whole file" (or, for a genuinely
    invalid explicit range, a 416 - see stream_media_file).
    """
    if not range_header:
        return None
    match = _RANGE_RE.match(range_header.strip())
    if not match:
        return None

    start_str, end_str = match.groups()
    if start_str == "" and end_str == "":
        return None

    if start_str == "":
        # Suffix range, e.g. "bytes=-500" = last 500 bytes.
        suffix_len = int(end_str)
        if suffix_len <= 0:
            return None
        start = max(file_size - suffix_len, 0)
        end = file_size - 1
    else:
        start = int(start_str)
        end = int(end_str) if end_str != "" else file_size - 1

    end = min(end, file_size - 1)
    if start > end or start < 0:
        raise ValueError("Unsatisfiable range")

    return start, end


def stream_media_file(
    media: Media,
    storage: StorageService,
    disposition: str,
    range_header: str | None = None,
) -> StreamingResponse:
    """
    Streams the ORIGINAL file (`media.google_drive_file_id`) with the given
    Content-Disposition.

    range_header, if given, is the raw incoming `Range` request header.
    When present and valid, this returns a 206 Partial Content response
    with Content-Range/Content-Length set to just that slice - required
    for <video> seeking, and for Safari to play video at all. When absent,
    behavior is unchanged: the full file streams back with a 200.
    """
    # Eager existence/access check before opening the streaming response -
    # once StreamingResponse starts, HTTP headers/status are already
    # committed, so any storage error needs to surface *before* that point
    # to become a proper {success:false, error} JSON response.
    try:
        stored = storage.get_file(media.google_drive_file_id)
    except StorageNotFoundError:
        raise not_found("The original file could not be found in storage.", code="MEDIA_FILE_MISSING")
    except StorageError:
        raise ApiError(502, "STORAGE_DOWNLOAD_FAILED", "Could not retrieve the file from storage. Please retry.")

    file_size = stored.size or media.file_size or 0

    byte_range = None
    if range_header and file_size > 0:
        try:
            byte_range = _parse_range_header(range_header, file_size)
        except ValueError:
            # A Range header was sent but doesn't fit the file (e.g. the
            # client has stale metadata) - 416 per RFC 7233, with
            # Content-Range telling it the actual size so it can retry.
            raise ApiError(
                416,
                "RANGE_NOT_SATISFIABLE",
                "The requested range is not satisfiable.",
                headers={"Content-Range": f"bytes */{file_size}"},
            )

    headers = {
        "Content-Disposition": content_disposition_header(disposition, media.file_name),
        # Tells the browser up front that range requests are supported, so
        # <video> knows it can seek before it has even made a range request.
        "Accept-Ranges": "bytes",
    }

    if byte_range is not None:
        start, end = byte_range
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(end - start + 1)
        status_code = 206

        def iter_bytes():
            try:
                yield from storage.download(media.google_drive_file_id, range_start=start, range_end=end)
            except StorageError as exc:
                logger.error("Storage error mid-stream (range) for media %s: %s", media.id, exc)
                return
    else:
        if file_size > 0:
            headers["Content-Length"] = str(file_size)
        status_code = 200

        def iter_bytes():
            try:
                yield from storage.download(media.google_drive_file_id)
            except StorageError as exc:
                # Can't change the HTTP status at this point - headers are
                # already sent. Just stop the stream; the client sees a
                # truncated/incomplete download and can retry.
                logger.error("Storage error mid-stream for media %s: %s", media.id, exc)
                return

    return StreamingResponse(iter_bytes(), status_code=status_code, media_type=media.mime_type, headers=headers)


def stream_media_thumbnail(media: Media, storage: StorageService) -> StreamingResponse:
    """Streams the generated thumbnail/poster (`media.thumbnail_reference`), inline, cached."""
    if not media.thumbnail_reference:
        raise not_found("No thumbnail available for this item.", code="THUMBNAIL_NOT_AVAILABLE")

    try:
        storage.get_file(media.thumbnail_reference)
    except StorageNotFoundError:
        raise not_found("No thumbnail available for this item.", code="THUMBNAIL_NOT_AVAILABLE")
    except StorageError:
        raise ApiError(502, "STORAGE_DOWNLOAD_FAILED", "Could not retrieve the thumbnail. Please retry.")

    def iter_bytes():
        try:
            yield from storage.download(media.thumbnail_reference)
        except StorageError as exc:
            logger.error("Storage error mid-stream for thumbnail of media %s: %s", media.id, exc)
            return

    # Thumbnails never change once generated, so browsers/CDNs are free to
    # cache them aggressively. Content-type comes from the Media row, not a
    # hard-coded value: older thumbnails are image/jpeg, everything stored
    # since the WebP switch is image/webp (see Media.thumbnail_mime_type).
    thumbnail_mime_type = media.thumbnail_mime_type or "image/jpeg"
    headers = {"Cache-Control": "private, max-age=86400"}
    return StreamingResponse(iter_bytes(), media_type=thumbnail_mime_type, headers=headers)

