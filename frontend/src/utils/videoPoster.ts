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
// Something this far below that is a placeholder/blank canvas (a video the
// browser never decoded), not a merely-dark real frame. We never store it.
const SOLID_BLACK_LUMA = 4;
// Resumption points scanned in order until a clearly non-black frame is
// found (each a fraction of the duration). Spot-checks further into the
// video catch fade-in-from-black footage and recover from a blank frame.
const CANDIDATE_FRACTIONS = [0.25, 0.5, 0.75];

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

// Browsers update the <video> element's presented frame asynchronously after
// "seeked" fires - drawing the canvas immediately can capture a not-yet-
// decoded frame. One requestAnimationFrame (~1 display refresh) is enough
// for the decoder to hand over the real frame.
function waitForPaint(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame !== "function") return resolve();
    requestAnimationFrame(() => resolve());
  });
}

// The core reason a <video>+<canvas> capture comes out black: a paused
// <video> element can sit on a placeholder (black) frame even after a
// "seeked" event, because it only ever PAINTS frames the decoder delivers
// during playback. This resolves once a REAL decoded frame has been
// presented to the element (the moment requestVideoFrameCallback fires, or
// one muted playback tick on browsers without it), then pauses again.
// Bounded by the shared deadline so a stalled decoder cannot hang the
// extraction; on timeout it resolves anyway and the caller keeps whatever
// it has (the solid-black guard then rejects it).
function nextDecodedFrame(video: HTMLVideoElement, deadline: number): Promise<void> {
  return new Promise((resolve) => {
    let settled = false;
    let cancel: (() => void) | null = null;

    const done = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (cancel) {
        try {
          cancel();
        } catch {
          /* no-op */
        }
      }
      try {
        video.pause();
      } catch {
        /* no-op */
      }
      resolve();
    };
    const timer = setTimeout(done, Math.max(1, deadline - Date.now()));

    // Start muted playback so the decoder actually produces painted frames.
    // play() can reject (autoplay policy) - if it does, keep whatever frame
    // the seek already produced rather than hanging.
    if (video.paused) {
      try {
        const playPromise = video.play() as unknown as Promise<void> | undefined;
        if (playPromise && typeof playPromise.catch === "function") {
          playPromise.catch(() => done());
        }
      } catch {
        /* autoplay unavailable - keep what we have */
      }
    }

    if (typeof video.requestVideoFrameCallback === "function") {
      const onFrame = () => done();
      let id: number | undefined;
      id = video.requestVideoFrameCallback(onFrame);
      cancel = () => {
        if (id !== undefined) video.cancelVideoFrameCallback(id);
      };
    } else {
      const onTick = () => done();
      video.addEventListener("timeupdate", onTick, { once: true });
      cancel = () => video.removeEventListener("timeupdate", onTick);
    }
  });
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
    // AUTO (not metadata): loading only metadata can leave the element sat
    // on a blank black placeholder - we need a track it can actually play.
    video.preload = "auto";
    // The element must be IN the document to actually paint frames: a video
    // that was never attached is never rendered, so the decoder has nothing
    // to present and every canvas draw comes out black (Chrome especially).
    // Hidden off-screen, 1x1, effectively invisible - never seen by anyone.
    video.width = 1;
    video.height = 1;
    video.style.position = "fixed";
    video.style.top = "0";
    video.style.left = "-10000px";
    video.style.opacity = "0.01";
    video.style.pointerEvents = "none";
    const host = document.body || document.documentElement;
    host.appendChild(video);
    video.src = url;

    await waitFor(video, ["loadedmetadata"], deadline);

    const duration = Number.isFinite(video.duration) ? video.duration : 0;
    // ~1 s in - the same spot the old server-side ffmpeg step used - or the
    // midpoint for clips shorter than 2 s.
    const primaryTime = duration > 0 ? Math.min(1, duration / 2) : 0;

    // Seek, force the decoder to DELIVER a painted frame (muted playback +
    // requestVideoFrameCallback - a paused element can draw black), then
    // capture it. Each spot is guarded: one un-seekable/unreadable position
    // must never abort the whole extraction, it just moves on to the next.
    const captureAt = async (time: number) => {
      try {
        await seekTo(video, time, deadline);
        await nextDecodedFrame(video, deadline);
        await waitForPaint();
        const canvas = drawFrame(video);
        return canvas ? { canvas, luma: meanLuma(canvas) } : null;
      } catch {
        return null;
      }
    };

    let best: { canvas: HTMLCanvasElement; luma: number } | null = await captureAt(primaryTime);

    // A black poster is worse than none. If the first frame is (still) dark -
    // faded in from black, or the decoder hasn't handed over a real frame -
    // scan a few spot-checks further in and keep the BRIGHTEST real frame.
    for (const fraction of CANDIDATE_FRACTIONS) {
      if (best && best.luma >= DARK_LUMA_THRESHOLD) break; // good enough already
      if (Date.now() > deadline) break;
      const time = duration * fraction;
      if (time <= 0 || Math.abs(time - primaryTime) < 0.05) continue;
      const attempt = await captureAt(time);
      if (attempt && (!best || attempt.luma > best.luma)) best = attempt;
    }

    // A solid-black frame is a decoder placeholder, not a real image - never
    // store it. Everything drawable failed or was still blank => no poster,
    // the gallery shows its placeholder tile. A merely-dark-but-real frame
    // (night footage) is still stored.
    if (!best || best.luma <= SOLID_BLACK_LUMA) return null;

    return await toImageBlob(best.canvas);
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
    try {
      if (video.parentNode) video.parentNode.removeChild(video);
    } catch {
      /* best effort */
    }
    URL.revokeObjectURL(url);
  }
}
