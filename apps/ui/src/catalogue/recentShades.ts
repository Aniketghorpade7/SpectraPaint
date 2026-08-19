/**
 * The recently-used row: the Shades looked at in the last few minutes.
 *
 * "So that I can flick back to something we looked at two minutes ago" — the Customer changes their
 * mind, and re-finding a Shade by scrolling a thousand tiles is the interaction this exists to
 * remove.
 *
 * Kept in `localStorage`, deliberately, and not on the service. Ticket #11 owns persistence, and
 * this is not the kind of state that belongs in it: it is a scratch list, worthless a day later, and
 * putting it in the Bundle database would mean a schema and a migration for something a Dealer would
 * never miss. See docs/implementation-decisions.md.
 *
 * Keyed by Catalogue identity, so swapping the Catalogue does not surface Shades that no longer
 * exist — a code from another manufacturer's file would be a dead entry the Dealer cannot select.
 */

import type { Shade } from './shade';

/** Short by design: a row the Dealer scans at a glance, not a history. */
export const MAX_RECENT_SHADES = 8;

const KEY_PREFIX = 'spectrapaint.recent-shades';

function storageKey(catalogueId: string): string {
  return `${KEY_PREFIX}.${catalogueId}`;
}

/**
 * Move a Shade to the front of the list, dropping any older copy of it.
 *
 * Pure, so the ordering rule can be tested without a browser. Most-recent first, because that is
 * the end the Dealer looks at.
 */
export function withMostRecent(shades: readonly Shade[], shade: Shade): Shade[] {
  const withoutIt = shades.filter((existing) => existing.shade_code !== shade.shade_code);
  return [shade, ...withoutIt].slice(0, MAX_RECENT_SHADES);
}

export function readRecentShades(catalogueId: string): Shade[] {
  try {
    const stored = window.localStorage.getItem(storageKey(catalogueId));
    if (!stored) return [];

    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];

    return parsed.filter(isShade).slice(0, MAX_RECENT_SHADES);
  } catch (error) {
    // Quiet recovery, but never silent (docs/conventions.md §5): a Dealer losing a convenience row
    // must not lose the Consultation, and a recurring fault must still be findable in the log.
    console.error('[catalogue] could not read the recently-used Shades:', error);
    return [];
  }
}

export function writeRecentShades(catalogueId: string, shades: readonly Shade[]): void {
  try {
    window.localStorage.setItem(storageKey(catalogueId), JSON.stringify(shades));
  } catch (error) {
    console.error('[catalogue] could not save the recently-used Shades:', error);
  }
}

/**
 * Whether a stored entry is still a Shade.
 *
 * Storage outlives the code that wrote it: a Dealer's machine can hold a row written by a previous
 * version, and trusting its shape would crash the panel rather than drop one stale entry.
 */
function isShade(value: unknown): value is Shade {
  if (typeof value !== 'object' || value === null) return false;

  const candidate = value as Partial<Shade>;
  return (
    typeof candidate.shade_code === 'string' &&
    typeof candidate.name === 'string' &&
    typeof candidate.shade_family === 'string' &&
    typeof candidate.lab === 'object' &&
    candidate.lab !== null &&
    typeof candidate.lab.l === 'number' &&
    typeof candidate.lab.a === 'number' &&
    typeof candidate.lab.b === 'number'
  );
}
