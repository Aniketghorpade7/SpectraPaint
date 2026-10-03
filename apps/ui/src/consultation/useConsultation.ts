import { useCallback, useEffect, useRef, useState } from 'react';

import type {
  ExportResult,
  MenuCommand,
  ProgressStreamEvent,
  RenderResult,
  WallPlaneOverlay,
  WallsResult,
} from '../../../desktop/src/bridge-types';
import { applyExportEvent, INITIAL_EXPORT_STATE, type ExportState } from './export';
import {
  type PaintHistory,
  type PaintSnapshot,
  INITIAL_PAINT_HISTORY,
  redo,
  record,
  undo,
} from './history';
import { applyRenderEvent, INITIAL_RENDER_STATE, type RenderState } from './render';
import {
  ALL_WALLS,
  type Assignments,
  nextAssignments,
  type PaintTarget,
  renderPayload,
  toggleTarget,
} from './accent';
import {
  effectiveArmedTool,
  toggleArmedTool,
  type CorrectionTool,
  type TapPoint,
} from './corrections';
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
  /**
   * Plain language, set when the prepared photo could not be fetched (issue #49) and the raw upload
   * is still what is on screen. Never an error screen: the photo is still usable, and the note says
   * what to try.
   */
  photoNotice?: string;
}

export type RenderMode = 'realistic' | 'true_colour';

export interface Consultation {
  state: ConsultationState;
  start: () => Promise<string | null>;
  discard: () => void;
  /** Put a reopened Consultation on screen: already prepared, nothing left to wait for (issue #11). */
  adopt: (sessionId: string, imageDataUrl: string) => void;
  /** The repaint's state on the Consultation surface. See render.ts for the reducer. */
  render: RenderState;
  /** Repaint in a Shade Code: every wall, or just the selected one. Safe to call with the photo on
   * screen. */
  applyShade: (shadeCode: string) => void;
  /** Which wall the next Shade paints, and the Shade each wall carries (ticket #7). */
  paint: { target: PaintTarget; assignments: Assignments };
  /** Choose the wall the next Shade paints; the same wall again goes back to painting them all. */
  selectWall: (planeId: string) => void;
  /** Show the original photo or the repaint after a successful render. */
  toggleBeforeAfter: () => void;
  /** Leave a failed repaint behind and keep the original photo on screen. */
  dismissRender: () => void;
  /** The Wall Planes found in the photo, and whether their outline is on screen (ticket #6). */
  walls: WallsState;
  /** Show or hide the detected-wall overlay. */
  toggleWalls: () => void;
  /** Realistic tints by room light; True Colour shows the chip colour. Default realistic. */
  renderMode: RenderMode;
  /** Switch between Realistic and True Colour; repaints the current Shade if one is on screen. */
  toggleRenderMode: () => void;
  /** Which correction tool is armed right now (ticket #10) — Add auto-arms when the photo has no
   * Wall Plane at all, since there is nothing else to do. The next tap on the photo performs it. */
  armedTool: CorrectionTool | null;
  /** Arm a correction tool; arming the already-armed tool disarms it — the same toggle
   * toggleWalls/toggleTarget/toggleRenderMode already use, not a new interaction to learn. */
  armTool: (tool: CorrectionTool) => void;
  /** Perform the armed tool's correction at a tapped point, then disarm. A no-op with nothing
   * armed or the photo not ready — safe to call from a click handler unconditionally. */
  correctWallsAt: (point: TapPoint) => void;
  /** Undo the last paint change — a Shade or a wall choice — within this open Consultation
   * (issue #50). Undoing to the Consultation's start returns the original photo to the screen.
   * A no-op when there is nothing to undo. Wall corrections are deliberately not undoable. */
  undoPaint: () => void;
  /** Redo the last undone paint change (issue #50). A no-op when there is nothing to redo. */
  redoPaint: () => void;
  /** Whether undo has a paint change to restore (issue #50) — what the menu items report. */
  canUndo: boolean;
  /** Whether redo has an undone paint change to restore (issue #50). */
  canRedo: boolean;
  /** The service's own message when the last correction tap was refused, safe to show as-is.
   * Cleared on the next tool armed or the next successful correction. The existing walls are
   * never touched by a refusal — this is a note beside them, never a dead end. */
  correctionMessage?: string;
  /** The failure code behind `correctionMessage`, when there is one. `session_not_found` is the
   * one the surface reacts to differently — see `render.code` (issue #15). */
  correctionCode?: string;
  /** Full-resolution JPEG export via the OS share sheet (issue #12) — non-blocking. */
  exportState: ExportState;
  exportRender: () => void;
  dismissExport: () => void;
}

