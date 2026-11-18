// Client gallery photo tiles are square-ish by default (a fixed 16 / 10.5
// landscape frame). A portrait photo cropped into that frame loses most of the
// subject, so once its thumbnail has loaded we let the tile take the
// thumbnail's own aspect ratio instead. Landscape photos keep the fixed frame,
// so the grid's established look is unchanged for them.
//
// The thumbnail is generated with Pillow's Image.thumbnail(), which preserves
// the photo's proportions, so naturalWidth / naturalHeight here is the
// original ratio (including EXIF rotation, which the thumbnail worker applies).

export function applyMediaTileRatio(img: HTMLImageElement) {
  const tile = img.closest<HTMLElement>(".wedding-media-tile");
  if (!tile) return;

  const { naturalWidth, naturalHeight } = img;
  if (!naturalWidth || !naturalHeight) return;

  if (naturalHeight > naturalWidth) {
    tile.classList.add("wedding-media-tile--portrait");
    tile.style.aspectRatio = `${naturalWidth} / ${naturalHeight}`;
  } else {
    tile.classList.remove("wedding-media-tile--portrait");
    tile.style.removeProperty("aspect-ratio");
  }
}
