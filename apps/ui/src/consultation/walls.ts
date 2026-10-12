import type { WallPlaneOverlay } from '../../../desktop/src/bridge-types';
import type { CorrectionTool } from './corrections';

/**
 * What the Dealer is shown about the walls SpectraPaint found (ticket #6).
 *
 * A pure reducer, like render.ts, so the rules are testable without a DOM
 * (docs/design-decisions.md §9d).
 *
 * Two rules are worth stating, because both are decisions rather than mechanics.
 *
 * **The overlay is neutral, never coloured, and never a selection mark.** ui-guidelines.md is
 * unambiguous: nothing saturated may sit near the render, because simultaneous contrast genuinely
 * shifts how the wall's colour reads. The usual way to draw a segmentation mask — a bright
 * translucent blue — is the one thing this application must not do. So every detected wall gets the
 * same weak white wash, and the *chosen* wall is marked by an outline (``matteOutline``, drawn by
 * ``WallOutlineCanvas``) and its inverted chip — never by a stronger wash, which would make the
 * one wall the Customer is about to judge paler than the others (issue #49). The outline is neutral
 * grey for the same reason: a saturated colour beside a wall being judged for its colour is exactly
 * what it forbids.
 *
 * **It hides itself while a repaint is on screen, whatever is armed.** The overlay exists to answer
 * "did it find the right wall?", which is a question the Dealer asks before choosing a Shade. Once
 * there is a repaint to look at, the same wash sits between the Customer and the colour they are
 * judging. Hiding it then is not a tidiness preference; leaving it up would corrupt the comparison
 * the whole product exists to support. This holds even when a correction tool is armed — the armed
 * state alone used to force the overlay back over the render, where the tool buttons (hidden while
 * a render shows) gave the Dealer no way to disarm it (issue #49). Tapping a Shade now also
 * disarms the tool, so the two agree; ``overlayVisible`` stays the hard rule either way.
 */

export interface WallsState {
  /** Every Paintable Plane found (walls and at most one ceiling), in the service's order. Can be
   * empty since ticket #10: automatic detection finding nothing at all is answered, not refused.
   * Each plane carries its ``surface`` (wall | ceiling) — the ceiling, when present, is an
   * independently-colourable surface with its own base colour and light map, never grouped with a
   * wall's (CONTEXT.md Ceiling Plane). */
  planes: WallPlaneOverlay[];
  /** Whether the Dealer wants the overlay shown at all. */
  wanted: boolean;
  /**
   * Why there is nothing more to see, in plain language, when that is worth saying — either the
   * overlay itself could not be fetched, or (ticket #10) automatic detection genuinely found no
   * wall. Never shown as an error state: a photo with nothing to outline is still a photo that
   * can be repainted, once the Dealer taps a wall in through the correction surface. From ticket
   * #39 the same note covers a photo with no ceiling — Add Ceiling is then the way forward.
   */
  message?: string;
  /**
   * A warning about the photo itself, in plain language — dark, blurred or heavily clipped
   * (ticket #15) — unrelated to `message`: the wall can be found perfectly well in a poor photo.
   * Never shown as an error state, and never cleared by a correction, since it describes the photo
   * rather than the planes found in it.
   */
  qualityNote?: string;
  /** The prepared photo's own pixel dimensions — known even with zero planes, which is what lets
   * a tap be turned into a point in that space before any plane has ever been found (ticket #10's
   * Add tool, on a photo with nothing detected at all). 0 means not yet known. */
  photoWidth: number;
  photoHeight: number;
}

export const INITIAL_WALLS_STATE: WallsState = {
  planes: [],
  wanted: true,
  photoWidth: 0,
  photoHeight: 0,
};

export type WallsEvent =
  | {
      type: 'found';
      planes: WallPlaneOverlay[];
      note: string | null;
      qualityNote?: string | null;
      photoWidth: number;
      photoHeight: number;
    }
  | { type: 'unavailable'; message: string }
  | { type: 'toggle' }
  | { type: 'cleared' };

