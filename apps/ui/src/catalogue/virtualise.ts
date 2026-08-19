/**
 * Which rows a virtualised list actually has to draw.
 *
 * A Fandeck runs past a thousand Shades and rendering them all eagerly stalls a floor-tier machine
 * (docs/specs/v1-spectrapaint.md), so the list draws only the window on screen and spaces it with
 * padding above and below. This is the arithmetic behind that, kept pure and out of the component:
 * it is the part that can be wrong in a way nobody sees until the list is long.
 */

export interface Window {
  /** First row index to render, inclusive. */
  start: number;
  /** Last row index to render, exclusive. */
  end: number;
  /** Pixels of empty space standing in for the rows above the window. */
  paddingTop: number;
  /** Pixels standing in for the rows below it. */
  paddingBottom: number;
}

/**
 * Rows drawn beyond each edge of the viewport.
 *
 * Without this, a fast scroll shows blank space for a frame — the browser paints before React has
 * rendered the newly-visible rows. Three rows is enough to cover a frame at counter-speed scrolling
 * and cheap enough not to matter.
 */
export const OVERSCAN_ROWS = 3;

export function visibleWindow({
  scrollTop,
  viewportHeight,
  rowHeight,
  rowCount,
  overscan = OVERSCAN_ROWS,
}: {
  scrollTop: number;
  viewportHeight: number;
  rowHeight: number;
  rowCount: number;
  overscan?: number;
}): Window {
  if (rowCount <= 0 || rowHeight <= 0) {
    return { start: 0, end: 0, paddingTop: 0, paddingBottom: 0 };
  }

  // A viewport of zero happens on the first render, before layout has measured anything. Drawing one
  // row rather than none means the list is never empty for a frame.
  const rowsInView = Math.max(1, Math.ceil(Math.max(viewportHeight, 0) / rowHeight));

  const first = Math.floor(Math.max(scrollTop, 0) / rowHeight);
  const start = Math.max(0, first - overscan);
  const end = Math.min(rowCount, first + rowsInView + overscan);

  return {
    start,
    end,
    paddingTop: start * rowHeight,
    paddingBottom: Math.max(0, (rowCount - end) * rowHeight),
  };
}

/**
 * The pages a window needs, given a fixed page size.
 *
 * The Catalogue is fetched a page at a time rather than all at once, so scrolling into unfetched
 * territory has to know what to ask for. Returns page indices, not row indices.
 */
export function pagesCovering(start: number, end: number, pageSize: number): number[] {
  if (end <= start || pageSize <= 0) return [];

  const firstPage = Math.floor(start / pageSize);
  const lastPage = Math.floor((end - 1) / pageSize);

  return Array.from({ length: lastPage - firstPage + 1 }, (_, index) => firstPage + index);
}
