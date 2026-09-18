from app.config.settings import Settings
from app.schemas.errors import bad_request

# Magic-byte signatures for the allowed types (Section 16: don't trust the
# extension alone). Checked against the first bytes actually read from the
# upload, not against the filename.
_IMAGE_SIGNATURES: dict[str, list[bytes]] = {
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "webp": [b"RIFF"],  # followed by "WEBP" at offset 8, checked separately below
    "gif": [b"GIF87a", b"GIF89a"],
}

# Video containers are boxes, not a single fixed prefix - "ftyp" appears a
# few bytes in for MP4/MOV, and WebM/MKV use an EBML header at byte 0.
# For MP4/MOV specifically we walk the actual box chain (see
# _has_iso_bmff_box below) rather than doing a substring search over a
# small fixed window - some real-world MOV exports put a "free"/"wide"
# box before "ftyp"/"moov", which would otherwise push the signature past
# a naive head[:32] check and get a perfectly valid video rejected.
_ISO_BMFF_LEADING_BOXES = {b"ftyp", b"moov", b"free", b"skip", b"wide", b"mdat", b"pnot", b"uuid", b"junk"}

_VIDEO_SIGNATURE_CHECKS = {
    "mp4": lambda head: _has_iso_bmff_box(head, {b"ftyp", b"moov"}),
    "mov": lambda head: _has_iso_bmff_box(head, {b"ftyp", b"moov"}),
    "webm": lambda head: head[:4] == b"\x1a\x45\xdf\xa3",
}

_MIME_BY_EXTENSION = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
}


def _get_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _has_iso_bmff_box(head: bytes, wanted: set[bytes]) -> bool:
    """
    Walks the ISO-BMFF/QuickTime box chain from the start of `head` looking
    for any box type in `wanted`. Each box is [4-byte big-endian size][4-byte
    ASCII type][payload...]; size==1 means a 64-bit size follows in the next
    8 bytes, size==0 means "extends to end of file". We only need to read
    box headers, not payloads, so this stays cheap even though `head` may
    be a few KB.

    This replaces a naive "does the signature appear anywhere in the first
    32 bytes" check, which incorrectly rejects real files where a small
    leading box (e.g. "free"/"wide") pushes "ftyp"/"moov" a bit further in.
    """
    offset = 0
    length = len(head)
    # Cap iterations so a malformed/adversarial header can't spin forever.
    for _ in range(64):
        if offset + 8 > length:
            return False
        size = int.from_bytes(head[offset : offset + 4], "big")
        box_type = head[offset + 4 : offset + 8]

        if box_type not in _ISO_BMFF_LEADING_BOXES:
            # Not a box type we recognize as a legitimate leading atom -
            # stop walking rather than risk false positives on unrelated
            # binary data that happens to look box-shaped.
            return False
        if box_type in wanted:
            return True

        if size == 1:
            if offset + 16 > length:
                return False
            size = int.from_bytes(head[offset + 8 : offset + 16], "big")
            header_len = 16
        elif size == 0:
            # Box runs to end of file - nothing more to find in this window.
            return False
        else:
            header_len = 8

        if size < header_len:
            return False  # malformed box, bail out safely
        offset += size

    return False


def guess_mime_type(filename: str) -> str:
    """
    Canonical mime type from the filename's extension alone - used before
    the direct-upload session is even created (Drive's X-Upload-Content-Type
    header), when no file bytes exist on this server yet to sniff. The
    authoritative type check still happens post-upload in validate_upload()
    below, against actual header bytes read back from Drive.
    """
    ext = _get_extension(filename)
    return _MIME_BY_EXTENSION.get(ext, "application/octet-stream")


def validate_upload_intent(settings: Settings, filename: str, file_size: int) -> str:
    """
    Cheap pre-flight check run BEFORE a Google Drive resumable session is
    minted for a direct browser upload - only the extension and the
    client-declared size are available at this point (no bytes exist on
    this server to sniff, by design). Returns the file's extension on
    success, raises ApiError otherwise.

    This intentionally mirrors only the extension/size portion of
    validate_upload() below - the magic-byte signature check still happens
    afterwards, once the file has landed in Drive and a small header slice
    can be read back (see complete_direct_upload in media_service.py).
    A file that fails signature validation at that point is deleted from
    Drive - this pre-check exists purely so an obviously-wrong request
    (wrong extension, oversized) fails fast without spending a Drive
    resumable-session round trip on it.
    """
    ext = _get_extension(filename)
    allowed_image = settings.allowed_image_extensions
    allowed_video = settings.allowed_video_extensions

    if ext not in allowed_image and ext not in allowed_video:
        raise bad_request(f"File type '.{ext}' is not allowed.", code="UNSUPPORTED_FILE_TYPE")

    if file_size <= 0:
        raise bad_request("Uploaded file is empty.", code="EMPTY_FILE")

    if file_size > settings.effective_max_upload_bytes:
        raise bad_request("File exceeds the maximum allowed upload size.", code="FILE_TOO_LARGE")

    return ext


def validate_upload(
    settings: Settings, filename: str, declared_content_type: str, file_size: int, header_bytes: bytes
) -> tuple[str, str]:
    """
    Returns (file_type, canonical_mime_type) on success, raises ApiError on
    any validation failure. `header_bytes` should be a few KB read from the
    start of the upload stream (video box-chain walking needs more than
    just the first 32 bytes to reliably find ftyp/moov).
    """
    ext = _get_extension(filename)
    allowed_image = settings.allowed_image_extensions
    allowed_video = settings.allowed_video_extensions

    if ext not in allowed_image and ext not in allowed_video:
        raise bad_request(
            f"File type '.{ext}' is not allowed.", code="UNSUPPORTED_FILE_TYPE"
        )

    if file_size <= 0:
        raise bad_request("Uploaded file is empty.", code="EMPTY_FILE")

    if file_size > settings.effective_max_upload_bytes:
        raise bad_request("File exceeds the maximum allowed upload size.", code="FILE_TOO_LARGE")

    canonical_mime = _MIME_BY_EXTENSION[ext]

    if ext in allowed_image:
        signatures = _IMAGE_SIGNATURES.get(ext, [])
        matches = any(header_bytes.startswith(sig) for sig in signatures)
        if ext == "webp":
            matches = header_bytes.startswith(b"RIFF") and header_bytes[8:12] == b"WEBP"
        if not matches:
            raise bad_request(
                "File contents do not match the declared image type.", code="FILE_SIGNATURE_MISMATCH"
            )
        return "photo", canonical_mime

    # video
    check = _VIDEO_SIGNATURE_CHECKS.get(ext)
    if check is None or not check(header_bytes):
        raise bad_request(
            "File contents do not match the declared video type.", code="FILE_SIGNATURE_MISMATCH"
        )
    return "video", canonical_mime
