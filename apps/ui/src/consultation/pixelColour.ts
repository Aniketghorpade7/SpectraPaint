import type { CorrectionTool } from '../../../desktop/src/bridge-types';

/**
 * The maths behind the Pixel Readout (issue #58): which pixel the cursor is over, what that pixel's
 * colour is in CMYK, and where the tooltip may sit. Pure, so the parts that are easy to get subtly
 * wrong — off-by-one at the image edge, a divide by zero on black — are testable without a browser.
 */

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

/** Each channel as a whole percentage, 0–100. */
export interface Cmyk {
  c: number;
  m: number;
  y: number;
  k: number;
}

/**
 * CMYK from RGB by the plain formula: K is how far the brightest channel falls short of white, and
 * C, M, Y are what remains once K is taken out.
 *
 * An approximation, and labelled as one wherever it is shown. Both images are RGB — a phone photo
 * and a lossless RGB render — so there is no CMYK in the pixels to read, and a true conversion
 * needs a printer's ICC profile that paint has no single right answer for. The Fandeck stays the
 * authority on real colour.
 */
export function rgbToApproxCmyk({ r, g, b }: Rgb): Cmyk {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const k = 1 - Math.max(rn, gn, bn);
  // Pure black has no hue to share out: the formula divides by (1 − K), which is zero.
  if (k >= 1) return { c: 0, m: 0, y: 0, k: 100 };
  const share = (channel: number) => Math.round(((1 - channel - k) / (1 - k)) * 100);
  return { c: share(rn), m: share(gn), y: share(bn), k: Math.round(k * 100) };
}

/** The box the image is drawn in, in client pixels. */
export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * The source pixel under the cursor, at the image's *natural* resolution — a 4000×3000 photo is
 * shown far smaller than it is, and the readout is the one pixel, not whatever the screen blended.
 * Clamped to the last pixel so the right and bottom edges read a real one; `null` outside the box.
 */
export function pointerToSourcePixel(
  clientX: number,
  clientY: number,
  box: Box,
  naturalWidth: number,
  naturalHeight: number,
): { x: number; y: number } | null {
  if (box.width <= 0 || box.height <= 0 || naturalWidth <= 0 || naturalHeight <= 0) return null;
  const fx = (clientX - box.left) / box.width;
  const fy = (clientY - box.top) / box.height;
  if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return null;
  return {
    x: Math.min(naturalWidth - 1, Math.floor(fx * naturalWidth)),
    y: Math.min(naturalHeight - 1, Math.floor(fy * naturalHeight)),
  };
}

/** The tooltip's size and its gap from the cursor, in CSS pixels. Fixed so placement needs no measuring. */
export const TOOLTIP_WIDTH = 232;
export const TOOLTIP_HEIGHT = 64;
export const TOOLTIP_OFFSET = 16;

/**
 * Where the tooltip's top-left goes, in the frame's own coordinates. Prefers right of and below the
 * cursor, flips to the other side when that would leave the frame, and finally clamps — so it never
 * covers the pixel being read and never leaves the frame.
 */
export function tooltipPlacement(
  x: number,
  y: number,
  frameWidth: number,
  frameHeight: number,
  width = TOOLTIP_WIDTH,
  height = TOOLTIP_HEIGHT,
  offset = TOOLTIP_OFFSET,
): { left: number; top: number } {
  let left = x + offset;
  if (left + width > frameWidth) left = x - offset - width;
  let top = y + offset;
  if (top + height > frameHeight) top = y - offset - height;
  return {
    left: Math.max(0, Math.min(left, frameWidth - width)),
    top: Math.max(0, Math.min(top, frameHeight - height)),
  };
}

/**
 * Whether the readout may show. Off unless the Dealer turned it on; paused while a correction tool
 * is armed, because the image is then taking clicks and the cursor is doing something else.
 */
export function readoutActive(inspecting: boolean, armedTool: CorrectionTool | null): boolean {
  return inspecting && armedTool === null;
}
