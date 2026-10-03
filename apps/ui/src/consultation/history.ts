import type { Assignments, PaintTarget } from './accent';

/**
 * The Consultation's undo history for paint (issue #50).
 *
 * A snapshot records what the wall-choice target and the per-wall Shade assignments *were* just
 * before a change, so undoing restores both together — undoing a Shade that landed on one wall of
 * an Accent Wall has to hand back the target that produced it, not just the colour map. Pure
 * functions, tested in vitest like `accent.ts` and `render.ts`: shell logic neither test seam can
 * reach (docs/conventions.md §6).
 *
 * Deliberately *not* in here: wall corrections (Add/Split/Merge). A correction can retire a plane
 * id, and a snapshot naming a retired plane cannot be replayed honestly — so the hook clears the
 * whole history when a correction lands (implementation-decisions.md #40 makes the same call for
 * stale assignments). Across saves is also out: a reopened Consultation starts with no history,
 * because what the Customer saw last time is what reopening shows, not an editable past.
 */

/** What a repaint was, at one moment: which wall the next Shade paints, and what each carries. */
export interface PaintSnapshot {
  target: PaintTarget;
  assignments: Assignments;
}

export interface PaintHistory {
  past: PaintSnapshot[];
  future: PaintSnapshot[];
}

/** The history cap. Consultations are minutes long and Shade taps are a handful; 50 is generous. */
export const HISTORY_LIMIT = 50;

export const INITIAL_PAINT_HISTORY: PaintHistory = { past: [], future: [] };

/**
 * Record what the paint was *before* a change, as the newest entry of `past`, and clear `future` —
 * a new edit makes every redo branch stale. The oldest entry falls off once the cap is reached, so
 * a long browsing session cannot grow the stack without bound.
 */
export function record(history: PaintHistory, before: PaintSnapshot): PaintHistory {
  const past = [...history.past, before];
  return { past: past.slice(-HISTORY_LIMIT), future: [] };
}

/**
 * Step back: `now` is what the paint *is* this instant — it becomes the newest entry of `future` —
 * and the newest entry of `past` is what to restore. Returns `null` when there is nothing to undo,
 * which is exactly what the menu's disabled state should already have guaranteed.
 */
export function undo(
  history: PaintHistory,
  now: PaintSnapshot,
): { history: PaintHistory; restore: PaintSnapshot } | null {
  const previous = history.past[history.past.length - 1];
  if (!previous) return null;
  return {
    history: {
      past: history.past.slice(0, -1),
      future: [...history.future, now],
    },
    restore: previous,
  };
}

/**
 * Step forward: the mirror of `undo`. `now` (the state undo left behind) goes back onto `past`,
 * and the newest entry of `future` is what to restore. Returns `null` when there is nothing to
 * redo.
 */
export function redo(
  history: PaintHistory,
  now: PaintSnapshot,
): { history: PaintHistory; restore: PaintSnapshot } | null {
  const next = history.future[history.future.length - 1];
  if (!next) return null;
  return {
    history: {
      past: [...history.past, now],
      future: history.future.slice(0, -1),
    },
    restore: next,
  };
}
