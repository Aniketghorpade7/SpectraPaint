"""Correcting the detected Wall Planes by tapping (ticket #10).

Three operations, one per tool the Dealer can arm on the Consultation surface — Add, Split, Merge —
each taking nothing but the point the Dealer tapped, in the prepared photo's own pixel space. This
mirrors implementation-decisions.md #40: the tapped point already carries the Dealer's intent (which
tool they armed), so nothing here asks the caller to also resolve *which* plane or *which* pair of
planes is meant — that geometry belongs here, next to the mattes it reads.

**Add** decodes a new plane from the tap through SAM 2, against features preparation already
encoded (or, for the one photo where it did not — difficulty 21 — a caller-supplied encode of its
own). **Split** and **Merge** need no model at all: a hard partition (segmentation/split.py) means
every Wall Plane's matte is already disjoint from every other's, so splitting is a plain array cut
and merging is a plain array sum. All three are therefore cheap enough to run on every tap without
re-running preparation — the criterion the ticket states outright.

Every refusal is a :class:`CorrectionRefused`, carrying the plain-language message the Dealer sees
(conventions.md §5) — never a stack trace, and never one message standing in for two different
things to do next.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from spectrapaint.imaging import dilate, erode
from spectrapaint.runtime.graphs import Graphs
from spectrapaint.segmentation.matte import (
    BAND_FRACTION,
    RefinerFeatures,
    decode_alpha,
    soften_boundary,
)
from spectrapaint.segmentation.prompts import single_point_prompt
from spectrapaint.segmentation.walls import (
    CEILING_PLANE_ID,
    MINIMUM_CEILING_FRACTION,
    MINIMUM_WALL_FRACTION,
    WallPlane,
)

# Where a matte is taken to be "confidently this pixel", for the point-in-plane and
# point-near-a-seam tests below. Matches matte.py's own _EDGE_LEVEL, kept as its own constant
# because point-testing a corrections tap and finding a matte's own edge band are different jobs
# that happen to agree on the same threshold.
_CORE_LEVEL = 0.5

# How close a tap must land to a seam to count as "there", as a fraction of the photo's shorter
# side. Generous enough for a fingertip (ui-guidelines.md's 44px minimum tap target, on the
# 1280px-long-side preview scale every photo is prepared at, is already ~3.4%) without being so
# wide that a tap well inside one plane's interior could ever read as "near" a seam it is not.
_SEAM_TAP_FRACTION = 0.02

MESSAGE_ALREADY_A_WALL = "That's already part of a wall. To split it into two, use Split instead."
MESSAGE_NOT_A_WALL = "That's not part of a wall yet. To add it, use Add instead."
MESSAGE_NOT_NEAR_A_SEAM = (
    "That doesn't look like where two walls meet. Please tap the line between two walls."
)
MESSAGE_NOTHING_FOUND_THERE = "No wall could be found there. Please try tapping somewhere else."
MESSAGE_TOO_CLOSE_TO_THE_EDGE = (
    "That's too close to the edge of the wall to split there. Please tap nearer the middle."
)


class CorrectionRefused(Exception):
    """A tap that does not satisfy its tool's precondition.

    One base class so the API layer can catch a single type regardless of which tool raised it —
    each subclass differs only in its plain-language ``message``, exactly like ``NoWallFound``
    carries its own (segmentation/walls.py). ``detail`` is for the log, never shown to the Dealer.
    """

    def __init__(self, message: str, detail: str) -> None:
        super().__init__(detail)
        self.message = message
        self.detail = detail


class PointAlreadyCovered(CorrectionRefused):
    """Add: the tapped point already belongs to an existing Wall Plane."""

    def __init__(self, detail: str) -> None:
        super().__init__(MESSAGE_ALREADY_A_WALL, detail)


class PointNotOnAPlane(CorrectionRefused):
    """Split: the tapped point does not belong to any existing Wall Plane."""

    def __init__(self, detail: str) -> None:
        super().__init__(MESSAGE_NOT_A_WALL, detail)


class PointNotNearASeam(CorrectionRefused):
    """Merge: the tapped point is not close to where two Wall Planes meet."""

    def __init__(self, detail: str) -> None:
        super().__init__(MESSAGE_NOT_NEAR_A_SEAM, detail)


class NothingFoundToAdd(CorrectionRefused):
    """Add: SAM 2 found essentially nothing wall-shaped at the tapped point."""

    def __init__(self, detail: str) -> None:
        super().__init__(MESSAGE_NOTHING_FOUND_THERE, detail)


class SplitTooCloseToTheEdge(CorrectionRefused):
    """Split: the cut would leave one side too small to be an offerable Wall Plane."""

    def __init__(self, detail: str) -> None:
        super().__init__(MESSAGE_TOO_CLOSE_TO_THE_EDGE, detail)


def _plane_containing(planes: tuple[WallPlane, ...], x: int, y: int) -> WallPlane | None:
    """Whichever plane's matte confidently covers this point, or None."""

    for plane in planes:
        if float(plane.alpha[y, x, 0]) >= _CORE_LEVEL:
            return plane
    return None


