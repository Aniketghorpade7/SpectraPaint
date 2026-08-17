import { describe, expect, it } from 'vitest';

import { generateLaunchSecret } from './secret';

describe('the per-launch secret', () => {
  it('is different every launch, so a leaked one is worthless next time', () => {
    const secrets = new Set(Array.from({ length: 100 }, () => generateLaunchSecret()));

    expect(secrets.size).toBe(100);
  });

  it('is long enough not to be guessed by a local process trying repeatedly', () => {
    expect(generateLaunchSecret().length).toBeGreaterThanOrEqual(32);
  });

  it('survives an HTTP header unescaped', () => {
    // base64url, so no padding, no slashes, nothing that needs quoting in `Authorization`.
    expect(generateLaunchSecret()).toMatch(/^[A-Za-z0-9_-]+$/);
  });
});
