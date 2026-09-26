"""
Section 15/22: thumbnails for the gallery grid, poster frames for videos.
Deliberately synchronous, called inline during upload rather than via a
queue - per Section 46 ("do not overengineer the MVP"), a background job
queue is unwarranted complexity for single-image/frame generation that
takes well under a second.

Failures here are non-fatal to the upload: a missing thumbnail means the
gallery grid falls back to a placeholder icon, not a failed upload.

VIDEO posters (and now PHOTO thumbs) are no longer generated on the server
during upload: the browser extracts the frame locally (frontend/src/utils/
videoPoster.ts and photoThumbnail.ts) and uploads that small image to
POST /upload-session/{id}/thumbnail instead, so this server never has to
read a multi-GB video (or a whole photo) back from Drive to make a
thumbnail. generate_video_poster() / the ffmpeg check below are
intentionally left in place (they're still covered by
tests/test_ffmpeg_availability.py and are the natural tool for a future
backfill of videos uploaded without a poster), but nothing in the upload
path calls them anymore.

Every thumbnail the upload path stores is WEBP (image/webp) - photo
thumbnails and video posters both. Media.thumbnail_mime_type records what
each row's thumbnail actually is, and the streaming route serves it under
that content type, so older JPEG thumbnails keep working.
"""

import functools
import logging
import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from typing import BinaryIO

from PIL import Image, ImageOps

logger = logging.getLogger("gallery.thumbnails")

THUMBNAIL_MAX_DIMENSION = 400
# WebP everywhere going forward: photo thumbnails and video posters alike.
# smaller than the JPEG it replaces at the same quality, and the browser
# already produces it natively for uploads (see photoThumbnail.ts).
THUMBNAIL_WEBP_QUALITY = 82
# Browser-generated thumbnails (photo thumbs + video posters) are kept a
# little larger than server-side photo thumbnails for video posters: a
# single poster frame per video, not a grid of hundreds of tiles.
VIDEO_POSTER_MAX_DIMENSION = 720
# Decode guard for browser-supplied thumbnails: a legitimate photo thumb is
# <= 400px and a poster <= ~720px on its long side, so anything decoding to
# more than this many pixels is not a thumbnail (and would cost real memory
# to decode just to be shrunk).
BROWSER_THUMBNAIL_MAX_SOURCE_PIXELS = 16_000_000
BROWSER_THUMBNAIL_ALLOWED_FORMATS = {"JPEG", "WEBP", "PNG"}
FFMPEG_TIMEOUT_SECONDS = 30
FFMPEG_POSTER_TIMESTAMP_SECONDS = 1.0


@functools.lru_cache(maxsize=1)
def is_ffmpeg_available() -> bool:
    """
    Checks once per process whether the `ffmpeg` binary is on PATH.

    ffmpeg is a SYSTEM package, not something requirements.txt can pin or
    install - see SYSTEM_REQUIREMENTS.md. It is OPTIONAL now: video poster
    frames are extracted by the browser during upload, so nothing in the
    upload path needs it. This check (and generate_video_poster below) is
    kept for tooling such as backfilling a poster for a video that was
    uploaded without one.

    Cached so this only actually shells out once.
    """
    available = shutil.which("ffmpeg") is not None
    if not available:
        logger.info(
            "ffmpeg was not found on PATH. This does not affect uploads: video poster frames are "
            "generated in the browser. Only server-side poster backfill tooling needs ffmpeg."
        )
    return available


def generate_image_thumbnail(
    file_obj: BinaryIO,
    max_dimension: int = THUMBNAIL_MAX_DIMENSION,
    quality: int = THUMBNAIL_WEBP_QUALITY,
) -> bytes | None:
    """
    Pillow can read directly from the file-like object already sitting in
    memory/disk from the upload - no extra copy needed for images, since
    they're small enough (Section 16's allowed types) that this never
    approaches the multi-GB concern Section 38 is about.
    """
    try:
        file_obj.seek(0)
        image = Image.open(file_obj)
        image.load()  # force decode while the source file_obj is still open
        image = ImageOps.exif_transpose(image)  # respect camera rotation metadata
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((max_dimension, max_dimension))

        buffer = BytesIO()
        image.save(buffer, format="WEBP", quality=quality)
        return buffer.getvalue()
    except Exception as exc:  # noqa: BLE001 - any decode failure just means "no thumbnail"
        logger.warning("Image thumbnail generation failed: %s", exc)
        return None
    finally:
        try:
            file_obj.seek(0)
        except Exception:
            pass