def check_addable(existing: tuple[WallPlane, ...], point: tuple[int, int]) -> None:
    """Raise :class:`PointAlreadyCovered` if the tap already lands on an existing plane.

    Split out of :func:`add_plane` so the route handler (api/planes.py) can run this before
    loading SAM 2 at all — Split's and Merge's own preconditions never touch a model either, and
    a tap that fails Add's precondition should not have to pay for an encoder it never needed.
    """

    x, y = point
    if _plane_containing(existing, x, y) is not None:
        raise PointAlreadyCovered(f"({x}, {y}) is already covered by an existing Wall Plane")


def _nearest_pair(
    planes: tuple[WallPlane, ...],
    x: int,
    y: int,
) -> tuple[WallPlane, WallPlane] | None:
    """The two planes touching a small window around the tap, or None unless exactly two do.

    A hard vertical cut (segmentation/split.py) means the seam between two planes is exactly
    where one's coverage ends and the other's begins, so a tap close to a real seam finds both
    planes confidently covering pixels within a small window of it; a tap in the middle of one
    plane, or on no plane at all, does not.
    """

    if len(planes) < 2:
        return None

    height, width = planes[0].alpha.shape[:2]
    radius = max(4, round(min(height, width) * _SEAM_TAP_FRACTION))
    top, bottom = max(0, y - radius), min(height, y + radius + 1)
    left, right = max(0, x - radius), min(width, x + radius + 1)

    touching = [
        plane
        for plane in planes
        if float(plane.alpha[top:bottom, left:right, 0].max(initial=0.0)) >= _CORE_LEVEL
    ]
    if len(touching) != 2:
        return None
    return touching[0], touching[1]


def _next_plane_id(existing: Iterable[str]) -> str:
    """The next ``wall_plane_N`` id not already in use.

    Corrections retire and mint ids out of the left-to-right order the automatic splitter numbers
    in (implementation-decisions.md #40: ids stay stable across a correction, so a Shade already
    assigned is never silently reassigned to a different wall) — a plain "count + 1" would
    eventually collide with an id an earlier correction already used, so this tracks the highest
    suffix actually in use instead.
    """

    highest = 0
    for plane_id in existing:
        if plane_id.startswith("wall_plane_"):
            suffix = plane_id.removeprefix("wall_plane_")
            if suffix.isdigit():
                highest = max(highest, int(suffix))
    return f"wall_plane_{highest + 1}"


def _next_ceiling_id(existing: Iterable[str]) -> str:
    """Ceiling ids are ``ceiling_plane_1`` — one per photo at most. Mint a fresh one only if none
    exists; otherwise reuse the same id so the dealer's shade assignment survives a re-add after
    deletion. Simpler than wall's counter because ceilings never split.
    """

    for plane_id in existing:
        if plane_id == CEILING_PLANE_ID:
            return CEILING_PLANE_ID
    return CEILING_PLANE_ID


def _left_edge(plane: WallPlane) -> float:
    """The leftmost confidently-covered column, for ordering — see :func:`order_left_to_right`."""

    coverage = plane.alpha[..., 0]
    covered = np.flatnonzero((coverage >= _CORE_LEVEL).any(axis=0))
    return float(covered[0]) if len(covered) else float(coverage.shape[1])


def order_left_to_right(planes: tuple[WallPlane, ...]) -> tuple[WallPlane, ...]:
    """Planes in left-to-right photo order.

    The automatic splitter (segmentation/split.py) always hands its planes back this way, and
    apps/ui/src/consultation/accent.ts's ``describeWall`` names a wall "the left wall" / "the
    right wall" purely from its position in this list. A correction changes *which* planes exist
    without going through the automatic splitter, so it is what has to re-establish the order.
    """

    return tuple(sorted(planes, key=_left_edge))


