import { describe, expect, it } from 'vitest';

import { applyRenderEvent, INITIAL_RENDER_STATE, type RenderState } from './render';

const RENDERING: RenderState = { phase: 'rendering', shadeCode: 'AP-2140', showingRender: false };

describe('applyRenderEvent', () => {
  it('moves from idle to rendering with the requested Shade Code', () => {
    const next = applyRenderEvent(INITIAL_RENDER_STATE, {
      type: 'requested',
      shadeCode: 'AP-2140',
    });

    expect(next).toEqual(RENDERING);
  });

  it('shows the repaint on success', () => {
    const next = applyRenderEvent(RENDERING, {
      type: 'ready',
      shadeCode: 'AP-2140',
      imageDataUrl: 'data:image/png;base64,AAAA',
    });

    expect(next.phase).toBe('ready');
    expect(next.imageDataUrl).toBe('data:image/png;base64,AAAA');
    expect(next.showingRender).toBe(true);
  });

  it('keeps the original photo on screen and shows the message when a render fails', () => {
    const next = applyRenderEvent(RENDERING, {
      type: 'failed',
      shadeCode: 'AP-2140',
      code: 'shade_not_found',
      message: 'That Shade Code is not in this Catalogue.',
    });

    expect(next.phase).toBe('failed');
    expect(next.message).toBe('That Shade Code is not in this Catalogue.');
    expect(next.showingRender).toBe(false);
  });

  it('drops a success for a Shade the Dealer has since replaced', () => {
    const superseded = applyRenderEvent(RENDERING, { type: 'requested', shadeCode: 'BL-1200' });

    const stale = applyRenderEvent(superseded, {
      type: 'ready',
      shadeCode: 'AP-2140',
      imageDataUrl: 'data:image/png;base64,OLD',
    });

    expect(stale).toEqual(superseded);
  });

  it('drops a failure for a Shade the Dealer has since replaced', () => {
    const superseded = applyRenderEvent(RENDERING, { type: 'requested', shadeCode: 'BL-1200' });

    const stale = applyRenderEvent(superseded, {
      type: 'failed',
      shadeCode: 'AP-2140',
      code: 'service_unavailable',
      message: 'The wall could not be repainted.',
    });

    expect(stale).toEqual(superseded);
  });

  it('toggles between the repaint and the original photo once a render is ready', () => {
    const ready = applyRenderEvent(RENDERING, {
      type: 'ready',
      shadeCode: 'AP-2140',
      imageDataUrl: 'data:image/png;base64,AAAA',
    });

    const original = applyRenderEvent(ready, { type: 'toggle' });
    expect(original.showingRender).toBe(false);

    const repaint = applyRenderEvent(original, { type: 'toggle' });
    expect(repaint.showingRender).toBe(true);
  });

  it('ignores a toggle when nothing is on screen', () => {
    const next = applyRenderEvent(INITIAL_RENDER_STATE, { type: 'toggle' });
    expect(next).toEqual(INITIAL_RENDER_STATE);
  });

  it('a failed render can be dismissed back to the original photo', () => {
    const failed = applyRenderEvent(RENDERING, {
      type: 'failed',
      shadeCode: 'AP-2140',
      code: 'shade_not_found',
      message: 'That Shade Code is not in this Catalogue.',
    });

    const next = applyRenderEvent(failed, { type: 'requested', shadeCode: 'BL-1200' });
    expect(next.phase).toBe('rendering');
    expect(next.shadeCode).toBe('BL-1200');
    expect(next.message).toBeUndefined();
  });
});