def _is_acceptable_browser_image(data: bytes) -> bool:
    """
    Cheap header probe shared by every browser-generated image we accept
    (thumbnails, posters): checks the format and the declared
    dimensions WITHOUT decoding the pixels, so an oversized/decompression-bomb
    image is rejected before it is ever loaded into memory.
    """
    try:
        with Image.open(BytesIO(data)) as probe:
            if probe.format not in BROWSER_THUMBNAIL_ALLOWED_FORMATS:
                return False
            width, height = probe.size
        if width < 1 or height < 1 or width * height > BROWSER_THUMBNAIL_MAX_SOURCE_PIXELS:
            return False
    except Exception as exc:  # noqa: BLE001 - unreadable/hostile bytes just mean "no image"
        logger.warning("Browser image rejected (unreadable image): %s", exc)
        return False
    return True


def normalize_browser_thumbnail(data: bytes) -> bytes | None:
    """
    Validates and normalizes a thumbnail the BROWSER generated from a local
    file - a video poster (<video> + <canvas>) or a downscaled photo thumb
    (<img> + <canvas>) - before it is stored. Returns WebP bytes
    (<= VIDEO_POSTER_MAX_DIMENSION px for posters, <= THUMBNAIL_MAX_DIMENSION
    for photo thumbs - the browser already downscaled to the right size), or
    None if `data` isn't a usable image.

    Normalizing to WebP matters because the thumbnail streaming route
    (media_streaming.stream_media_thumbnail) serves every thumbnail under
    Media.thumbnail_mime_type - a browser that can't encode WebP from a
    canvas (older Safari falls back to JPEG/PNG) must not be able to store
    a thumbnail that is then served under the wrong content type. It also
    strips metadata and caps dimensions regardless of what the client sent.

    Reuses generate_image_thumbnail() - the same Pillow path used elsewhere -
    so there is one image-normalization implementation, not two. The header
    is probed BEFORE the full decode so an oversized/decompression-bomb
    image is rejected without ever being loaded into memory.
    """
    if not _is_acceptable_browser_image(data):
        return None
    return generate_image_thumbnail(BytesIO(data), max_dimension=VIDEO_POSTER_MAX_DIMENSION)


def generate_video_poster(file_obj: BinaryIO, filename_hint: str) -> bytes | None:
    """
    Writes the video to a temp file on local disk (NVMe, not RAM - Section
    38's concern is RAM, and this is a one-time, briefly-lived copy) so
    ffmpeg has a seekable file to grab a single frame from. The `-ss`
    flag before `-i` makes ffmpeg seek without decoding the whole file
    first, so this stays fast even for a multi-GB video.
    """
    suffix = os.path.splitext(filename_hint)[1] or ".mp4"
    if not is_ffmpeg_available():
        # Already logged once, loudly, by is_ffmpeg_available() itself (and
        # at startup). No need to repeat a warning on every single video
        # upload - just skip straight to "no poster" instead of spawning a
        # subprocess we already know will fail with FileNotFoundError.
        return None
    in_path = None
    out_path = None
    try:
        file_obj.seek(0)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as in_file:
            shutil.copyfileobj(file_obj, in_file, length=8 * 1024 * 1024)
            in_path = in_file.name

        out_path = in_path + ".thumb.jpg"
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(FFMPEG_POSTER_TIMESTAMP_SECONDS),
                "-i",
                in_path,
                "-frames:v",
                "1",
                "-q:v",
                "3",
                out_path,
            ],
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
        if result.returncode != 0 or not os.path.exists(out_path):
            logger.warning(
                "ffmpeg poster generation failed (code %s): %s",
                result.returncode,
                result.stderr.decode(errors="ignore")[:500],
            )
            return None

        with open(out_path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("ffmpeg binary not found on this system - skipping video poster generation.")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg poster generation timed out for %s.", filename_hint)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Video poster generation failed: %s", exc)
        return None
    finally:
        for path in (in_path, out_path):
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
        try:
            file_obj.seek(0)
        except Exception:
            pass