def _seam(winner: np.ndarray, loser: np.ndarray, radius: int) -> np.ndarray:
    """Where two planes' soft claims are describing the *same* boundary rather than each other's.

    Three conditions, and all three are load-bearing:

    * **both claim it** — otherwise there is nothing to reconcile;
    * **each is inside the other's boundary band** — a seam has two 0.5-contours a few pixels apart,
      and a pixel far from either contour is simply interior to one plane and unknown to the other;
    * **their confident interiors do not overlap** — this is what separates a seam from two planes
      fading into the *same* exclusion. Two planes that both pull back from one window have cores
      that coincide, and summing there would paint over the window's surround twice over, which is
      the over-count bug 03's path 3 warns about. Where two planes genuinely face each other, one
      plane's interior is the other plane's exterior, so this is nearly always true.
    """

    # Strictly above the level, not at or above it. A pixel reading exactly 0.5 is *on* the contour,
    # and a contour belongs to neither side — which is what a contour is. Counting it as part of
    # both
    # cores makes them overlap on the seam itself, and the seam is the one pixel the union exists to
    # fix, so the rule would have excluded exactly what it was written for. It also keeps the
    # shared-exclusion case working: two mattes both sitting at 0.6 well inside the same hole are
    # both core there, and are correctly told apart from a seam.
    winner_core = winner > _CORE_LEVEL
    loser_core = loser > _CORE_LEVEL
    winner_band = dilate(winner_core, radius) & ~erode(winner_core, radius)
    loser_band = dilate(loser_core, radius) & ~erode(loser_core, radius)
    return (winner > 0.0) & (loser > 0.0) & winner_band & loser_band & ~(winner_core & loser_core)


def resolve_exclusive(winner: np.ndarray, loser: np.ndarray, radius: int) -> np.ndarray:
    """``winner``'s matte once the two planes' overlapping claims have been reconciled.

    **On a seam the winner takes the union, not its own value** — ``min(1, a + b)`` rather than
    ``max(a, b)``. This is the fix for bug 03 path 3. Two soft mattes meeting at a seam each read
    about half at the join; keeping the higher leaves the pixel at half coverage, the render paints
    half a coat over it, and the old paint shows through as a faint stripe along the shared edge —
    the "colour is faint where selected" report. Summing them is what makes the wall whole there.

    **Elsewhere it keeps ``max``**, which is the ordinary answer: one plane has the pixel and the
    other does not, so the winner's own value already is the max. See :func:`_seam` for how the two
    cases are told apart — the tempting simplification, summing wherever both claims are nonzero,
    over-counts along a shared exclusion boundary.

    Which of the two planes is ``winner`` is *not* decided here. It is the caller's, from the same
    comparison it already makes, and this function only answers "given that this one won, what is it
    worth". Deciding it here too would be the same rule written twice in two places, and the two
    copies would not stay in step.
    """

    return np.where(
        _seam(winner, loser, radius),
        np.minimum(1.0, winner + loser),
        np.maximum(winner, loser),
    ).astype(np.float32)


def seam_radius(shape: tuple[int, int]) -> int:
    """How far apart two planes' boundaries may be and still count as a seam, in pixels.

    The same fraction the matte's own boundary band is built from, deliberately: a seam is a pair
    of matte boundaries, so "close enough to be the same boundary" is the same question the band
    already answers for a matte against itself. Two constants for one idea is how they drift apart.
    """

    return max(1, round(min(shape) * BAND_FRACTION))


