import { describe, expect, it } from 'vitest';

import { isLightShade, labToCssColour } from './colour';

/**
 * Colour conversion is the one piece of maths in the renderer that has analytically known answers,
 * and getting it subtly wrong is invisible — every swatch still draws, just in the wrong colour. So
 * it is checked against reference values rather than against itself.
 *
 * Reference white D65, 2° observer, and the piecewise sRGB transfer function, both pinned by
 * docs/specs/v1-spectrapaint.md.
 */
describe('a Catalogue Lab value as a screen colour', () => {
  it('turns the Lab white point into sRGB white', () => {
    expect(labToCssColour({ l: 100, a: 0, b: 0 })).toBe('#ffffff');
  });

  it('turns Lab black into sRGB black', () => {
    expect(labToCssColour({ l: 0, a: 0, b: 0 })).toBe('#000000');
  });

  it('turns mid grey into a neutral, with all three channels equal', () => {
    const grey = labToCssColour({ l: 53.585, a: 0, b: 0 });

    const [, red, green, blue] = /^#(..)(..)(..)$/.exec(grey) ?? [];
    expect(red).toBe(green);
    expect(green).toBe(blue);
    // L* 53.6 is the perceptual middle, which sits near 128 in sRGB — not at 50% of linear light.
    expect(parseInt(red ?? '0', 16)).toBeGreaterThan(115);
    expect(parseInt(red ?? '0', 16)).toBeLessThan(135);
  });

  it('matches the reference conversion for sRGB primaries', () => {
    // The Lab coordinates of pure sRGB red, green and blue under D65 — from the standard, not from
    // this implementation.
    expect(labToCssColour({ l: 53.2408, a: 80.0925, b: 67.2032 })).toBe('#ff0000');
    expect(labToCssColour({ l: 87.7347, a: -86.1827, b: 83.1793 })).toBe('#00ff00');
    expect(labToCssColour({ l: 32.297, a: 79.1875, b: -107.8602 })).toBe('#0000ff');
  });

  it('uses the piecewise transfer function, not a 2.2 power curve', () => {
    // Deep in the shadows the two disagree, and a 2.2 curve would come out darker here. L* 2 is
    // inside the linear segment of the sRGB function.
    const nearlyBlack = labToCssColour({ l: 2, a: 0, b: 0 });
    const channel = parseInt(nearlyBlack.slice(1, 3), 16);

    expect(channel).toBeGreaterThan(4); // a 2.2 power curve gives ~3
    expect(channel).toBeLessThan(9);
  });

  it('clamps a Shade the monitor cannot show rather than refusing to draw it', () => {
    // A printed chip can be more saturated than the screen. The swatch narrows the choice down; the
    // Fandeck settles it (docs/design-decisions.md §8).
    expect(labToCssColour({ l: 60, a: 120, b: -120 })).toMatch(/^#[0-9a-f]{6}$/);
  });

  it('always produces a six-digit hex colour', () => {
    for (const lab of [
      { l: 0, a: -128, b: -128 },
      { l: 100, a: 127, b: 127 },
      { l: 50, a: 0, b: 0 },
    ]) {
      expect(labToCssColour(lab)).toMatch(/^#[0-9a-f]{6}$/);
    }
  });
});

describe('whether a swatch needs dark text on it', () => {
  it('calls a pale Shade light and a deep one not', () => {
    expect(isLightShade({ l: 94, a: 0.5, b: 2 })).toBe(true);
    expect(isLightShade({ l: 34, a: 6, b: -28 })).toBe(false);
  });

  it('decides on lightness alone, whatever the hue', () => {
    // L is perceptual by construction, which is why Shades are stored in Lab at all.
    expect(isLightShade({ l: 80, a: 60, b: -60 })).toBe(true);
    expect(isLightShade({ l: 20, a: 60, b: -60 })).toBe(false);
  });
});
