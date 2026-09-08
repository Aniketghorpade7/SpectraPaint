import { describe, expect, it } from 'vitest';

import {
  describeArmedTool,
  effectiveArmedTool,
  tapPointFromFraction,
  toggleArmedTool,
} from './corrections';

describe('effectiveArmedTool', () => {
  it('is nothing when no tool is chosen and planes already exist', () => {
    expect(effectiveArmedTool(null, 2)).toBeNull();
  });

  it('auto-arms Add when there is nothing else to do', () => {
    expect(effectiveArmedTool(null, 0)).toBe('add');
  });

  it('an explicit choice wins even with zero planes', () => {
    expect(effectiveArmedTool('split', 0)).toBe('split');
  });

  it('an explicit choice wins with planes present too', () => {
    expect(effectiveArmedTool('merge', 3)).toBe('merge');
  });
});

describe('toggleArmedTool', () => {
  it('arms a tool that was not armed', () => {
    expect(toggleArmedTool(null, 'add')).toBe('add');
  });

  it('disarms the tool that was already armed', () => {
    expect(toggleArmedTool('split', 'split')).toBeNull();
  });

  it('switches from one armed tool straight to another', () => {
    expect(toggleArmedTool('split', 'merge')).toBe('merge');
  });
});

describe('describeArmedTool', () => {
  it('names the one thing the next tap does, for each tool', () => {
    expect(describeArmedTool('add')).toMatch(/add/i);
    expect(describeArmedTool('split')).toMatch(/split/i);
    expect(describeArmedTool('merge')).toMatch(/merge/i);
  });
});

describe('tapPointFromFraction', () => {
  it('scales a fraction of the rendered element to the photo’s own pixel space', () => {
    expect(tapPointFromFraction(0.5, 0.25, 1280, 720)).toEqual({ x: 640, y: 180 });
  });

  it('clamps to the last valid pixel rather than the photo width or height', () => {
    expect(tapPointFromFraction(1, 1, 1280, 720)).toEqual({ x: 1279, y: 719 });
  });

  it('clamps a fraction outside [0, 1] — a tap right at the rendered element’s own edge', () => {
    expect(tapPointFromFraction(-0.01, 1.01, 100, 100)).toEqual({ x: 0, y: 99 });
  });

  it('rounds to the nearest pixel rather than truncating', () => {
    // 0.5 / 1000 * 3 = 1.5, which must round up, not be floored to 1.
    expect(tapPointFromFraction(0.5, 0, 3, 1)).toEqual({ x: 2, y: 0 });
  });
});
