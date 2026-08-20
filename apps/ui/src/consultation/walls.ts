import type { WallPlaneOverlay } from '../../../desktop/src/bridge-types';

/**
 * What the Dealer is shown about the walls SpectraPaint found (ticket #6).
 *
 * A pure reducer, like render.ts, so the rules are testable without a DOM
 * (docs/design-decisions.md §9d).
 *
 * Two rules are worth stating, because both are decisions rather than mechanics.
 *
 * **The overlay is neutral, never coloured.** ui-guidelines.md is unambiguous: nothing saturated
 * may sit near the render, because simultaneous contrast genuinely shifts how the wall's colour
 * reads. The usual way to draw a segmentation mask — a bright translucent blue — is the one thing
 * this application must not do. So the overlay is a white wash, and the shade of it lives in CSS
 * with the rest of the greys.
 *
 * **It hides itself while a repaint is on screen.** The overlay exists to answer "did it find the
 * right wall?", which is a question the Dealer asks before choosing a Shade. Once there is a
 * repaint to look at, the same wash sits between the Customer and the colour they are judging.
 * Hiding it then is not a tidiness preference; leaving it up would corrupt the comparison the whole
 * product exists to support.
 */

export interface WallsState {
  /** Every Wall Plane found, in the service's order. One, until ticket #7. */
  planes: WallPlaneOverlay[];
  /** Whether the Dealer wants the overlay shown at all. */
  wanted: boolean;
  /**
   * Why there is no overlay, in plain language, when that is worth saying. Never shown as an error
   * state: a photo whose walls could not be outlined is still a photo that can be repainted, so
   * this is a note, not a dead end.
   */
  message?: string;
}

export const INITIAL_WALLS_STATE: WallsState = { planes: [], wanted: true };

export type WallsEvent =
  | { type: 'found'; planes: WallPlaneOverlay[] }
  | { type: 'unavailable'; message: string }
  | { type: 'toggle' }
  | { type: 'cleared' };

export function applyWallsEvent(state: WallsState, event: WallsEvent): WallsState {
  switch (event.type) {
    case 'found':
      return { planes: event.planes, wanted: state.wanted };
    case 'unavailable':
      return { planes: [], wanted: state.wanted, message: event.message };
    case 'toggle':
      return { ...state, wanted: !state.wanted };
    case 'cleared':
      return INITIAL_WALLS_STATE;
    default:
      return state;
  }
}

/**
 * Whether the overlay should be on screen right now.
 *
 * ``showingRender`` is passed in rather than stored, because it belongs to the render's state and
 * duplicating it here would mean two answers to the same question.
 */
export function overlayVisible(state: WallsState, showingRender: boolean): boolean {
  return state.wanted && !showingRender && state.planes.length > 0;
}