export function applyWallsEvent(state: WallsState, event: WallsEvent): WallsState {
  switch (event.type) {
    case 'found':
      return {
        planes: event.planes,
        wanted: state.wanted,
        message: event.note ?? undefined,
        qualityNote: event.qualityNote ?? undefined,
        photoWidth: event.photoWidth,
        photoHeight: event.photoHeight,
      };
    case 'unavailable':
      return { ...state, planes: [], message: event.message };
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
 * ``showingRender`` and ``armedTool`` are passed in rather than stored, because they belong to the
 * render's and the correction surface's state and duplicating them here would mean two answers to
 * the same questions.
 *
 * The rule the signature exists to pin (issue #49): **never true while a repaint is showing**, for
 * every armed tool and none — the armed tool's old override is what put a wash over the painted
 * render with no way to dismiss it. With no render showing, a tool armed shows the overlay by
 * itself (correcting walls that are not visible is not a thing a Dealer can do — ticket #10);
 * otherwise it is the Dealer's own show/hide choice over a photo that has planes.
 */
export function overlayVisible(
  state: WallsState,
  showingRender: boolean,
  armedTool: CorrectionTool | null = null,
): boolean {
  if (showingRender) return false;
  if (armedTool !== null) return true;
  return state.wanted && state.planes.length > 0;
}

/**
 * The pixels of an Alpha Matte, as ``ImageData`` carries them — declared structurally rather than
 * as the DOM's ``ImageData`` so the pure helper below stays testable in vitest's node environment,
 * where no ``ImageData`` constructor exists (docs/conventions.md §6: pure functions, testable
 * without a DOM). A real ``ImageData`` satisfies it as-is.
 */
export interface MatteImage {
  readonly width: number;
  readonly height: number;
  /** RGBA, 4 bytes per pixel, row-major — exactly ``ImageData``'s layout. */
  readonly data: Uint8ClampedArray;
}

/**
 * Where the matte says "wall" — its grey level, thresholded. The Alpha Matte is served as an 8-bit
 * mode-L greyscale PNG (sessions.py ``_encode_matte``): decoded, the coverage sits in every RGB
 * channel with alpha opaque — the very level the overlay's ``mask-mode: luminance`` consumes. A
 * pixel is *of the wall* when that level says at least half-covered; 128 is the halfway point.
 * (Thresholding the *alpha* byte instead would read 255 everywhere and see one wall covering the
 * whole photo — a real bug this outline shipped with for exactly one headless-Chrome run.)
 */
const MATTE_INSIDE_THRESHOLD = 128;

/**
 * The wall's own edge, as an image the caller can colour: pixels of the matte that lie within
 * ``width`` pixels of its boundary, opaque white; everything else transparent.
 *
 * Pure, so the ring the chosen-wall outline draws is testable without a DOM (issue #49). "Inside"
 * is the threshold above; "within ``width`` pixels" is measured as the distance to the nearest
 * outside pixel along the 4-neighbourhood (an exact two-pass L1 distance transform), which is what
 * makes the ring closed — a boundary pixel always has an outside 4-neighbour, so no matte edge ever
 * shows a gap. Pixels past the photo's border are *not* outside: a wall running off the edge of the
 * photo has no edge there, and outlining the photo's frame instead would draw a rectangle around
 * the room.
 */
export function matteOutline(matte: MatteImage, width: number): MatteImage {
  const { width: w, height: h, data } = matte;
  const size = w * h;
  const empty = (): MatteImage => ({ width: w, height: h, data: new Uint8ClampedArray(size * 4) });
  if (width < 1 || w < 1 || h < 1) return empty();

  const inside = new Uint8Array(size);
  for (let i = 0; i < size; i++) {
    // The matte is greyscale by contract (mode L), so one channel *is* the level. An absent byte
    // would read as no coverage; the index is always in bounds, so the fallback only satisfies the
    // indexed-access rule.
    const level = data[i * 4] ?? 0;
    inside[i] = level >= MATTE_INSIDE_THRESHOLD ? 1 : 0;
  }

  // Distance to the nearest outside pixel, capped at `width + 1` — everything beyond that is not
  // on the outline, so exact values past the cap are never read. The two passes sweep the whole
  // grid once each way, so the cost is per-pixel regardless of `width`.
  const unreachable = width + 1;
  const dist = new Uint16Array(size);
  for (let i = 0; i < size; i++) dist[i] = inside[i] ? unreachable : 0;
  // Reads of `dist` never leave the grid — the coordinate guards below prove it — and a value that
  // were somehow absent would mean "no outside pixel in reach", which is what `unreachable`
  // already means, so it is the honest fallback rather than a type-level shim.
  const distanceAt = (index: number): number => dist[index] ?? unreachable;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const current = distanceAt(i);
      if (current === 0) continue;
      let d = current;
      if (x > 0) d = Math.min(d, distanceAt(i - 1) + 1);
      if (y > 0) d = Math.min(d, distanceAt(i - w) + 1);
      dist[i] = d;
    }
  }
  for (let y = h - 1; y >= 0; y--) {
    for (let x = w - 1; x >= 0; x--) {
      const i = y * w + x;
      const current = distanceAt(i);
      if (current === 0) continue;
      let d = current;
      if (x < w - 1) d = Math.min(d, distanceAt(i + 1) + 1);
      if (y < h - 1) d = Math.min(d, distanceAt(i + w) + 1);
      dist[i] = d;
    }
  }

  const out = empty().data;
  for (let i = 0; i < size; i++) {
    if (inside[i] === 1 && distanceAt(i) <= width) {
      const o = i * 4;
      out[o] = 255;
      out[o + 1] = 255;
      out[o + 2] = 255;
      out[o + 3] = 255;
    }
  }
  return { width: w, height: h, data: out };
}
