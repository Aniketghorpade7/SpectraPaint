import type { WallPlaneOverlay } from '../../../desktop/src/bridge-types';

/**
 * Which wall the next Shade paints, and what that means on the wire (issue #7).
 *
 * A room with one wall plane has no decision to make, and a room with two has one the Dealer makes
 * with a single extra tap: tap a wall, then tap a Shade, and only that wall changes. Tapping a Shade
 * without choosing a wall first paints them all, which is the common case and stays at zero extra
 * taps — the budget is three (docs/ui-guidelines.md).
 *
 * The state lives here as pure functions because it is the kind of logic neither test seam reaches:
 * the service knows nothing about which wall is selected, and the render engine sees only the
 * assignments map that comes out the far end (docs/conventions.md §6).
 */

/** What the next tapped Shade will be applied to: every wall, or one of them. */
export type PaintTarget = { kind: 'all' } | { kind: 'plane'; planeId: string };

export const ALL_WALLS: PaintTarget = { kind: 'all' };

/** The Shade Code each wall is currently carrying, by Wall Plane id. Absent means not yet painted. */
export type Assignments = Record<string, string>;

export function isTargeted(target: PaintTarget, planeId: string): boolean {
  return target.kind === 'plane' && target.planeId === planeId;
}

/**
 * Tapping a wall selects it; tapping the selected wall again goes back to painting every wall.
 *
 * A toggle rather than a separate "all walls" action, because deselecting is the same gesture as
 * selecting and a confirmation step is a tap we cannot afford (docs/ui-guidelines.md).
 */
export function toggleTarget(target: PaintTarget, planeId: string): PaintTarget {
  return isTargeted(target, planeId) ? ALL_WALLS : { kind: 'plane', planeId };
}

/**
 * The assignments after a Shade is tapped.
 *
 * Painting every wall replaces the map outright, so a room being tried in one colour does not carry
 * a stale Accent Wall underneath it. Painting one wall keeps what the others already have — that is
 * what makes two Shades at once possible at all.
 */
export function nextAssignments(
  previous: Assignments,
  target: PaintTarget,
  shadeCode: string,
  planes: WallPlaneOverlay[],
): Assignments {
  if (target.kind === 'all') {
    return Object.fromEntries(planes.map((plane) => [plane.planeId, shadeCode]));
  }
  return { ...previous, [target.planeId]: shadeCode };
}

/**
 * What to send the service: a bare Shade Code, or a Shade per wall.
 *
 * A single code only when *every plane the photo has* is getting the same one, because the bridge
 * then discovers the plane ids itself and a photo whose walls were re-split between two taps
 * cannot produce a request naming a plane that no longer exists. A map otherwise — either the
 * walls genuinely differ, or only some of them have a Shade yet — and only for walls the Dealer
 * has actually chosen a Shade for, so an unpainted wall stays the colour it is in the photograph
 * rather than being quietly given somebody else's Shade.
 *
 * `planes` is what makes that distinction correct rather than accidental: checking only whether
 * every *assigned* code matches is trivially true the moment exactly one wall has been painted so
 * far — a one-entry map has nothing to disagree with itself — which used to collapse "paint just
 * this one wall" into a bare Shade Code the bridge would apply to every plane in the photo.
 * Collapsing to a bare code now requires the assignment map to actually cover every plane, not
 * merely agree with itself.
 */
export function renderPayload(
  assignments: Assignments,
  planes: WallPlaneOverlay[],
): string | Assignments {
  const codes = Object.values(assignments);
  const [first] = codes;
  if (first === undefined) return {};

  const coversEveryPlane = planes.length > 0 && Object.keys(assignments).length === planes.length;
  const everyWallTheSame = coversEveryPlane && codes.every((code) => code === first);
  return everyWallTheSame ? first : assignments;
}

/**
 * What to call a wall in front of a Dealer.
 *
 * Position, because that is how somebody standing in the room would point at it, and the planes
 * arrive ordered left to right. "Wall Plane" is the word for the code and the glossary, not for a
 * caption over a photograph. A ceiling is always called "the ceiling" regardless of position.
 */
export function describeWall(index: number, total: number): string {
  if (total <= 1) return 'the wall';
  if (total === 2) return index === 0 ? 'the left wall' : 'the right wall';
  if (total === 3) {
    return ['the left wall', 'the middle wall', 'the right wall'][index] ?? `wall ${index + 1}`;
  }
  return `wall ${index + 1}`;
}

export function describePlane(plane: WallPlaneOverlay, index: number, total: number): string {
  if (plane.surface === 'ceiling') return 'the ceiling';
  return describeWall(index, total);
}

/** Walls only — a ceiling is its own surface and never takes a wall's positional name (issue #39). */
function wallsOf(planes: WallPlaneOverlay[]): WallPlaneOverlay[] {
  return planes.filter((plane) => plane.surface !== 'ceiling');
}

/** The caption above the photo: what the next Shade tap will do. */
export function describeTarget(target: PaintTarget, planes: WallPlaneOverlay[]): string {
  if (planes.length <= 1) return '';
  if (target.kind === 'all') {
    return 'Tap a Shade to paint every wall, or tap one wall to paint it on its own.';
  }
  // Positional names count walls only (issue #39): a ceiling in the list must not turn "the wall"
  // into "the left wall", nor leave the wall sounding like it sits beside another wall. The target
  // itself is looked up across every plane — a chosen ceiling names itself as "the ceiling".
  const plane = planes.find((candidate) => candidate.planeId === target.planeId);
  if (!plane) return '';
  const walls = wallsOf(planes);
  return `Tap a Shade to paint ${describePlane(plane, walls.indexOf(plane), walls.length)}. Tap it again for all of them.`;
}
