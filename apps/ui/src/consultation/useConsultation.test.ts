import { describe, expect, it } from 'vitest';

import type { ProgressStreamEvent } from '../../../desktop/src/bridge-types';
import { applyProgressEvent, type ConsultationState } from './useConsultation';

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