const PREPARED_PHOTO_FAILED_MESSAGE =
  'This photo could not be shown the way SpectraPaint prepared it, so the walls found may look out of place. Try loading the photo again.';

/** The fallback shown before the stream's first message arrives. */
const LOADING_MESSAGE = 'Loading your photo…';

const PREP_FAILED_MESSAGE = 'The photo could not be prepared. Please try another photo.';

const RENDER_FAILED_MESSAGE = 'The wall could not be repainted. Please try another Shade.';

const WALLS_UNAVAILABLE_MESSAGE =
  'The walls in this photo could not be shown. The photo can still be repainted.';

const CORRECTION_FAILED_MESSAGE = 'That could not be done. The walls stay as they were.';

/**
 * Shown instead of the service's own `session_not_found` message (issue #15).
 *
 * A sidecar restart wipes the service's in-memory sessions, but never the Consultation itself —
 * its photo and Wall Planes were already saved before this could happen (issue #11's auto-save).
 * The backend's own wording, "start a new one," is technically true but sends the Dealer to lose
 * work that reopening would recover intact; naming the actual recovery here is what keeps this
 * from being a dead end that quietly fails every retry instead of a visibly working one.
 */
export const MESSAGE_SESSION_LOST =
  'SpectraPaint had to restart. Please reopen this consultation from Bundles to continue — ' +
  'nothing has been lost.';

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

/**
 * What the prepared photo's arrival does to the state, as a pure function so it is testable without
 * a DOM (docs/design-decisions.md §9d).
 *
 * Success swaps the raw upload for the prepared pixels. Failure keeps the placeholder but says so
 * (``photoNotice``) — logging alone left an oriented photo misaligned with nothing on screen to
 * tell the Dealer why. Either way only the session that asked is touched: a discard, or another
 * photo chosen while the fetch was in flight, must not be resurrected or annotated.
 */
export function applyPreparedPhoto(
  previous: ConsultationState,
  sessionId: string,
  prepared: string | null,
): ConsultationState {
  if (previous.phase !== 'ready' || previous.sessionId !== sessionId) return previous;
  if (prepared === null) return { ...previous, photoNotice: PREPARED_PHOTO_FAILED_MESSAGE };
  const next: ConsultationState = { ...previous, imageDataUrl: prepared };
  delete next.photoNotice;
  return next;
}

/** What tapping a Shade records, before the request goes out. */
export interface ShadeTapState {
  /** Always ``null``: the tap disarms whatever correction tool was armed. */
  explicitTool: CorrectionTool | null;
  render: RenderState;
  assignments: Assignments;
}

/**
 * What tapping a Shade means to the Consultation's state before the request goes out, as a pure
 * function so the tap's meaning is testable without a DOM (docs/design-decisions.md §9d) — the
 * same reasoning as `applyProgressEvent` above.
 *
 * Three things change, none of them reading another's new value:
 *
 * - **Every armed correction tool is disarmed (issue #49).** Tapping a Shade is the Dealer moving
 *   on from correcting the walls to judging the paint. A tool left armed would hold the correction
 *   surface over the arriving repaint — and the tool buttons are hidden while a render shows, so
 *   the Dealer could not even disarm it except by tapping the photo. `overlayVisible` (walls.ts)
 *   refuses to draw anything over a render regardless; this is what stops the *state* disagreeing
 *   with the screen underneath it.
 * - The assignment map is updated for the tapped Shade (accent.ts `nextAssignments`): every wall,
 *   or just the selected one, with the others keeping the Shades they already have.
 * - The render state marks the request (render.ts `applyRenderEvent`).
 */