def add_plane(
    graphs: Graphs,
    photo_u8: np.ndarray,
    features: RefinerFeatures,
    point: tuple[int, int],
    existing: tuple[WallPlane, ...],
) -> tuple[WallPlane, tuple[WallPlane, ...]]:
    """A new Wall Plane grown from one tapped point — the Add tool, and the surface reachable
    when automatic detection missed a wall entirely, from a photo with none at all to one that
    simply missed a sliver at the frame edge.

    SAM 2 decodes from the tap as its only positive prompt. No negatives, unlike the automatic
    pass (segmentation/prompts.prompts_for): there is no ``SemanticRegions`` here to sample
    exclusions from, and the Dealer's own tap is the intent signal this correction is built
    around — a tap that lands on a window is a tap the Dealer chose to make.

    Returns ``(new_plane, adjusted_existing)``: the grown plane, and every existing plane with
    its own matte adjusted wherever the two overlap. Resolved by the stronger claim, pixel by
    pixel — not simply "the new plane wins" — because a fresh decode's own soft edge can brush
    against an existing plane's confident *interior* as readily as its uncertain boundary, and an
    already-correct pixel must never be made worse by an unrelated correction elsewhere in the
    photo. Where the two disagree, whichever was more confident keeps the pixel at exactly the
    value it already had; the loser drops to zero there. The union of every plane's coverage can
    therefore only ever stay the same or improve — never regress — which is the property the
    test against real photographs checks.
    """

    x, y = point
    check_addable(existing, point)

    prompts = single_point_prompt(graphs.refiner_decoder.config, photo_u8.shape[:2], x, y)
    refined, _iou_score = decode_alpha(graphs, features, prompts, photo_u8.shape[:2])
    alpha = soften_boundary(photo_u8, refined)

    # Existing planes are already mutually disjoint, so at most one has a nonzero claim at any
    # given pixel — this is simply whichever one that is, or 0 where none claims it at all.
    existing_claim = np.zeros(photo_u8.shape[:2], dtype=np.float32)
    for plane in existing:
        existing_claim = np.maximum(existing_claim, plane.alpha[..., 0])

    # Exclusivity (spec, "Corners"): the higher claim survives at full strength, the other drops
    # to zero, so no pixel is ever composited twice. Ties favour the new plane — it exists
    # because the Dealer tapped exactly there.
    new_wins = alpha >= existing_claim
    resolved_new = np.where(
        new_wins, resolve_exclusive(alpha, existing_claim, seam_radius(alpha.shape)), 0.0
    ).astype(np.float32)

    coverage = float(resolved_new.mean())
    if coverage < MINIMUM_WALL_FRACTION:
        raise NothingFoundToAdd(f"the grown matte covers {coverage:.4f} of the photo")

    plane_id = _next_plane_id(plane.plane_id for plane in existing)
    new_plane = WallPlane(plane_id=plane_id, alpha=resolved_new[..., None], surface="wall")

    adjusted_existing = tuple(
        WallPlane(
            plane_id=plane.plane_id,
            alpha=np.where(new_wins, 0.0, plane.alpha[..., 0]).astype(np.float32)[..., None],
            surface=plane.surface,
        )
        for plane in existing
    )
    return new_plane, adjusted_existing


def add_ceiling_plane(
    graphs: Graphs,
    photo_u8: np.ndarray,
    features: RefinerFeatures,
    point: tuple[int, int],
    existing: tuple[WallPlane, ...],
) -> tuple[WallPlane, tuple[WallPlane, ...]]:
    """A new Ceiling Plane grown from one tapped point — the Add Ceiling tool.

    Same decoding as :func:`add_plane` but the resulting plane is tagged
    ``surface="ceiling"`` and will never be grouped with a wall's base colour.
    The ceiling is always one region, so no splitting.
    """

    x, y = point
    check_addable(existing, point)

    prompts = single_point_prompt(graphs.refiner_decoder.config, photo_u8.shape[:2], x, y)
    refined, _iou_score = decode_alpha(graphs, features, prompts, photo_u8.shape[:2])
    alpha = soften_boundary(photo_u8, refined)

    existing_claim = np.zeros(photo_u8.shape[:2], dtype=np.float32)
    for plane in existing:
        existing_claim = np.maximum(existing_claim, plane.alpha[..., 0])

    new_wins = alpha >= existing_claim
    resolved_new = np.where(
        new_wins, resolve_exclusive(alpha, existing_claim, seam_radius(alpha.shape)), 0.0
    ).astype(np.float32)

    coverage = float(resolved_new.mean())
    if coverage < MINIMUM_CEILING_FRACTION:
        raise NothingFoundToAdd(f"the grown ceiling covers {coverage:.4f} of the photo")

    plane_id = _next_ceiling_id(plane.plane_id for plane in existing)
    new_plane = WallPlane(plane_id=plane_id, alpha=resolved_new[..., None], surface="ceiling")

    adjusted_existing = tuple(
        WallPlane(
            plane_id=plane.plane_id,
            alpha=np.where(new_wins, 0.0, plane.alpha[..., 0]).astype(np.float32)[..., None],
            surface=plane.surface,
        )
        for plane in existing
    )
    return new_plane, adjusted_existing


