/**
 * Turning a Catalogue Lab value into something the screen can draw.
 *
 * The Catalogue stores Shades in CIELAB (docs/specs/v1-spectrapaint.md), so a swatch cannot be
 * rendered without this conversion. Everything pinned by the spec is pinned here too, not left to a
 * default: reference white **D65, 2° observer**, and gamma meaning the **piecewise sRGB transfer
 * function**, never a 2.2 power curve. The two disagree most in the dark end, which is exactly where
 * a deep Shade lives.
 *
 * Pure, so it is tested directly against values with known answers.
 */

/** A Shade's colour as the Catalogue stores it. */
export interface Lab {
  l: number;
  a: number;
  b: number;
}

// D65, 2° observer, normalised to Y = 100. Changing these changes every swatch on screen.
const WHITE_X = 95.047;
const WHITE_Y = 100.0;
const WHITE_Z = 108.883;

// The linear-sRGB primaries under D65.
const XYZ_TO_LINEAR_RGB = [
  [3.2404542, -1.5371385, -0.4985314],
  [-0.969266, 1.8760108, 0.041556],
  [0.0556434, -0.2040259, 1.0572252],
] as const;

const DELTA = 6 / 29;

function inverseF(t: number): number {
  return t > DELTA ? t ** 3 : 3 * DELTA * DELTA * (t - 4 / 29);
}

/** The piecewise sRGB transfer function — not a 2.2 power curve (docs/design-decisions.md §6). */
function encodeGamma(channel: number): number {
  return channel <= 0.0031308 ? 12.92 * channel : 1.055 * channel ** (1 / 2.4) - 0.055;
}

function clamp(value: number, low = 0, high = 1): number {
  return Math.min(high, Math.max(low, value));
}

function toHexPair(channel: number): string {
  return Math.round(clamp(channel) * 255)
    .toString(16)
    .padStart(2, '0');
}

/**
 * The CSS colour for a Shade, as `#rrggbb`.
 *
 * Out-of-gamut Shades are clamped per channel rather than refused. A printed chip can be more
 * saturated than a monitor can show, and the guard-rail already stated in `docs/design-decisions.md`
 * §8 applies: the screen narrows the choice down, the Fandeck settles it. Showing the nearest
 * displayable colour is what every colour picker does; showing nothing would be worse.
 */
export function labToCssColour({ l, a, b }: Lab): string {
  const fy = (l + 16) / 116;
  const fx = fy + a / 500;
  const fz = fy - b / 200;

  const x = (WHITE_X * inverseF(fx)) / 100;
  const y = (WHITE_Y * inverseF(fy)) / 100;
  const z = (WHITE_Z * inverseF(fz)) / 100;

  const [red, green, blue] = XYZ_TO_LINEAR_RGB.map(
    ([rx, ry, rz]) => rx * x + ry * y + rz * z,
  ) as unknown as [number, number, number];

  return `#${[red, green, blue].map((channel) => toHexPair(encodeGamma(clamp(channel)))).join('')}`;
}

/**
 * Whether a Shade is light enough that text on top of it must be dark.
 *
 * Lightness alone decides it: L is perceptual by construction, which is the whole point of storing
 * Shades in Lab. The threshold sits where it does because a Shade Code has to stay legible on a
 * swatch the Dealer is reading across a counter.
 */
export const LIGHT_SHADE_THRESHOLD = 62;

export function isLightShade({ l }: Lab): boolean {
  return l >= LIGHT_SHADE_THRESHOLD;
}
