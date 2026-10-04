import { describe, expect, it } from 'vitest';

import { ALL_WALLS, type PaintTarget } from './accent';
import {
  HISTORY_LIMIT,
  type PaintSnapshot,
  INITIAL_PAINT_HISTORY,
  redo,
  record,
  undo,
} from './history';

const snapshot = (target: PaintTarget, left: string, right?: string): PaintSnapshot => ({
  target,
  assignments: right ? { plane_1: left, plane_2: right } : { plane_1: left },
});

describe('record, undo, redo on paint history', () => {
  it('round-trips a snapshot: record, undo, redo restores what was undone', () => {
    const before: PaintSnapshot = snapshot(ALL_WALLS, 'AP-2140');
    let history = record(INITIAL_PAINT_HISTORY, before);
    expect(history.past).toEqual([before]);

    const now: PaintSnapshot = snapshot(ALL_WALLS, 'AP-2150');
    const undone = undo(history, now);
    expect(undone).not.toBeNull();
    expect(undone?.restore).toEqual(before);

    history = undone!.history;
    // Undoing leaves `now` in future so redo can put it back.
    const redone = redo(history, now);
    expect(redone?.restore).toEqual(now);
  });

  it('returns null when there is nothing to undo', () => {
    expect(undo(INITIAL_PAINT_HISTORY, snapshot(ALL_WALLS, 'AP-2140'))).toBeNull();
  });

  it('returns null when there is nothing to redo', () => {
    expect(redo(INITIAL_PAINT_HISTORY, snapshot(ALL_WALLS, 'AP-2140'))).toBeNull();
  });

  it('returns null redoing twice past the end of the future stack', () => {
    const before = snapshot(ALL_WALLS, 'AP-2140');
    let history = record(INITIAL_PAINT_HISTORY, before);
    const now = snapshot(ALL_WALLS, 'AP-2150');
    history = undo(history, now)!.history;

    const redone = redo(history, now);
    expect(redone).not.toBeNull();
    expect(redo(redone!.history, redone!.restore)).toBeNull();
  });

  it('a record after an undo clears the future — the redo branch is gone', () => {
    const before = snapshot(ALL_WALLS, 'AP-2140');
    let history = record(INITIAL_PAINT_HISTORY, before);
    history = undo(history, snapshot(ALL_WALLS, 'AP-2150'))!.history;
    expect(history.future).toHaveLength(1);

    // The Dealer paints again instead of redoing: the stale branch must not survive.
    history = record(history, snapshot(ALL_WALLS, 'AP-2160'));
    expect(history.future).toEqual([]);
    expect(redo(history, snapshot(ALL_WALLS, 'AP-2160'))).toBeNull();
  });

  it('caps the history at HISTORY_LIMIT entries, dropping the oldest', () => {
    let history = INITIAL_PAINT_HISTORY;
    for (let index = 0; index < HISTORY_LIMIT + 5; index += 1) {
      history = record(history, snapshot(ALL_WALLS, `AP-${1000 + index}`));
    }

    expect(history.past).toHaveLength(HISTORY_LIMIT);
    // The five oldest snapshots fell off; the newest survived.
    expect(history.past[0]).toEqual(snapshot(ALL_WALLS, `AP-${1000 + 5}`));
    expect(history.past[HISTORY_LIMIT - 1]).toEqual(snapshot(ALL_WALLS, `AP-${1000 + 54}`));
  });

  it('keeps the wall choice and the assignments together in one snapshot', () => {
    const target: PaintTarget = { kind: 'plane', planeId: 'plane_2' };
    const before = snapshot(target, 'AP-2140', 'AP-2200');
    const history = record(INITIAL_PAINT_HISTORY, before);

    expect(undo(history, snapshot(ALL_WALLS, 'AP-2141', 'AP-2201'))?.restore).toEqual(before);
  });
});
