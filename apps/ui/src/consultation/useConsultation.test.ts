import { describe, expect, it } from 'vitest';

import type {
  CorrectionTool,
  ProgressStreamEvent,
  WallPlaneOverlay,
} from '../../../desktop/src/bridge-types';
import { ALL_WALLS, type Assignments, type PaintTarget } from './accent';
import { INITIAL_RENDER_STATE, type RenderState } from './render';
import { applyProgressEvent, beginShadeTap, type ConsultationState } from './useConsultation';

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

describe('beginShadeTap', () => {
  const plane: WallPlaneOverlay = {
    planeId: 'wall_plane_1',
    surface: 'wall',
    coverage: 0.4,
    photoWidth: 640,
    photoHeight: 480,
    bounds: { left: 0, top: 0, right: 640, bottom: 480 },
    matteDataUrl: 'data:image/png;base64,AAAA',
  };
  const otherPlane: WallPlaneOverlay = {
    ...plane,
    planeId: 'wall_plane_2',
    bounds: { left: 320, top: 0, right: 640, bottom: 480 },
  };
  const planes = [plane, otherPlane];

  function tap(
    explicitTool: CorrectionTool | null,
    render: RenderState = INITIAL_RENDER_STATE,
    assignments: Assignments = {},
    target: PaintTarget = ALL_WALLS,
  ) {
    return beginShadeTap(explicitTool, render, assignments, target, planes, 'BLU001');
  }

  it('disarms every armed correction tool — tapping a Shade ends correcting (issue #49)', () => {
    for (const tool of ['add', 'add-ceiling', 'split', 'merge'] as const) {
      expect(tap(tool).explicitTool).toBeNull();
    }
    expect(tap(null).explicitTool).toBeNull();
  });

  it('marks the render requested for the tapped Shade', () => {
    const next = tap(null);

    expect(next.render.phase).toBe('rendering');
    expect(next.render.shadeCode).toBe('BLU001');
  });

  it('paints every wall with the tapped Shade when no wall is selected', () => {
    const next = tap(null);

    expect(next.assignments).toEqual({ wall_plane_1: 'BLU001', wall_plane_2: 'BLU001' });
  });

  it('keeps the other walls’ Shades when one wall is selected', () => {
    const next = tap(
      null,
      INITIAL_RENDER_STATE,
      { wall_plane_2: 'RED002' },
      {
        kind: 'plane',
        planeId: 'wall_plane_1',
      },
    );

    expect(next.assignments).toEqual({ wall_plane_2: 'RED002', wall_plane_1: 'BLU001' });
  });
});
