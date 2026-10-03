import { describe, expect, it } from 'vitest';

import type { ProgressStreamEvent } from '../../../desktop/src/bridge-types';
import { ALL_WALLS, type PaintTarget } from './accent';
import { type PaintSnapshot, INITIAL_PAINT_HISTORY, redo, record, undo } from './history';
import {
  applyProgressEvent,
  restoresOriginalPhoto,
  shadeCodeOf,
  type ConsultationState,
} from './useConsultation';

const uploading: ConsultationState = {
  phase: 'uploading',
  sessionId: 'abc123',
  imageDataUrl: 'data:image/png;base64,AAAA',
  progressMessage: 'Reading your photo…',
};

describe('applyProgressEvent', () => {
  it('stays preparing and shows the latest message while progress flows', () => {
    const event: ProgressStreamEvent = { phase: 'progress', message: 'Finding the walls…' };

    const next = applyProgressEvent(uploading, event);

    expect(next).toEqual({ ...uploading, progressMessage: 'Finding the walls…' });
  });

  it('reveals the photo on done, keeping the photo already held', () => {
    const event: ProgressStreamEvent = { phase: 'done' };

    const next = applyProgressEvent(uploading, event);

    expect(next.phase).toBe('ready');
    expect(next.imageDataUrl).toBe(uploading.imageDataUrl);
    expect(next.sessionId).toBe(uploading.sessionId);
  });

  it('lands on the error state with the streamed message when preparation fails', () => {
    const event: ProgressStreamEvent = {
      phase: 'failed',
      message: 'That photo could not be read. Please try another photo.',
    };

    const next = applyProgressEvent(uploading, event);

    expect(next.phase).toBe('failed');
    expect(next.message).toBe('That photo could not be read. Please try another photo.');
  });

  it('never dead-ends: a failed event without a message still lands on an actionable error', () => {
    const event: ProgressStreamEvent = { phase: 'failed' };

    const next = applyProgressEvent(uploading, event);

    expect(next.phase).toBe('failed');
    expect(next.message).toBeTruthy();
  });

  it('applies a full stream in order: progress, progress, done', () => {
    const stream: ProgressStreamEvent[] = [
      { phase: 'progress', message: 'Reading your photo…' },
      { phase: 'progress', message: 'Finding the walls…' },
      { phase: 'done' },
    ];

    const final = stream.reduce(applyProgressEvent, uploading);

    expect(final.phase).toBe('ready');
    expect(final.imageDataUrl).toBe(uploading.imageDataUrl);
  });
});

/**
 * Issue #50's hook-level behaviour, minus the DOM: the hook's decisions are factored into pure
 * functions (`shadeCodeOf`, `restoresOriginalPhoto`) plus the pure `history` module, so the
 * sequences the hook performs are stated here without mounting React — the same reasoning that
 * put `applyRenderEvent` and `applyProgressEvent` outside the hook.
 */

twoShadesThenUndoAt('all walls', ALL_WALLS);

twoShadesThenUndoAt('one wall', { kind: 'plane', planeId: 'plane_1' });

function twoShadesThenUndoAt(name: string, target: PaintTarget): void {
  describe(`two Shades applied, then undo (${name})`, () => {
    const before: PaintSnapshot = { target, assignments: {} };
    const postA: PaintSnapshot = { target, assignments: { plane_1: 'AP-2140' } };
    const postB: PaintSnapshot = { target, assignments: { plane_1: 'AP-2150' } };

    it('restores the post-A snapshot, and the repaint carries the restored Shade', () => {
      // applyShade A records what the paint was before the tap (nothing painted yet);
      // applyShade B records post-A. Now is post-B.
      let history = record(INITIAL_PAINT_HISTORY, before);
      history = record(history, postA);
      const step = undo(history, postB);
      expect(step).not.toBeNull();
      expect(step?.restore).toEqual(postA);
      // Exactly one repaint is requested, for the restored state — with the Shade the restored
      // paint actually carries, which is what the render reducer pins the reply to.
      expect(shadeCodeOf(step!.restore)).toBe('AP-2140');
    });

    it('redo puts shade B back, and can then go no further', () => {
      let history = record(INITIAL_PAINT_HISTORY, before);
      history = record(history, postA);
      const undone = undo(history, postB)!;
      const redone = redo(undone.history, postB);
      expect(redone?.restore).toEqual(postB);
      expect(shadeCodeOf(redone!.restore)).toBe('AP-2150');
      expect(redo(redone!.history, redone!.restore)).toBeNull();
    });
  });
}

describe('undoing to the Consultation start (issue #50)', () => {
  it('returns to the original photo instead of requesting an empty repaint', () => {
    const empty: PaintSnapshot = { target: ALL_WALLS, assignments: {} };
    const history = record(INITIAL_PAINT_HISTORY, empty);
    const step = undo(history, { target: ALL_WALLS, assignments: { plane_1: 'AP-2140' } });

    expect(restoresOriginalPhoto(step!.restore)).toBe(true);
    // An empty snapshot must never reach the render request: the service answers an empty
    // assignment map with `422 malformed_request`.
    expect(step!.restore.assignments).toEqual({});
  });

  it('keeps the repaint when the restored snapshot still carries Shades', () => {
    const painted: PaintSnapshot = { target: ALL_WALLS, assignments: { plane_1: 'AP-2140' } };
    expect(restoresOriginalPhoto(painted)).toBe(false);
  });
});

describe('a correction clears the history (issue #50)', () => {
  it('leaves nothing to undo, so canUndo is false with no stale plane to replay onto', () => {
    // What correctWallsAt's success path does: setHistory(INITIAL_PAINT_HISTORY) drops every
    // snapshot, because a split or merge can retire the plane id a snapshot names.
    const retired = { ...INITIAL_PAINT_HISTORY };
    expect(retired.past).toHaveLength(0);
    expect(retired.future).toHaveLength(0);
    expect(undo(retired, { target: ALL_WALLS, assignments: { plane_1: 'AP-2140' } })).toBeNull();
    expect(redo(retired, { target: ALL_WALLS, assignments: { plane_1: 'AP-2140' } })).toBeNull();
  });
});