export function beginShadeTap(
  explicitTool: CorrectionTool | null,
  render: RenderState,
  assignments: Assignments,
  target: PaintTarget,
  planes: WallPlaneOverlay[],
  shadeCode: string,
): ShadeTapState {
  return {
    explicitTool: null,
    render: applyRenderEvent(render, { type: 'requested', shadeCode }),
    assignments: nextAssignments(assignments, target, shadeCode, planes),
  };
}

/**
 * The Shade Code a restored snapshot repaints in.
 *
 * Undo and redo restore *state* — target and assignments — and then repaint through the normal
 * path. The render reducer pins its replies to the Shade Code of the request, and undo/redo are
 * not Shade taps, so the snapshot's own most recent code stands in: it is the Shade the restored
 * paint actually carries, and it keeps a stale reply from a superseded request from overwriting
 * the restored state (issue #50). An empty snapshot repaints nothing, so its code is never asked
 * for — the fallback only keeps the type honest.
 */
export function shadeCodeOf(snapshot: PaintSnapshot): string {
  const codes = Object.values(snapshot.assignments);
  return codes[codes.length - 1] ?? 'repaint';
}

/** What the screen has to do to show a restored snapshot (issue #50). */
export type RestorePlan = 'original-photo' | 'repaint' | 'keep';

/**
 * What restoring `restore` over `now` means for what is on screen, for undo and redo alike.
 *
 * - **`original-photo`** when the restored paint carries no Shade: nothing is painted, so the
 *   render state is dropped and the original photo returns, rather than an empty repaint being
 *   requested (the service answers an empty assignment map with `422 malformed_request`). This holds
 *   in *both* directions — redo can land on an empty snapshot too, after a wall choice made before
 *   any Shade was undone and redone.
 * - **`keep`** when only the wall choice differs: the Shades each wall carries are what the render
 *   shows, so what is on screen is already right and a repaint would be a request for the same
 *   picture.
 * - **`repaint`** otherwise.
 */
export function restorePlan(now: PaintSnapshot, restore: PaintSnapshot): RestorePlan {
  const restored = Object.entries(restore.assignments);
  if (restored.length === 0) return 'original-photo';
  const current = now.assignments;
  const unchanged =
    restored.length === Object.keys(current).length &&
    restored.every(([planeId, code]) => current[planeId] === code);
  return unchanged ? 'keep' : 'repaint';
}

