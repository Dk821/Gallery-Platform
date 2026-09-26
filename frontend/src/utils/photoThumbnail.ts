// Makes ONE small thumbnail WebP from a local image File, entirely in the
// browser (<img> + <canvas>), so the server never has to download the
// original back from Google Drive to make a grid thumbnail (option 1: the
// same trick videoPoster.ts already does for video posters).
//
// The File is read through a blob: URL, decoded by the browser natively
// (hardware-accelerated where available), downscaled to an at-most-400px
// tile, and re-encoded as WebP (~10-50 KB). Servers without WebP canvas
// support fall back to JPEG; the backend re-normalizes whatever arrives to
// WebP anyway, so the stored format is always consistent.
//
// This NEVER throws and never blocks an upload for long: any failure - an
// undecodable image, no canvas, an overly large decode, or the deadline -
// resolves to null, and the caller simply uploads without a thumbnail (the
// gallery shows its placeholder tile for it).

const MAX_DIMENSION = 400; // long side, px. Matches THUMBNAIL_MAX_DIMENSION on the backend.
const WEBP_QUALITY = 0.82;
// Decode guard: a legitimate thumbnail source is a normal photo, so anything
// decoding larger than this is treated as a hostile/accidental resource hog
// and skipped rather than pushed through Image + canvas.
const MAX_SOURCE_PIXELS = 50_000_000;
// Hard ceiling for the whole extraction (decode + draw + encode). It runs in
// parallel with the photo's own upload, so this only matters for tiny files
// that finish uploading almost immediately.
const OVERALL_TIMEOUT_MS = 15_000;

const IMAGE_EXTENSION = /\.(jpg|jpeg|png|webp|gif)$/i;

export function isImageFile(file: File): boolean {
  return file.type.startsWith("image/") || IMAGE_EXTENSION.test(file.name);
}

// toBlob can silently fail for an unsupported type (e.g. WebP on older
// Safari), so try the requested type first and fall back to JPEG if the
// canvas refused to encode it.
function toBlobWithFallback(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => {
    canvas.toBlob(
      (webp) => {
        if (webp) {
          resolve(webp);
        } else {
          canvas.toBlob((jpeg) => resolve(jpeg), "image/jpeg", quality);
        }
      },
      "image/webp",
      quality
    );
  });
}

interface RenderOptions {
  maxDimension: number;
  quality: number;
  what: string; // for the timeout error message only
}

// The one implementation: decode a local image File natively, downscale it
// onto a canvas, re-encode as WebP. Never throws - any failure is null.
async function renderPhotoToBlob(file: File, options: RenderOptions): Promise<Blob | null> {
  if (typeof document === "undefined") return null;

  const url = URL.createObjectURL(file);
  const img = new Image();
  const deadline = Date.now() + OVERALL_TIMEOUT_MS;

  try {
    img.decoding = "async";
    img.src = url;
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`${options.what} extraction timed out`)), deadline - Date.now());
      img.onload = () => {
        clearTimeout(timer);
        resolve();
      };
      img.onerror = () => {
        clearTimeout(timer);
        reject(new Error("image could not be decoded"));
      };
    });

    const iw = img.naturalWidth;
    const ih = img.naturalHeight;
    if (!iw || !ih) return null;
    if (iw * ih > MAX_SOURCE_PIXELS) return null;

    const scale = Math.min(1, options.maxDimension / Math.max(iw, ih));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(iw * scale));
    canvas.height = Math.max(1, Math.round(ih * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    // Browsers apply EXIF orientation to <img> decoding by default, so a
    // phone photo drawn here comes out the right way up, same as the
    // backend's ImageOps.exif_transpose used to guarantee server-side.
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    return await toBlobWithFallback(canvas, options.quality);
  } catch {
    return null;
  } finally {
    img.onload = null;
    img.onerror = null;
    URL.revokeObjectURL(url);
  }
}

// Grid/lightbox thumbnail (<= 400px). Behaviour unchanged by the refactor.
export function extractPhotoThumbnail(file: File): Promise<Blob | null> {
  return renderPhotoToBlob(file, { maxDimension: MAX_DIMENSION, quality: WEBP_QUALITY, what: "thumbnail" });
}
