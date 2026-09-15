"""
Section 15/22: thumbnails for the gallery grid, poster frames for videos.
Deliberately synchronous, called inline during upload rather than via a
queue - per Section 46 ("do not overengineer the MVP"), a background job
queue is unwarranted complexity for single-image/frame generation that
takes well under a second.

Failures here are non-fatal to the upload: a missing thumbnail means the
gallery grid falls back to a placeholder icon, not a failed upload.
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
THUMBNAIL_JPEG_QUALITY = 82
FFMPEG_TIMEOUT_SECONDS = 30
FFMPEG_POSTER_TIMESTAMP_SECONDS = 1.0


@functools.lru_cache(maxsize=1)
def is_ffmpeg_available() -> bool:
    """
    Checks once per process whether the `ffmpeg` binary is on PATH.

    ffmpeg is a SYSTEM package, not something requirements.txt can pin or
    install - see SYSTEM_REQUIREMENTS.md. Without it, video uploads still
    succeed (Section 15/22: thumbnail failures are non-fatal), but every
    video in the gallery silently falls back to a placeholder icon with
    no poster frame, which is easy to miss until a client notices.

    Cached so this only actually shells out once; app startup (see
    app/main.py's lifespan) calls this eagerly and logs loudly if it's
    False, so the gap shows up in server logs/monitoring immediately
    instead of only as scattered per-upload warnings.
    """
    available = shutil.which("ffmpeg") is not None
    if not available:
        logger.warning(
            "ffmpeg was not found on PATH. Video uploads will still succeed, but NO video "
            "poster/thumbnail images will be generated until ffmpeg is installed on this "
            "server. See SYSTEM_REQUIREMENTS.md for install instructions."
        )
    return available


def generate_image_thumbnail(file_obj: BinaryIO, max_dimension: int = THUMBNAIL_MAX_DIMENSION) -> bytes | None:
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
        image.save(buffer, format="JPEG", quality=THUMBNAIL_JPEG_QUALITY)
        return buffer.getvalue()
    except Exception as exc:  # noqa: BLE001 - any decode failure just means "no thumbnail"
        logger.warning("Image thumbnail generation failed: %s", exc)
        return None
    finally:
        try:
            file_obj.seek(0)
        except Exception:
            pass


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
