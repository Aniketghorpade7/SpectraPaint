import { describe, expect, it } from 'vitest';

import { OVERSCAN_ROWS, pagesCovering, visibleWindow } from './virtualise';

/**
 * The arithmetic behind the virtualised list. A silent regression here is expensive and invisible:
 * the list still draws, it just draws the wrong rows or the wrong height of padding, and only a
 * thousand-Shade Catalogue on a slow machine shows it up (docs/design-decisions.md §9d).
 */
describe('which rows a virtualised list has to draw', () => {
  const list = { rowHeight: 50, viewportHeight: 500, rowCount: 1000 };

  it('draws the rows in view, plus a little either side', () => {
    const window = visibleWindow({ ...list, scrollTop: 0 });

    expect(window.start).toBe(0);
    expect(window.end).toBe(10 + OVERSCAN_ROWS);
  });

  it('follows the scroll', () => {
    const window = visibleWindow({ ...list, scrollTop: 5000 });

    expect(window.start).toBe(100 - OVERSCAN_ROWS);
    expect(window.end).toBe(100 + 10 + OVERSCAN_ROWS);
  });

  it('pads for exactly the rows it did not draw, so the scrollbar tells the truth', () => {
    const window = visibleWindow({ ...list, scrollTop: 5000 });
    const drawn = (window.end - window.start) * list.rowHeight;

    expect(window.paddingTop).toBe(window.start * list.rowHeight);
    expect(window.paddingTop + drawn + window.paddingBottom).toBe(list.rowCount * list.rowHeight);
  });

  it('never runs off either end of the list', () => {
    const atTop = visibleWindow({ ...list, scrollTop: -200 });
    expect(atTop.start).toBe(0);
    expect(atTop.paddingTop).toBe(0);

    const atBottom = visibleWindow({ ...list, scrollTop: 1_000_000 });
    expect(atBottom.end).toBe(list.rowCount);
    expect(atBottom.paddingBottom).toBe(0);
  });

  it('draws a row before the viewport has been measured', () => {
    // The first render happens before layout, and a list that is empty for a frame reads as broken.
    const window = visibleWindow({ ...list, viewportHeight: 0, scrollTop: 0 });

    expect(window.end).toBeGreaterThan(0);
  });

  it('draws nothing when there is nothing to draw', () => {
    expect(visibleWindow({ ...list, rowCount: 0, scrollTop: 0 })).toEqual({
      start: 0,
      end: 0,
      paddingTop: 0,
      paddingBottom: 0,
    });
  });

  it('draws the same number of rows whether the Catalogue holds a hundred or a hundred thousand', () => {
    // This is the criterion, stated as arithmetic: the work of drawing the list is set by the
    // viewport, not by the size of the Catalogue. It is what "a 1000+ Shade Catalogue scrolls
    // smoothly on a low-end machine" reduces to once the rendering is windowed.
    const drawn = (rowCount: number) => {
      const window = visibleWindow({ ...list, rowCount, scrollTop: 25 * rowCount });
      return window.end - window.start;
    };

    expect(drawn(1159)).toBe(drawn(100));
    expect(drawn(100_000)).toBe(drawn(100));
    expect(drawn(100)).toBeLessThanOrEqual(10 + 2 * OVERSCAN_ROWS);
  });

  it('never asks for more rows than a whole Fandeck', () => {
    const window = visibleWindow({ ...list, viewportHeight: 100_000, scrollTop: 0 });

    expect(window.end).toBe(list.rowCount);
  });
});

describe('which pages a window needs fetching', () => {
  it('names the one page a small window sits in', () => {
    expect(pagesCovering(10, 30, 200)).toEqual([0]);
  });

  it('names both pages when a window straddles a boundary', () => {
    expect(pagesCovering(190, 210, 200)).toEqual([0, 1]);
  });

  it('counts the last row as inside the window, not past it', () => {
    // end is exclusive: rows 0-199 are page 0 alone, and asking for page 1 too would fetch 200
    // Shades nobody is looking at.
    expect(pagesCovering(0, 200, 200)).toEqual([0]);
    expect(pagesCovering(0, 201, 200)).toEqual([0, 1]);
  });

  it('names every page a tall window crosses', () => {
    expect(pagesCovering(150, 650, 200)).toEqual([0, 1, 2, 3]);
  });

  it('asks for nothing when the window is empty', () => {
    expect(pagesCovering(40, 40, 200)).toEqual([]);
    expect(pagesCovering(0, 10, 0)).toEqual([]);
  });
});
