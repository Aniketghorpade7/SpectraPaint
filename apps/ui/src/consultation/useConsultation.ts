import { useCallback, useState } from 'react';

/**
 * The state of the Consultation surface, and the two things a Dealer can do to it.
 *
 * The photo is server-owned only in the sense that the session id comes from the service; the
 * pixels shown on screen are the data URL main handed over, so the renderer still does no
 * filesystem work. Discarding ends the session on the service, which is the "deleted session fails
 * cleanly" criterion made visible.
 */

export type ConsultationPhase = 'idle' | 'uploading' | 'ready' | 'failed';

export interface ConsultationState {
  phase: ConsultationPhase;
  sessionId?: string;
  imageDataUrl?: string;
  /** Plain language, safe to show as-is. Present only when the phase is 'failed'. */
  message?: string;
}

export interface Consultation {
  state: ConsultationState;
  start: () => void;
  discard: () => void;
}

export function useConsultation(): Consultation {
  const [state, setState] = useState<ConsultationState>({ phase: 'idle' });

  const start = useCallback(async () => {
    setState({ phase: 'uploading' });

    try {
      const result = await window.spectrapaint.createConsultation();
      switch (result.status) {
        case 'cancelled':
          // Walking away is a decision, not a failure — back to where the Dealer was, silently.
          setState({ phase: 'idle' });
          break;
        case 'ready':
          setState({
            phase: 'ready',
            sessionId: result.sessionId,
            imageDataUrl: result.imageDataUrl,
          });
          break;
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
  }, []);

  const discard = useCallback(async () => {
    if (state.phase === 'ready' && state.sessionId) {
      try {
        const response = await window.spectrapaint.request({
          path: `/sessions/${state.sessionId}`,
          method: 'DELETE',
        });
        if (!response.ok) {
          console.error('[consultation] could not end the session:', response.body);
        }
      } catch (error) {
        // Same rule as start(): the bridge rejecting must not strand the Dealer. Putting the photo
        // down is a local decision, so it succeeds here even when the service never hears about it.
        console.error('[consultation] could not end the session:', error);
      }
    }
    setState({ phase: 'idle' });
  }, [state]);

  return { state, start, discard };
}
