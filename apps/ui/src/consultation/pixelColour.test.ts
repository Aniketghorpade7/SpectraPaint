import { describe, expect, it } from 'vitest';

import {
  pointerToSourcePixel,
  readoutActive,
  rgbToApproxCmyk,
  tooltipPlacement,
} from './pixelColour';

describe('rgbToApproxCmyk', () => {
  it('reads black as full K without dividing by zero', () => {
    expect(rgbToApproxCmyk({ r: 0, g: 0, b: 0 })).toEqual({ c: 0, m: 0, y: 0, k: 100 });
  });

  it('reads white as no ink at all', () => {
    expect(rgbToApproxCmyk({ r: 255, g: 255, b: 255 })).toEqual({ c: 0, m: 0, y: 0, k: 0 });
  });

  it('reads pure red as magenta and yellow', () => {
    expect(rgbToApproxCmyk({ r: 255, g: 0, b: 0 })).toEqual({ c: 0, m: 100, y: 100, k: 0 });
  });

  it('reads a mid grey as K only', () => {
    expect(rgbToApproxCmyk({ r: 128, g: 128, b: 128 })).toEqual({ c: 0, m: 0, y: 0, k: 50 });
  });

  it('reads a warm neutral', () => {
    expect(rgbToApproxCmyk({ r: 182, g: 164, b: 150 })).toEqual({ c: 0, m: 10, y: 18, k: 29 });
  });

  it('never produces NaN or out-of-range values', () => {
    for (const r of [0, 1, 127, 254, 255]) {
      for (const g of [0, 1, 127, 254, 255]) {
        for (const b of [0, 1, 127, 254, 255]) {
          const { c, m, y, k } = rgbToApproxCmyk({ r, g, b });
          for (const value of [c, m, y, k]) {
            expect(Number.isInteger(value)).toBe(true);
            expect(value).toBeGreaterThanOrEqual(0);
            expect(value).toBeLessThanOrEqual(100);
          }
        }
      }
    }
  });
});

describe('pointerToSourcePixel', () => {
  const box = { left: 100, top: 50, width: 400, height: 300 };

  it('maps the displayed box onto the natural resolution', () => {
    expect(pointerToSourcePixel(300, 200, box, 4000, 3000)).toEqual({ x: 2000, y: 1500 });
  });

  it('maps the top-left corner to the first pixel', () => {
    expect(pointerToSourcePixel(100, 50, box, 4000, 3000)).toEqual({ x: 0, y: 0 });
  });

  it('clamps the right and bottom edges to the last real pixel', () => {
    expect(pointerToSourcePixel(500, 350, box, 4000, 3000)).toEqual({ x: 3999, y: 2999 });
  });

  it('returns null outside the box', () => {
    expect(pointerToSourcePixel(99, 200, box, 4000, 3000)).toBeNull();
    expect(pointerToSourcePixel(300, 351, box, 4000, 3000)).toBeNull();
  });

  it('returns null for an image with no size yet', () => {
    expect(pointerToSourcePixel(300, 200, box, 0, 0)).toBeNull();
    expect(pointerToSourcePixel(300, 200, { ...box, width: 0 }, 4000, 3000)).toBeNull();
  });
});

describe('tooltipPlacement', () => {
  it('sits right of and below the cursor when there is room', () => {
    expect(tooltipPlacement(100, 100, 800, 600, 188, 72, 16)).toEqual({ left: 116, top: 116 });
  });

  it('flips left near the right edge', () => {
    const { left } = tooltipPlacement(780, 100, 800, 600, 188, 72, 16);
    expect(left).toBe(780 - 16 - 188);
  });

  it('flips above near the bottom edge', () => {
    const { top } = tooltipPlacement(100, 590, 800, 600, 188, 72, 16);
    expect(top).toBe(590 - 16 - 72);
  });

  it('stays inside a frame smaller than the tooltip needs', () => {
    const { left, top } = tooltipPlacement(10, 10, 100, 50, 188, 72, 16);
    expect(left).toBeGreaterThanOrEqual(0);
    expect(top).toBeGreaterThanOrEqual(0);
  });
});

describe('readoutActive', () => {
  it('is off unless the Dealer turned it on', () => {
    expect(readoutActive(false, null)).toBe(false);
  });

  it('is on when inspecting and no tool is armed', () => {
    expect(readoutActive(true, null)).toBe(true);
  });

  it('pauses while a correction tool is armed', () => {
    expect(readoutActive(true, 'add')).toBe(false);
    expect(readoutActive(true, 'split')).toBe(false);
  });
});