export function useConsultation(): Consultation {
  const [state, setState] = useState<ConsultationState>({ phase: 'idle' });
  const [render, setRender] = useState<RenderState>(INITIAL_RENDER_STATE);
  const [walls, setWalls] = useState<WallsState>(INITIAL_WALLS_STATE);
  const [renderMode, setRenderMode] = useState<RenderMode>('realistic');
  const [exportState, setExportState] = useState<ExportState>(INITIAL_EXPORT_STATE);
  // Which wall the next Shade paints, and what each wall is already carrying. Held here rather than
  // in the render state because it outlives a single repaint: an Accent Wall is built one wall at a
  // time, and the second tap has to know what the first one did (ticket #7).
  const [target, setTarget] = useState<PaintTarget>(ALL_WALLS);
  const [assignments, setAssignments] = useState<Assignments>({});
  // The paint history (issue #50): what target+assignments were before each Shade or wall choice.
  // Held as state rather than a ref so canUndo/canRedo re-derive — and reach the menu — on change.
  const [history, setHistory] = useState<PaintHistory>(INITIAL_PAINT_HISTORY);
  // What the Dealer explicitly armed, if anything — corrections.effectiveArmedTool is what turns
  // this into what is actually armed, so auto-arming Add on a zero-plane photo can never drift
  // out of sync with whether a plane exists (ticket #10, implementation-decisions.md #39).
  const [explicitTool, setExplicitTool] = useState<CorrectionTool | null>(null);
  const [correctionMessage, setCorrectionMessage] = useState<string | undefined>(undefined);
  const [correctionCode, setCorrectionCode] = useState<string | undefined>(undefined);
  const armedTool = effectiveArmedTool(explicitTool, walls.planes.length);
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
          ? {
              type: 'found',
              planes: result.planes,
              note: result.note,
              qualityNote: result.qualityNote,
              photoWidth: result.photoWidth,
              photoHeight: result.photoHeight,
            }
          : { type: 'unavailable', message: result.message },
      ),
    );
  }, []);

  // Once preparation is done, what is on screen becomes what was prepared (issue #49): the raw
  // upload is only ever a placeholder, because an oriented phone photo is displayed rotated by
  // Chromium — its EXIF tag honoured — while the prepared pixels already carry the orientation.
  // Showing the raw upload after `done` would put the mattes and the repaint on a different
  // rectangle than the one the Dealer sees. If the fetch fails, the placeholder stays, the
  // fault is logged rather than swallowed (docs/conventions.md §5), and the Dealer is told on screen.
  const showPreparedPhoto = useCallback(
    async (sessionId: string) => {
      let prepared: string | null = null;
      try {
        const result = await window.spectrapaint.preparedPhoto(sessionId);
        if (result.status === 'ready') {
          prepared = result.imageDataUrl;
        } else {
          console.error('[consultation] could not fetch the prepared photo:', result.message);
        }
      } catch (error) {
        console.error('[consultation] could not fetch the prepared photo:', error);
      }

      setState((previous) => applyPreparedPhoto(previous, sessionId, prepared));

      // The walls are fetched after the swap, so the overlay's pixel space (the mattes') is the one
      // on screen — not the raw upload's. One request either way: the service waits for preparation
      // rather than answering "not ready", so there is nothing to poll and nothing to retry.
      void loadWalls(sessionId);
    },
    [loadWalls],
  );

  const start = useCallback(async (): Promise<string | null> => {
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    setRender(INITIAL_RENDER_STATE);
    setWalls(INITIAL_WALLS_STATE);
    setExportState(INITIAL_EXPORT_STATE);
    setHistory(INITIAL_PAINT_HISTORY);
    setState({ phase: 'uploading', progressMessage: LOADING_MESSAGE });

    try {
      const result = await window.spectrapaint.createConsultation();
      switch (result.status) {
        case 'cancelled':
          // Walking away is a decision, not a failure — back to where the Dealer was, silently.
          setState({ phase: 'idle' });
          return null;
        case 'ready': {
          const { sessionId, imageDataUrl } = result;
          const unsubscribe = window.spectrapaint.onProgress(sessionId, (event) => {
            setState((previous) => applyProgressEvent(previous, event));
            if (event.phase === 'done') {
              unsubscribeRef.current?.();
              unsubscribeRef.current = null;
              // The prepared photo replaces the upload on screen, and the walls — known by the time
              // preparation says done — are fetched once it is in place (issue #49).
              void showPreparedPhoto(sessionId);
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
          return sessionId;
        }
        case 'failed':
          setState({ phase: 'failed', message: result.message });
          return null;
      }
    } catch (error) {
      // The bridge rejected without a result (not a service refusal). Never dead-end: the Dealer
      // must not sit on "Loading your photo…" with no way out.
      console.error('[consultation] could not start a consultation:', error);
      setState({
        phase: 'failed',
        message: 'The photo could not be loaded. Please try another photo.',
      });
      return null;
    }
  }, [endSession, showPreparedPhoto]);

  const discard = useCallback(() => {
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    if (state.phase === 'ready' && state.sessionId) {
      void endSession(state.sessionId);
    }
    setRender(INITIAL_RENDER_STATE);
    setWalls(INITIAL_WALLS_STATE);
    setExportState(INITIAL_EXPORT_STATE);
    setTarget(ALL_WALLS);
    setAssignments({});
    setHistory(INITIAL_PAINT_HISTORY);
    setRenderMode('realistic');
    setExplicitTool(null);
    setCorrectionMessage(undefined);
    setCorrectionCode(undefined);
    setState({ phase: 'idle' });
  }, [state, endSession]);

  const adopt = useCallback(
    (sessionId: string, imageDataUrl: string) => {
      // A reopened Consultation arrives already prepared on the service: no stream to follow, no
      // waiting. The walls are asked for once, exactly as a freshly prepared photo would (issue #11).
      // History starts empty too (issue #50): what the Customer saw last time is what reopening
      // shows — an editable past is not something a saved Consultation carries.
      setRender(INITIAL_RENDER_STATE);
      setWalls(INITIAL_WALLS_STATE);
      setExportState(INITIAL_EXPORT_STATE);
      setHistory(INITIAL_PAINT_HISTORY);
      setTarget(ALL_WALLS);
      setAssignments({});
      setState({ phase: 'ready', sessionId, imageDataUrl });
      void loadWalls(sessionId);
    },
    [loadWalls],
  );

  /**
   * Ask the service to repaint the walls carrying `assignments`, and run the reply through the
   * render reducer (issue #50). One helper, three callers — applyShade, the render-mode switch and
   * undo/redo — so the request/reply/failed path cannot drift between them. `shadeCode` is what the
   * render reducer pins the reply to: the last requested Shade wins, so a stale reply cannot
   * overwrite a newer one (issue #3).
   */
  const repaint = useCallback(
    // `mode` is explicit because toggleRenderMode repaints in the mode it is *switching to* — state
    // has not caught up within the same event, so the caller must say which mode it means.
    async (nextAssignments: Assignments, shadeCode: string, mode: RenderMode = renderMode) => {
      if (state.phase !== 'ready' || !state.sessionId) return;
      const sessionId = state.sessionId;
      setRender((previous) => applyRenderEvent(previous, { type: 'requested', shadeCode }));

      const payload = renderPayload(nextAssignments, walls.planes);

      let result: RenderResult;
      try {
        result = await window.spectrapaint.render(sessionId, payload, mode);
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
            // session_not_found means a sidecar restart, not that this Shade failed (issue #15);
            // the service's own "start a new one" wording would send the Dealer to lose work that
            // reopening recovers intact.
            message: result.code === 'session_not_found' ? MESSAGE_SESSION_LOST : result.message,
          }),
        );
      }
    },
    [state.phase, state.sessionId, walls.planes, renderMode],
  );

  const applyShade = useCallback(
    (shadeCode: string) => {
      if (state.phase !== 'ready' || !state.sessionId) return;

      // Record what the paint was *before* this tap, so undo can restore it (issue #50). The
      // snapshot pairs the wall choice with the assignments: undoing a targeted Shade has to give
      // back the wall that was chosen too, or the next tap would land somewhere else.
      setHistory((previous) => record(previous, { target, assignments }));

      // What this tap means — the armed tool disarmed (issue #49), the assignments updated, the
      // render marked — is computed before the request goes out, so the request and the state it
      // records cannot disagree. `repaint` then makes the request.
      const tap = beginShadeTap(explicitTool, render, assignments, target, walls.planes, shadeCode);
      setExplicitTool(tap.explicitTool);
      setRender(tap.render);
      setAssignments(tap.assignments);
      void repaint(tap.assignments, shadeCode);
    },
    [
      state.phase,
      state.sessionId,
      explicitTool,
      render,
      assignments,
      target,
      walls.planes,
      repaint,
    ],
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

  const selectWall = useCallback(
    (planeId: string) => {
      // The wall choice is undoable too (issue #50): the snapshot pairs it with the assignments so
      // undo hands back both, and the next undo step after a Shade reaches the choice that made it.
      setHistory((previous) => record(previous, { target, assignments }));
      setTarget((previous) => toggleTarget(previous, planeId));
    },
    [target, assignments],
  );

  /**
   * Put a snapshot back on screen, for undo and redo alike (issue #50). The state is restored
   * first; what has to be *asked of the service* is `restorePlan`'s call — a repaint only when the
   * Shades on the walls changed, never replayed from a stored image, which is how a snapshot naming
   * a live plane stays honest.
   */
  const restoreSnapshot = useCallback(
    (now: PaintSnapshot, restore: PaintSnapshot) => {
      setTarget(restore.target);
      setAssignments(restore.assignments);
      switch (restorePlan(now, restore)) {
        case 'original-photo':
          // Nothing painted: back to the photo the Customer's room was judged against.
          setRender(INITIAL_RENDER_STATE);
          break;
        case 'repaint':
          void repaint(restore.assignments, shadeCodeOf(restore));
          break;
        case 'keep':
          break;
      }
    },
    [repaint],
  );

  /**
   * Undo the last paint change — a Shade or a wall choice — within this open Consultation
   * (issue #50). Restoring a snapshot with empty `assignments` is the Consultation's own start:
   * nothing painted yet, so the render state is dropped and the original photo returns to the
   * screen rather than an empty repaint being requested. The restored state is *asked for* as a
   * normal repaint, exactly as the same paint would be reached by tapping — never replayed from a
   * stored image, which is how a snapshot naming a live plane stays honest.
   */
  const undoPaint = useCallback(() => {
    if (state.phase !== 'ready' || !state.sessionId) return;
    const now: PaintSnapshot = { target, assignments };
    const step = undo(history, now);
    if (!step) return;

    setHistory(step.history);
    restoreSnapshot(now, step.restore);
  }, [state.phase, state.sessionId, target, assignments, history, restoreSnapshot]);

  /** Redo the last undone paint change (issue #50) — the mirror of undoPaint. */
  const redoPaint = useCallback(() => {
    if (state.phase !== 'ready' || !state.sessionId) return;
    const now: PaintSnapshot = { target, assignments };
    const step = redo(history, now);
    if (!step) return;

    setHistory(step.history);
    restoreSnapshot(now, step.restore);
  }, [state.phase, state.sessionId, target, assignments, history, restoreSnapshot]);

  const toggleRenderMode = useCallback(() => {
    const next: RenderMode = renderMode === 'realistic' ? 'true_colour' : 'realistic';
    setRenderMode(next);
    // If a Shade is already on screen, repaint it in the new mode so the Dealer sees the
    // difference without tapping again (CONTEXT.md: Realistic vs True Colour). The same repaint
    // path applyShade uses — only the mode differs, so the reply handling cannot drift.
    if (state.phase === 'ready' && state.sessionId && Object.keys(assignments).length > 0) {
      const shadeForState = Object.values(assignments)[0] ?? 'repaint';
      void repaint(assignments, shadeForState, next);
    }
  }, [renderMode, state.phase, state.sessionId, assignments, repaint]);

  const armTool = useCallback((tool: CorrectionTool) => {
    setExplicitTool((previous) => toggleArmedTool(previous, tool));
    setCorrectionMessage(undefined);
    setCorrectionCode(undefined);
  }, []);

  const correctWallsAt = useCallback(
    (point: TapPoint) => {
      if (armedTool === null || state.phase !== 'ready' || !state.sessionId) return;
      const tool = armedTool;
      const sessionId = state.sessionId;
      // One tap, one correction: disarm immediately rather than staying in a mode, matching
      // ui-guidelines.md's "act, do not confirm" rule for the rest of this surface.
      setExplicitTool(null);
      setCorrectionMessage(undefined);
      setCorrectionCode(undefined);

      void (async () => {
        let result: WallsResult;
        try {
          result = await window.spectrapaint.correctWalls(sessionId, tool, point);
        } catch (error) {
          // The bridge rejected without a result (not a service refusal). Never dead-end: the
          // existing walls are untouched, so this is a note beside them, not a lost photo.
          console.error('[consultation] could not correct the walls:', error);
          setCorrectionMessage(CORRECTION_FAILED_MESSAGE);
          return;
        }

        if (result.status === 'ready') {
          setWalls((previous) =>
            applyWallsEvent(previous, {
              type: 'found',
              planes: result.planes,
              note: result.note,
              qualityNote: result.qualityNote,
              photoWidth: result.photoWidth,
              photoHeight: result.photoHeight,
            }),
          );
          // A split or merge can retire a plane id the Dealer had targeted or already assigned a
          // Shade to; fall back to painting every wall and drop the stale assignment rather than
          // reference a plane that no longer exists (implementation-decisions.md #40). The paint
          // history goes with them (issue #50): a snapshot naming a retired plane cannot be
          // replayed honestly, so no correction is undoable — the Dealer simply re-runs one.
          setHistory(INITIAL_PAINT_HISTORY);
          const ids = new Set(result.planes.map((plane) => plane.planeId));
          setTarget((previous) =>
            previous.kind === 'plane' && !ids.has(previous.planeId) ? ALL_WALLS : previous,
          );
          setAssignments((previous) =>
            Object.fromEntries(Object.entries(previous).filter(([planeId]) => ids.has(planeId))),
          );
        } else {
          // The service's own message names the right tool instead — "already part of a wall,
          // try Split" — and the existing walls stay exactly as they were. Except for
          // session_not_found (issue #15): the service's own wording ("start a new one") would
          // send the Dealer to lose work that reopening recovers intact, so that one code gets a
          // message of this surface's own.
          setCorrectionMessage(
            result.code === 'session_not_found' ? MESSAGE_SESSION_LOST : result.message,
          );
          setCorrectionCode(result.code);
        }
      })();
    },
    [armedTool, state.phase, state.sessionId],
  );

  const exportRender = useCallback(() => {
    if (state.phase !== 'ready' || !state.sessionId || Object.keys(assignments).length === 0)
      return;
    setExportState((previous) => applyExportEvent(previous, { type: 'requested' }));
    const payload = renderPayload(assignments, walls.planes);
    void window.spectrapaint
      .export(state.sessionId, payload, renderMode)
      .then((result: ExportResult) => {
        if (result.status === 'ready') {
          setExportState((previous) =>
            applyExportEvent(previous, {
              type: 'ready',
              filename: result.filename,
              filePath: result.filePath,
            }),
          );
        } else if (result.status === 'cancelled') {
          setExportState((previous) => applyExportEvent(previous, { type: 'cancelled' }));
        } else {
          setExportState((previous) =>
            applyExportEvent(previous, {
              type: 'failed',
              code: result.code,
              message: result.message,
            }),
          );
        }
      })
      .catch((error: unknown) => {
        console.error('[consultation] export failed:', error);
        setExportState((previous) =>
          applyExportEvent(previous, {
            type: 'failed',
            code: 'export_failed',
            message: 'The export could not be completed. Please try again.',
          }),
        );
      });
  }, [state.phase, state.sessionId, assignments, walls.planes, renderMode]);

  const dismissExport = useCallback(() => {
    setExportState((previous) => applyExportEvent(previous, { type: 'dismiss' }));
  }, []);

  // The menu items enable and disable with the Consultation's history (issue #50) — published
  // whenever it changes, so Undo/Redo never grey-lie about what they would do.
  const canUndo = history.past.length > 0;
  const canRedo = history.future.length > 0;
  useEffect(() => {
    window.spectrapaint.setMenuState({ canUndo, canRedo });
  }, [canUndo, canRedo]);

  // Menu commands arrive here (issue #50). Undo/Redo are paint commands — unless the Dealer is
  // editing text, when the browser's own undo for the focused field is what Ctrl+Z must do. A menu
  // accelerator fires before the page sees the key, so without this branch typing in the Catalogue
  // search box would undo a Shade instead of a letter.
  useEffect(() => {
    return window.spectrapaint.onMenuCommand((command: MenuCommand) => {
      const element = document.activeElement;
      const editing = element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement;
      if (editing) {
        document.execCommand(command);
        return;
      }
      if (command === 'undo') undoPaint();
      else redoPaint();
    });
  }, [undoPaint, redoPaint]);

  return {
    state,
    start,
    discard,
    adopt,
    render,
    applyShade,
    toggleBeforeAfter,
    dismissRender,
    walls,
    toggleWalls,
    paint: { target, assignments },
    selectWall,
    renderMode,
    toggleRenderMode,
    armedTool,
    armTool,
    correctWallsAt,
    correctionMessage,
    correctionCode,
    undoPaint,
    redoPaint,
    canUndo,
    canRedo,
    exportState,
    exportRender,
    dismissExport,
  };
}