def split_plane(
    photo_u8: np.ndarray,
    planes: tuple[WallPlane, ...],
    point: tuple[int, int],
) -> tuple[WallPlane, WallPlane, WallPlane]:
    """Split whichever Wall Plane contains the tapped point into two, at that point's column —
    the Split tool, and the same hard vertical cut the automatic splitter makes
    (segmentation/split.py), with the seam given by the Dealer instead of detected cues.

    Returns ``(first_half, second_half, original)`` — the same three-tuple shape
    :func:`merge_planes` returns, so a caller removes ``original`` from the plane list and puts
    the two halves in its place. Both halves mint fresh ids; the original's is retired. Nothing
    says which half — if either — should keep a Shade already assigned to the wall being split,
    so neither does (implementation-decisions.md #40). A ceiling cannot be split — it is one
    region per photo.
    """

    x, y = point
    target = _plane_containing(planes, x, y)
    if target is None:
        raise PointNotOnAPlane(f"({x}, {y}) is not covered by any existing Wall Plane")
    if target.surface == "ceiling":
        raise PointNotOnAPlane(f"({x}, {y}) is on the ceiling, which cannot be split")

    coverage = target.alpha[..., 0]
    height, width = coverage.shape
    on_the_left = np.arange(width)[None, :] < x
    left = np.where(on_the_left, coverage, 0.0).astype(np.float32)
    right = (coverage - left).astype(np.float32)

    # The same viability floor automatic detection uses for "worth offering as a paintable
    # surface" (segmentation/walls.MINIMUM_WALL_FRACTION), applied per side so a tap near a
    # plane's own edge cannot mint a sliver nobody could judge a colour from.
    photo_area = float(height * width)
    left_fraction = float(np.count_nonzero(left >= _CORE_LEVEL)) / photo_area
    right_fraction = float(np.count_nonzero(right >= _CORE_LEVEL)) / photo_area
    if left_fraction < MINIMUM_WALL_FRACTION or right_fraction < MINIMUM_WALL_FRACTION:
        raise SplitTooCloseToTheEdge(
            f"split at x={x} leaves {left_fraction:.4f}/{right_fraction:.4f} of the photo"
        )

    existing_ids = [plane.plane_id for plane in planes]
    first_id = _next_plane_id(existing_ids)
    second_id = _next_plane_id([*existing_ids, first_id])
    return (
        WallPlane(plane_id=first_id, alpha=left[..., None], surface=target.surface),
        WallPlane(plane_id=second_id, alpha=right[..., None], surface=target.surface),
        target,
    )


def merge_planes(
    planes: tuple[WallPlane, ...],
    point: tuple[int, int],
) -> tuple[WallPlane, WallPlane, WallPlane]:
    """The two Wall Planes meeting nearest the tapped point, unioned into one — the Merge tool.

    Returns ``(merged, first_source, second_source)`` so a caller can remove the two originals
    and put the merged plane in their place. No model call: the two mattes are already disjoint
    (spec, "Corners"), so the union is a plain sum, never a re-decode.
    """

    x, y = point
    pair = _nearest_pair(planes, x, y)
    if pair is None:
        raise PointNotNearASeam(f"({x}, {y}) is not near where two Wall Planes meet")

    first, second = pair
    # Ceiling and wall must not be merged — different surfaces.
    if first.surface != second.surface:
        raise PointNotNearASeam(
            f"({x}, {y}) is between a {first.surface} and a "
            f"{second.surface}, which cannot be merged"
        )
    merged_alpha = np.clip(first.alpha + second.alpha, 0.0, 1.0).astype(np.float32)
    # The larger plane's id survives, so a Shade already assigned to it keeps working
    # (implementation-decisions.md #40) — an arbitrary but deterministic tie-break otherwise.
    survivor_id = first.plane_id if first.coverage >= second.coverage else second.plane_id
    survivor_surface = first.surface
    merged = WallPlane(plane_id=survivor_id, alpha=merged_alpha, surface=survivor_surface)
    return merged, first, second
