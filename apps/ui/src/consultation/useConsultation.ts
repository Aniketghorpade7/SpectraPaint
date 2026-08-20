import { useCallback, useEffect, useRef, useState } from 'react';

import type {
  ProgressStreamEvent,
  RenderResult,
  WallsResult,
} from '../../../desktop/src/bridge-types';
import { applyRenderEvent, INITIAL_RENDER_STATE, type RenderState } from './render';
import { applyWallsEvent, INITIAL_WALLS_STATE, type WallsState } from './walls';

/**
 * The state of the Consultation surface, and the two things a Dealer can do to it.
 *
 * The photo is server-owned only in the sense that the session id comes from the service; the
 * pixels shown on screen are the data URL main handed over, so the renderer still does no
 * filesystem work. Discarding ends the session on the service, which is the "deleted session fails
 * cleanly" criterion made visible.
 *
 * From issue #4 the loading state is a live stream: the service reports preparation progress in
 * plain language ("Reading your photo…"), the stream ends with exactly one terminal event, and the
 * photo is revealed only once preparation is done — so the Dealer never stares at a silent spinner
 * (docs/ui-guidelines.md, never dead-end). A failed preparation ends its session on the service
 * too, so a rejected photo cannot orphan a session holding its bytes until the process exits.
 */

export type ConsultationPhase = 'idle' | 'uploading' | 'ready' | 'failed';

export interface ConsultationState {
  phase: ConsultationPhase;
  sessionId?: string;
  imageDataUrl?: string;
  /** Plain language, safe to show as-is. Present only when the phase is 'failed'. */
  message?: string;
  /** The latest preparation message, shown while the phase is 'uploading'. */
  progressMessage?: string;
}

export interface Consultation {
  state: ConsultationState;
  start: () => void;
  discard: () => void;
  /** The repaint's state on the Consultation surface. See render.ts for the reducer. */
  render: RenderState;
  /** Repaint the Wall Plane in a Shade Code. Safe to call with the photo on screen. */
  applyShade: (shadeCode: string) => void;
  /** Show the original photo or the repaint after a successful render. */
  toggleBeforeAfter: () => void;
  /** Leave a failed repaint behind and keep the original photo on screen. */
  dismissRender: () => void;
  /** The Wall Planes found in the photo, and whether their outline is on screen (ticket #6). */
  walls: WallsState;
  /** Show or hide the detected-wall overlay. */
  toggleWalls: () => void;
}

/** The fallback shown before the stream's first message arrives. */
const LOADING_MESSAGE = 'Loading your photo…';

const PREP_FAILED_MESSAGE = 'The photo could not be prepared. Please try another photo.';

const RENDER_FAILED_MESSAGE = 'The wall could not be repainted. Please try another Shade.';

const WALLS_UNAVAILABLE_MESSAGE =
  'The walls in this photo could not be shown. The photo can still be repainted.';

/**
 * The phase transition the progress stream drives, as a pure function so it is testable without a
 * DOM (docs/design-decisions.md §9d). A `progress` event keeps preparing; `done` reveals the photo
 * already held in state; `failed` lands on the never-dead-end error state with a message the Dealer
 * can act on.
 */
export function applyProgressEvent(
  state: ConsultationState,
  event: ProgressStreamEvent,
): ConsultationState {
  switch (event.phase) {
    case 'progress':
      return { ...state, phase: 'uploading', progressMessage: event.message ?? LOADING_MESSAGE };
    case 'done':
      return { ...state, phase: 'ready' };
    case 'failed':
      return { ...state, phase: 'failed', message: event.message ?? PREP_FAILED_MESSAGE };
    default:
      return state;
  }
}

