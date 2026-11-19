// Client gallery photo tiles start as a fixed 16 / 10.5 frame (so the grid has a
// sensible placeholder before anything has loaded). Once a thumbnail has loaded
// the tile takes that thumbnail's own aspect ratio, for portrait AND landscape
// photos, so nothing is cropped and the masonry layout (masonry.ts) can pack the
// tiles without gaps.
//
// The thumbnail is generated with Pillow's Image.thumbnail(), which preserves
// the photo's proportions, so naturalWidth / naturalHeight here is the
// original ratio (including EXIF rotation, which the thumbnail worker applies).

import { MASONRY_RELAYOUT_EVENT } from "./masonry";

export function applyMediaTileRatio(img: HTMLImageElement) {
  const tile = img.closest<HTMLElement>(".wedding-media-tile");
  if (!tile) return;

  const { naturalWidth, naturalHeight } = img;
  if (!naturalWidth || !naturalHeight) return;

  tile.classList.toggle("wedding-media-tile--portrait", naturalHeight > naturalWidth);
  tile.style.aspectRatio = `${naturalWidth} / ${naturalHeight}`;

  // Tell the grid its tile height changed so it re-packs the columns.
  tile.parentElement?.dispatchEvent(new Event(MASONRY_RELAYOUT_EVENT));
}
