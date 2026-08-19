import { describe, expect, it } from 'vitest';

import { MAX_RECENT_SHADES, withMostRecent } from './recentShades';
import type { Shade } from './shade';

/**
 * The ordering rule behind the recently-used row, tested as a pure function. Reading and writing
 * `localStorage` is not tested here: it would need a mock, and conventions.md §6 puts anything
 * needing one at seam 1 instead.
 */
function shade(shade_code: string): Shade {
  return {
    shade_code,
    name: `Shade ${shade_code}`,
    shade_family: 'Neutrals',
    lab: { l: 70, a: 2, b: 6 },
    finishes: ['matte'],
  };
}

describe('the recently-used row', () => {
  it('puts the newest Shade at the front, where the Dealer looks', () => {
    const row = withMostRecent([shade('A'), shade('B')], shade('C'));

    expect(row.map((entry) => entry.shade_code)).toEqual(['C', 'A', 'B']);
  });

  it('moves a Shade already in the row rather than repeating it', () => {
    // "Flick back to what we looked at two minutes ago" — a row with the same Shade three times
    // holds two fewer things to flick back to.
    const row = withMostRecent([shade('A'), shade('B'), shade('C')], shade('C'));

    expect(row.map((entry) => entry.shade_code)).toEqual(['C', 'A', 'B']);
  });

  it('stays short enough to scan at a glance', () => {
    let row: Shade[] = [];
    for (let index = 0; index < MAX_RECENT_SHADES + 5; index += 1) {
      row = withMostRecent(row, shade(`S-${index}`));
    }

    expect(row).toHaveLength(MAX_RECENT_SHADES);
    expect(row[0]?.shade_code).toBe(`S-${MAX_RECENT_SHADES + 4}`);
  });

  it('drops the oldest Shade when it overflows, not the newest', () => {
    const full = Array.from({ length: MAX_RECENT_SHADES }, (_, index) => shade(`S-${index}`));

    const row = withMostRecent(full, shade('NEW'));

    expect(row[0]?.shade_code).toBe('NEW');
    expect(row.map((entry) => entry.shade_code)).not.toContain(`S-${MAX_RECENT_SHADES - 1}`);
  });

  it('does not change the row it was given', () => {
    const row = [shade('A')];

    withMostRecent(row, shade('B'));

    expect(row.map((entry) => entry.shade_code)).toEqual(['A']);
  });
});