export function useConsultation(): Consultation {
  const [state, setState] = useState<ConsultationState>({ phase: 'idle' });
  const [render, setRender] = useState<RenderState>(INITIAL_RENDER_STATE);
  const [walls, setWalls] = useState<WallsState>(INITIAL_WALLS_STATE);
  const unsubscribeRef = useRef<(() => void) | null>(null);

  // A subscription must not outlive the surface: discarding, starting again, or unmounting
  // mid-preparation all stop the stream rather than leak it.
  useEffect(() => {
    return () => {
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
    };
  }, []);

  const endSession = useCallback(async (sessionId: string) => {
    try {
      const response = await window.spectrapaint.request({
        path: `/sessions/${sessionId}`,
        method: 'DELETE',
      });
      if (!response.ok) {
        console.error('[consultation] could not end the session:', response.body);
      }
    } catch (error) {
      // Same rule as start(): the bridge rejecting must not strand the Dealer. Putting the photo
      // down is a local decision, so the session is dropped locally even when the service never
      // hears about it.
      console.error('[consultation] could not end the session:', error);
    }
  }, []);

  const loadWalls = useCallback(async (sessionId: string) => {
    // Asked for once, when preparation finishes. The service waits for preparation rather than
    // answering "not ready", so there is nothing to poll and nothing to retry.
    let result: WallsResult;
    try {
      result = await window.spectrapaint.walls(sessionId);
    } catch (error) {
      // A missing outline is cosmetic: the photo is still repaintable, which is what the Dealer
      // came for. So this is a note beside the photo, never an error state over it.
      console.error('[consultation] could not fetch the wall planes:', error);
      setWalls((previous) =>
        applyWallsEvent(previous, { type: 'unavailable', message: WALLS_UNAVAILABLE_MESSAGE }),
      );
      return;
    }

    setWalls((previous) =>
      applyWallsEvent(
        previous,
        result.status === 'ready'
          ? { type: 'found', planes: result.planes }
          : { type: 'unavailable', message: result.message },
      ),
    );
  }, []);

  const start = useCallback(async () => {
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    setRender(INITIAL_RENDER_STATE);
    setWalls(INITIAL_WALLS_STATE);
    setState({ phase: 'uploading', progressMessage: LOADING_MESSAGE });

    try {
      const result = await window.spectrapaint.createConsultation();
      switch (result.status) {
        case 'cancelled':
          // Walking away is a decision, not a failure — back to where the Dealer was, silently.
          setState({ phase: 'idle' });
          break;
        case 'ready': {
          const { sessionId, imageDataUrl } = result;
          const unsubscribe = window.spectrapaint.onProgress(sessionId, (event) => {
            setState((previous) => applyProgressEvent(previous, event));
            if (event.phase === 'done') {
              unsubscribeRef.current?.();
              unsubscribeRef.current = null;
              // The walls are known by the time preparation says done, so this is one request that
              // resolves immediately rather than a wait the Dealer notices.
              void loadWalls(sessionId);
            } else if (event.phase === 'failed') {
              unsubscribeRef.current?.();
              unsubscribeRef.current = null;
              // The failed session is dead on arrival — nothing can be retried against it. End it
              // on the service too, or every failed preparation orphans a session holding its photo
              // until the process exits (the only other DELETE path, discard, needs the ready phase).
              void endSession(sessionId);
            }
          });
          unsubscribeRef.current = unsubscribe;
          setState((previous) => ({ ...previous, sessionId, imageDataUrl }));
          break;
        }
        case 'failed':
          setState({ phase: 'failed', message: result.message });
          break;
      }
    } catch (error) {
      // The bridge rejected without a result (not a service refusal). Never dead-end: the Dealer
      // must not sit on "Loading your photo…" with no way out.
      console.error('[consultation] could not start a consultation:', error);
      setState({
        phase: 'failed',
        message: 'The photo could not be loaded. Please try another photo.',
      });
    }
  }, [endSession, loadWalls]);

  const discard = useCallback(() => {
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    if (state.phase === 'ready' && state.sessionId) {
      void endSession(state.sessionId);
    }
    setRender(INITIAL_RENDER_STATE);
    setWalls(INITIAL_WALLS_STATE);
    setState({ phase: 'idle' });
  }, [state, endSession]);

  const applyShade = useCallback(
    async (shadeCode: string) => {
      if (state.phase !== 'ready' || !state.sessionId) return;
      setRender((previous) => applyRenderEvent(previous, { type: 'requested', shadeCode }));

      let result: RenderResult;
      try {
        result = await window.spectrapaint.render(state.sessionId, shadeCode);
      } catch (error) {
        // The bridge rejected without a result (not a service refusal). Never dead-end: the Dealer
        // must not sit on "Repainting…" with no way out.
        console.error('[consultation] could not repaint the wall:', error);
        setRender((previous) =>
          applyRenderEvent(previous, {
            type: 'failed',
            shadeCode,
            code: 'render_failed',
            message: RENDER_FAILED_MESSAGE,
          }),
        );
        return;
      }

      if (result.status === 'ready') {
        setRender((previous) =>
          applyRenderEvent(previous, {
            type: 'ready',
            shadeCode,
            imageDataUrl: result.imageDataUrl,
          }),
        );
      } else {
        setRender((previous) =>
          applyRenderEvent(previous, {
            type: 'failed',
            shadeCode,
            code: result.code,
            message: result.message,
          }),
        );
      }
    },
    [state.phase, state.sessionId],
  );

  const toggleBeforeAfter = useCallback(() => {
    setRender((previous) => applyRenderEvent(previous, { type: 'toggle' }));
  }, []);

  const dismissRender = useCallback(() => {
    setRender(INITIAL_RENDER_STATE);
  }, []);

  const toggleWalls = useCallback(() => {
    setWalls((previous) => applyWallsEvent(previous, { type: 'toggle' }));
  }, []);

  return {
    state,
    start,
    discard,
    render,
    applyShade,
    toggleBeforeAfter,
    dismissRender,
    walls,
    toggleWalls,
  };
}
