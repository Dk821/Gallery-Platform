// Extracts ONE poster frame from a local video File, entirely in the browser
// (<video> + <canvas>), so the server never has to download a multi-GB video
// back from Google Drive just to make a thumbnail. Photo thumbnails use the
// same trick, for smaller images - see photoThumbnail.ts.
//
// The File is played through a blob: URL, which the browser reads from the
// user's disk on demand (range-style) - nothing is copied into memory, so a
// 2 GB video is no more expensive to seek into than a 20 MB one.
//
// The frame is re-encoded as WebP (JPEG fallback on browsers without WebP
// canvas support - the backend normalizes to WebP regardless).
//
// This NEVER throws and never blocks an upload for long: any failure - a
// codec this browser can't decode (e.g. HEVC in some Chrome builds), a
// corrupt file, no canvas support, or hitting the overall deadline - resolves
// to null, and the caller simply uploads the video without a poster (the
// gallery shows its placeholder tile for it).

const MAX_DIMENSION = 720; // long side, px. ~30-150 KB as WebP.
const WEBP_QUALITY = 0.8;
// Hard ceiling for the whole extraction (metadata + seek + draw). It runs in
// parallel with the video's own upload, so this only matters for tiny videos
// that finish uploading almost immediately.
const OVERALL_TIMEOUT_MS = 20_000;
// Mean luma (0-255) under which a frame is treated as "basically black" -
// many videos fade in from black, and a black poster is worse than none.
const DARK_LUMA_THRESHOLD = 16;

const VIDEO_EXTENSION = /\.(mp4|mov|webm)$/i;

export function isVideoFile(file: File): boolean {
  return file.type.startsWith("video/") || VIDEO_EXTENSION.test(file.name);
}

// Resolves on the first of `events`; rejects on a media error or when the
// shared deadline passes. Each wait draws on the SAME deadline, so the whole
// extraction is bounded by OVERALL_TIMEOUT_MS no matter how many waits it
// chains together.
function waitFor(video: HTMLVideoElement, events: string[], deadline: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("poster extraction timed out"));
    }, Math.max(1, deadline - Date.now()));
    const onOk = () => {
      cleanup();
      resolve();
    };
    const onError = () => {
      cleanup();
      reject(new Error("video could not be decoded"));
    };
    function cleanup() {
      clearTimeout(timer);
      events.forEach((e) => video.removeEventListener(e, onOk));
      video.removeEventListener("error", onError);
    }
    events.forEach((e) => video.addEventListener(e, onOk));
    video.addEventListener("error", onError);
  });
}

async function seekTo(video: HTMLVideoElement, time: number, deadline: number): Promise<void> {
  // Setting currentTime to (roughly) where it already is fires no "seeked"
  // event, so waiting for one would just hang until the deadline.
  if (Math.abs(video.currentTime - time) > 0.01) {
    const seeked = waitFor(video, ["seeked"], deadline); // listen BEFORE seeking
    video.currentTime = time;
    await seeked;
  }
  // HAVE_CURRENT_DATA (2): a frame is actually available to draw.
  if (video.readyState < 2) {
    await waitFor(video, ["loadeddata", "canplay"], deadline);
  }
}

function meanLuma(source: HTMLCanvasElement): number {
  // Downscale to a tiny canvas first: averaging 32x32 pixels is plenty to
  // tell "black" from "not black" and costs nothing.
  const probe = document.createElement("canvas");
  probe.width = 32;
  probe.height = 32;
  const ctx = probe.getContext("2d");
  if (!ctx) return 255; // can't measure -> don't second-guess the frame
  ctx.drawImage(source, 0, 0, 32, 32);
  const { data } = ctx.getImageData(0, 0, 32, 32);
  let sum = 0;
  for (let i = 0; i < data.length; i += 4) {
    sum += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
  }
  return sum / (data.length / 4);
}

function drawFrame(video: HTMLVideoElement): HTMLCanvasElement | null {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return null; // audio-only, or the video track didn't decode
  const scale = Math.min(1, MAX_DIMENSION / Math.max(vw, vh));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(vw * scale));
  canvas.height = Math.max(1, Math.round(vh * scale));
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas;
}

function toImageBlob(canvas: HTMLCanvasElement): Promise<Blob | null> {
  // Prefer WebP (the app's standard thumbnail format); some older browsers
  // can't encode it, so fall back to JPEG - the backend re-normalizes
  // whatever arrives to WebP anyway (see normalize_browser_thumbnail).
  return new Promise((resolve) => {
    canvas.toBlob(
      (webp) => {
        if (webp) {
          resolve(webp);
        } else {
          canvas.toBlob((jpeg) => resolve(jpeg), "image/jpeg", WEBP_QUALITY);
        }
      },
      "image/webp",
      WEBP_QUALITY
    );
  });
}

export async function extractVideoPoster(file: File): Promise<Blob | null> {
  if (typeof document === "undefined") return null;

  const url = URL.createObjectURL(file);
  const video = document.createElement("video");
  const deadline = Date.now() + OVERALL_TIMEOUT_MS;

  try {
    // Muted + inline: required for a detached element to load on iOS/Safari
    // and keeps the browser from ever treating this as media to play aloud.
    video.muted = true;
    video.playsInline = true;
    video.preload = "metadata";
    video.src = url;

    await waitFor(video, ["loadedmetadata"], deadline);

    const duration = Number.isFinite(video.duration) ? video.duration : 0;
    // ~1 s in - the same spot the old server-side ffmpeg step used - or the
    // midpoint for clips shorter than 2 s.
    const primaryTime = duration > 0 ? Math.min(1, duration / 2) : 0;

    await seekTo(video, primaryTime, deadline);
    let best = drawFrame(video);
    if (!best) return null;

    // Faded in from black? Take one more look further in and keep whichever
    // frame is brighter. One retry at most: this stays cheap on huge files.
    if (duration > 4 && meanLuma(best) < DARK_LUMA_THRESHOLD) {
      try {
        await seekTo(video, duration * 0.25, deadline);
        const later = drawFrame(video);
        if (later && meanLuma(later) > meanLuma(best)) best = later;
      } catch {
        /* keep the first frame */
      }
    }

    return await toImageBlob(best);
  } catch {
    return null;
  } finally {
    // Release the decoder and the blob URL promptly - up to several of these
    // can run at once (one per concurrent upload), and each pins a handle to
    // a potentially multi-GB file until released.
    try {
      video.pause();
      video.removeAttribute("src");
      video.load();
    } catch {
      /* best effort */
    }
    URL.revokeObjectURL(url);
  }
}
