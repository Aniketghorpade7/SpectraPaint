import { describe, expect, it } from 'vitest';

import { MINIMUM_BOOT_MILLISECONDS, isBootFinished } from './useBoot';

describe('when the boot screen gives way to the app', () => {
  it('waits for the service even once the minimum has passed', () => {
    expect(isBootFinished({ phase: 'starting' }, true)).toBe(false);
    expect(isBootFinished({ phase: 'restarting' }, true)).toBe(false);
    expect(isBootFinished({ phase: 'failed', message: 'anything' }, true)).toBe(false);
  });

  it('holds the screen for the minimum even once the service is ready', () => {
    expect(isBootFinished({ phase: 'ready' }, false)).toBe(false);
  });

  it('finishes only when both are true', () => {
    expect(isBootFinished({ phase: 'ready' }, true)).toBe(true);
  });

  it('holds for at least two seconds', () => {
    expect(MINIMUM_BOOT_MILLISECONDS).toBeGreaterThanOrEqual(2_000);
  });
});
