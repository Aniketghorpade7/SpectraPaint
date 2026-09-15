/**
 * The state of a repaint on the Consultation surface, driven as a pure reducer so the whole state
 * machine is testable without a DOM (docs/design-decisions.md §9d), on the model of
 * `applyProgressEvent`.
 *
 * The reducer decides how the render and the original photo relate on screen: a successful repaint
 * shows the render, with a before/after toggle back to the original photo; a failed repaint keeps
 * the original photo on screen and shows the service's message. Neither a render in flight nor a
 * failed one may leave the Dealer with a frozen swatch or no way back (docs/ui-guidelines.md).
 */

export type RenderPhase = 'idle' | 'rendering' | 'ready' | 'failed';

export interface RenderState {
  phase: RenderPhase;
  /** The Shade Code that produced the current render, present while it is in flight or on screen. */
  shadeCode?: string;
  /** The repainted photo, present when a render succeeded. */
  imageDataUrl?: string;
  /** Plain language, safe to show as-is. Present only when the phase is 'failed'. */
  message?: string;
  /** The service's machine-readable failure code, present only when the phase is 'failed'.
   * `session_not_found` is the one the surface treats specially (issue #15): it means the sidecar
   * restarted since this Consultation's session was created, not that the Shade itself failed, and
   * no retry against the same session id will ever succeed. */
  code?: string;
  /** Whether the repaint or the original photo is on screen after a success. */
  showingRender: boolean;
}

export type RenderEvent =
  | { type: 'requested'; shadeCode: string }
  | { type: 'ready'; shadeCode: string; imageDataUrl: string }
  | { type: 'failed'; shadeCode: string; code: string; message: string }
  | { type: 'toggle' };

export const INITIAL_RENDER_STATE: RenderState = { phase: 'idle', showingRender: false };

export function applyRenderEvent(state: RenderState, event: RenderEvent): RenderState {
  switch (event.type) {
    case 'requested':
      return {
        ...state,
        phase: 'rendering',
        shadeCode: event.shadeCode,
        message: undefined,
        code: undefined,
      };
    case 'ready':
      // A reply for a Shade the Dealer has since replaced is stale: the requested event for the
      // newer Shade moved the state on, and an old success must not overwrite it.
      if (state.phase !== 'rendering' || state.shadeCode !== event.shadeCode) return state;
      return {
        phase: 'ready',
        shadeCode: event.shadeCode,
        imageDataUrl: event.imageDataUrl,
        message: undefined,
        code: undefined,
        showingRender: true,
      };
    case 'failed':
      // Same staleness rule as 'ready': a failure for a superseded request must not surface.
      if (state.phase !== 'rendering' || state.shadeCode !== event.shadeCode) return state;
      // Back to the original photo, with the message the Dealer can act on — not a dead end.
      return {
        ...state,
        phase: 'failed',
        message: event.message,
        code: event.code,
        showingRender: false,
      };
    case 'toggle':
      return state.phase === 'ready' ? { ...state, showingRender: !state.showingRender } : state;
    default:
      return state;
  }
}
