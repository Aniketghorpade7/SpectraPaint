import { describe, expect, it } from 'vitest';

import { applyExportEvent, INITIAL_EXPORT_STATE } from './export';

describe('export', () => {
  it('starts exporting from idle', () => {
    const next = applyExportEvent(INITIAL_EXPORT_STATE, { type: 'requested' });
    expect(next.phase).toBe('exporting');
  });

  it('lands ready with filename and filePath', () => {
    const exporting = applyExportEvent(INITIAL_EXPORT_STATE, { type: 'requested' });
    const ready = applyExportEvent(exporting, {
      type: 'ready',
      filename: 'PS-1001-Morning-Linen.jpg',
      filePath: '/tmp/PS-1001-Morning-Linen.jpg',
    });
    expect(ready.phase).toBe('ready');
    expect(ready.filename).toBe('PS-1001-Morning-Linen.jpg');
    expect(ready.filePath).toBe('/tmp/PS-1001-Morning-Linen.jpg');
  });

  it('cancellation returns to idle so browsing continues', () => {
    const exporting = applyExportEvent(INITIAL_EXPORT_STATE, { type: 'requested' });
    const cancelled = applyExportEvent(exporting, { type: 'cancelled' });
    expect(cancelled.phase).toBe('idle');
  });

  it('failure keeps the message and dismiss goes back to idle', () => {
    const exporting = applyExportEvent(INITIAL_EXPORT_STATE, { type: 'requested' });
    const failed = applyExportEvent(exporting, {
      type: 'failed',
      code: 'export_failed',
      message: 'The export could not be completed. Please try again.',
    });
    expect(failed.phase).toBe('failed');
    expect(failed.message).toBe('The export could not be completed. Please try again.');
    const idle = applyExportEvent(failed, { type: 'dismiss' });
    expect(idle.phase).toBe('idle');
  });

  it('export state does not touch render state — non-blocking', () => {
    // The export reducer is its own slice; a Dealer picks another Shade while export is in flight.
    const exporting = applyExportEvent(INITIAL_EXPORT_STATE, { type: 'requested' });
    // No transition here removes 'exporting'; only export events affect it. Browsing (render) is separate.
    expect(exporting.phase).toBe('exporting');
    const ready = applyExportEvent(exporting, {
      type: 'ready',
      filename: 'PS-1002-Morning-Chalk.jpg',
      filePath: '/tmp/x.jpg',
    });
    expect(ready.phase).toBe('ready');
  });
});
