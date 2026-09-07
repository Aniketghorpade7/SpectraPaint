/**
 * Export state on the Consultation surface, as a pure reducer (docs/design-decisions.md §9d).
 *
 * Export must not block browsing: a Dealer continues to pick Shades while the
 * full-resolution JPEG is generated and handed to the OS. So export is its own
 * slice of state, not a mode of the render state.
 */

export type ExportPhase = 'idle' | 'exporting' | 'ready' | 'failed';

export interface ExportState {
  phase: ExportPhase;
  /** The filename handed to the OS, present after a successful export. */
  filename?: string;
  /** The filesystem path, present after a successful export. */
  filePath?: string;
  /** Plain language, safe to show as-is. Present only when the phase is 'failed'. */
  message?: string;
}

export type ExportEvent =
  | { type: 'requested' }
  | { type: 'ready'; filename: string; filePath: string }
  | { type: 'failed'; code: string; message: string }
  | { type: 'dismiss' }
  | { type: 'cancelled' };

export const INITIAL_EXPORT_STATE: ExportState = { phase: 'idle' };

export function applyExportEvent(state: ExportState, event: ExportEvent): ExportState {
  switch (event.type) {
    case 'requested':
      return { phase: 'exporting' };
    case 'ready':
      return { phase: 'ready', filename: event.filename, filePath: event.filePath };
    case 'failed':
      return { phase: 'failed', message: event.message };
    case 'cancelled':
      return { phase: 'idle' };
    case 'dismiss':
      return { phase: 'idle' };
    default:
      return state;
  }
}
