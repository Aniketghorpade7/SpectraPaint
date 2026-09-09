import type { CorrectionTool, TapPoint } from '../../../desktop/src/bridge-types';

export type { CorrectionTool, TapPoint };

/**
 * Correcting the detected Wall Planes by tapping (ticket #10).
 *
 * Three tools — Add, Split, Merge — armed one at a time: the next tap on the photo performs
 * whichever is armed, then disarms itself, the same "act, do not confirm" rule the rest of this
 * surface already follows (ui-guidelines.md). Kept as pure functions, on the model of `accent.ts`
 * and `render.ts`, so the state transitions are testable without a DOM
 * (docs/design-decisions.md §9d) — this is the Wall Plane correction logic
 * docs/specs/v1-spectrapaint.md names as worth extracting once it exists.
 */

/**
 * Which tool is actually armed right now: what the Dealer explicitly chose, or Add by default
 * when there is nothing else to do — automatic detection found no wall at all, and the
 * correction surface is the only way forward (implementation-decisions.md #39).
 *
 * A derived value rather than its own piece of state, so auto-arming Add can never drift out of
 * sync with whether a plane actually exists the way a separately-set flag could: the moment a
 * plane exists, this stops returning `'add'` on its own, with nothing to remember to clear.
 */
export function effectiveArmedTool(
  explicitlyArmed: CorrectionTool | null,
  planeCount: number,
): CorrectionTool | null {
  if (explicitlyArmed) return explicitlyArmed;
  return planeCount === 0 ? 'add' : null;
}

/**
 * Arming the already-armed tool disarms it — the same toggle `toggleWalls`/`toggleTarget`/
 * `toggleRenderMode` already use, so this is not a new interaction to learn, only a familiar one
 * applied again (implementation-decisions.md #39).
 */
export function toggleArmedTool(
  explicitlyArmed: CorrectionTool | null,
  tool: CorrectionTool,
): CorrectionTool | null {
  return explicitlyArmed === tool ? null : tool;
}

/** What to tell the Dealer while a tool is armed — the one thing the next tap on the photo does. */
export function describeArmedTool(tool: CorrectionTool): string {
  switch (tool) {
    case 'add':
      return 'Tap where a wall is to add it.';
    case 'add-ceiling':
      return 'Tap where the ceiling is to add it.';
    case 'split':
      return 'Tap a wall to split it into two there.';
    case 'merge':
      return 'Tap the line between two walls to merge them.';
  }
}

/**
 * A tap's position on the photo, from where it landed on the rendered `<img>` element to the
 * pixel it names in the prepared photo — the coordinate space `photoWidth`/`photoHeight` already
 * describe (implementation-decisions.md #40).
 *
 * Takes the *fraction* across the rendered element, not the click event itself, so the geometry
 * is testable without a browser: the one line that reads `getBoundingClientRect` stays in the
 * component, thin enough to verify by running it (spec, "Deliberately not seams"). Clamped to the
 * last valid pixel rather than the photo's width/height, which the service would refuse as
 * outside the photo.
 */
export function tapPointFromFraction(
  fractionX: number,
  fractionY: number,
  photoWidth: number,
  photoHeight: number,
): TapPoint {
  const clamp = (fraction: number, size: number) =>
    Math.min(size - 1, Math.max(0, Math.round(fraction * size)));
  return { x: clamp(fractionX, photoWidth), y: clamp(fractionY, photoHeight) };
}
