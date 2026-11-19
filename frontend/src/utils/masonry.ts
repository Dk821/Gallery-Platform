// Masonry layout for the client gallery grids (.wedding-media-grid).
//
// Every tile keeps its photo's original aspect ratio (see mediaTileRatio.ts),
// so tiles have different heights. A plain CSS grid leaves empty gaps under the
// shorter tiles. This places each tile, in DOM order, into the currently
// shortest column, so the gaps disappear while the order still reads
// left-to-right / top-to-bottom for every sort option.
//
// The column count and gap come from the grid's own CSS (grid-template-columns
// and gap), so the existing breakpoints and the "large" layout keep working.

import { useEffect, useLayoutEffect, type RefObject } from "react";

export const MASONRY_RELAYOUT_EVENT = "masonry:relayout";

export function layoutMasonry(container: HTMLElement) {
  const style = getComputedStyle(container);
  const columns = style.gridTemplateColumns.split(" ").filter(Boolean).length || 1;
  const gap = parseFloat(style.columnGap) || 0;
  const rowGap = parseFloat(style.rowGap) || gap;
  const width = container.clientWidth;
  if (!width) return;

  const colWidth = (width - gap * (columns - 1)) / columns;
  const heights = new Array<number>(columns).fill(0);
  const tiles = Array.from(container.children) as HTMLElement[];

  for (const tile of tiles) {
    // Shortest column; ties go to the leftmost so the order stays left-to-right.
    let col = 0;
    for (let c = 1; c < columns; c++) {
      if (heights[c] < heights[col] - 0.5) col = c;
    }

    tile.style.position = "absolute";
    tile.style.width = `${colWidth}px`;
    tile.style.left = `${col * (colWidth + gap)}px`;
    tile.style.top = `${heights[col]}px`;

    heights[col] += tile.offsetHeight + rowGap;
  }

  const tallest = Math.max(0, ...heights) - (tiles.length ? rowGap : 0);
  container.style.height = `${Math.max(0, tallest)}px`;
}

export function useMasonry(ref: RefObject<HTMLElement | null>, deps: unknown[]) {
  // Re-place the tiles whenever the list changes (sort, search, load more, layout switch).
  useLayoutEffect(() => {
    if (ref.current) layoutMasonry(ref.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => layoutMasonry(el));
    };

    const observer = new ResizeObserver(schedule);
    observer.observe(el);
    el.addEventListener(MASONRY_RELAYOUT_EVENT, schedule);
    window.addEventListener("resize", schedule);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      el.removeEventListener(MASONRY_RELAYOUT_EVENT, schedule);
      window.removeEventListener("resize", schedule);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
