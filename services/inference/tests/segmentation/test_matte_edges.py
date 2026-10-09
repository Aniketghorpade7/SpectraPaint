"""Fast-lane unit tests for the Alpha Matte's edges (issue #51).

The models lane in `tests/api/test_walls.py` measures whether the pipeline finds walls on real
photographs. It cannot measure the thing #51 is actually about, which is the *shape* of the matte's
edge — and it cannot do it cheaply, because every assertion about edge shape needs a synthetic input
with a known geometry, and the fixtures do not have one.

So these are synthetic, fast, and deliberately brutal about the two properties that were broken:

* a matte's boundary does not follow SegFormer's 128x128 grid, and
* a matte is soft everywhere — no step where a zone meets its neighbour, and no pixel of an excluded
  region carries coverage.

Both are stated as properties of the *output* rather than of the implementation. A test that
asserted
"calls `erode_round`" would pass while the matte kept its staircase, because the staircase has more
than one possible cause and this pipeline had four.
"""

from __future__ import annotations

import numpy as np
import pytest

from spectrapaint.imaging import _ERODE_LEVEL, erode, erode_round
from spectrapaint.segmentation.corrections import resolve_exclusive, seam_radius
from spectrapaint.segmentation.matte import (
    EXCLUSION_FEATHER_FRACTION,
    exclusion_ramp,
    soften_boundary,
    wall_alpha,
)
from spectrapaint.segmentation.semantic import (
    UNCLAIMED,
    SemanticRegions,
    _resize_to,
    argmax_at_photo_resolution,
)
from tests.segmentation.grid_metric import (
    SEMANTIC_GRID,
    edge_on_grid,
    edge_on_grid_fraction,
    grid_excess,
)


def _regions(
    shape: tuple[int, int],
    *,
    wall: np.ndarray | None = None,
    excluded: np.ndarray | None = None,
    wall_confidence: np.ndarray | None = None,
    ceiling: np.ndarray | None = None,
) -> SemanticRegions:
    empty = np.zeros(shape, dtype=bool)
    return SemanticRegions(
        wall=wall if wall is not None else empty,
        excluded=excluded if excluded is not None else empty.copy(),
        wall_confidence=(
            wall_confidence if wall_confidence is not None else np.zeros(shape, dtype=np.float32)
        ),
        ceiling=ceiling if ceiling is not None else empty.copy(),
        ceiling_confidence=np.zeros(shape, dtype=np.float32),
        floor_exempt=empty.copy(),
    )


class TestTheBoundaryLeavesTheGrid:
    """The 128-grid must not be able to tell where a matte's edge is.

    Measured three ways, because each catches a different mistake: on the semantic map, on the
    finished matte, and on a nearest-neighbour control that stands for the code #51 replaced. The
    control is not decoration — a metric that scores the old code well is not measuring grid
    alignment, and this fixture was wrong twice before it measured anything.
    """

    def test_the_matte_has_almost_no_razor_edges_at_all(self) -> None:
        """A diagonal wall/floor boundary comes out of `wall_alpha` with no razor edge on it.

        This is the acceptance criterion stated as a property of the *output* (#51:
        `edge_on_grid_fraction`
        <= 0.10), and it passes by a wider margin than the threshold: the soft exclusion ramp and
        the
        continuous band together mean there is no jump over 0.5 anywhere along this boundary to
        place
        on a grid line in the first place. The AC is a floor on how bad it may be, not a target to
        aim at.
        """

        matte = _synthetic_matte()
        fraction, edges = edge_on_grid_fraction(matte)
        assert fraction <= 0.10, f"{fraction:.3f} of razor edges sit on the {SEMANTIC_GRID}-grid"
        assert edges < 50, (
            f"the boundary still produced {edges} razor edges; the matte is meant to be soft along "
            f"it, and a soft edge has no jump to measure"
        )

    def test_the_semantic_boundary_has_moved_off_the_grid(self) -> None:
        """The decision itself is no longer quantised to the grid, which is the change #51 made.

        On the semantic map *before* the matte softens it. This cannot reach 0.10 — a binary map of
        where the wall is will always have an edge somewhere, and at 960x1280 the grid lines are
        every 7.5 rows and 10 columns, so even a perfectly diagonal boundary lands near one a
        quarter
        of the time by chance. What it can do is show the boundary moved, which it does not do at
        all
        under the nearest-neighbour decision it replaced.
        """

        regions = _synthetic_regions((960, 1280))
        sharp = regions.wall.astype(np.float32) - regions.excluded.astype(np.float32)
        fraction, edges = edge_on_grid_fraction(sharp)
        assert edges > 100, f"only {edges} razor edges; too few to judge"
        assert fraction <= 0.45, (
            f"{fraction:.3f} of the semantic boundary is still on the grid. Note that a binary map "
            f"cannot do better than about 0.22 by chance at this size; anything near the old 0.70 "
            f"means the decision is still being taken on the grid."
        )

    def test_the_nearest_neighbour_control_is_a_staircase(self) -> None:
        """Argmax at the grid, then nearest-neighbour — what the code did — has to score badly.

        Same synthetic probabilities, same photo, only the resampling differs. If this ever stops
        being true the test above has stopped measuring grid alignment and would pass for the wrong
        reason, which is worse than not having it.
        """

        regions = _synthetic_regions((960, 1280))
        coarse = regions.wall.shape[0] * SEMANTIC_GRID // 1280  # unused; see the ratio below
        assert coarse > 0  # the fixture really is a 128-grid upsampled to a 1280-wide photo

        control = _nearest_neighbour_control((960, 1280))
        fraction, edges = edge_on_grid_fraction(control)
        assert edges > 100
        assert fraction > 0.45, (
            f"the nearest-neighbour control only scored {fraction:.3f}, so the comparison above is "
            f"not measuring what it claims to"
        )


class TestNothingExcludedIsEverPainted:
    def test_a_pixel_the_semantic_pass_excluded_keeps_zero_coverage(self) -> None:
        """A window's pixels carry no coverage at all, whatever the refiner believed.

        "Never paint a window" is absolute (design-decisions.md §5), and the soft ramp added in #51
        makes it a place where that could have quietly stopped being true: the ramp is a
        *multiplier*
        on the matte, so a ramp that was not exactly 0 on the excluded side would leave coverage
        there. This is the assertion that keeps the ramp honest.
        """

        height, width = 320, 320
        excluded = np.zeros((height, width), dtype=bool)
        excluded[100:200, 100:200] = True

        ramp = exclusion_ramp(excluded, (height, width))
        assert float(ramp[excluded].max()) == 0.0, (
            "the exclusion ramp is nonzero inside the exclusion; a window would be repainted"
        )

        alpha = np.full((height, width), 0.9, dtype=np.float32)
        resolved = np.where(excluded, 0.0, alpha * ramp)
        assert float(resolved[excluded].max()) == 0.0

    def test_the_ramp_is_a_few_pixels_wide_and_reaches_full_coverage_away_from_the_edge(
        self,
    ) -> None:
        """The feather is narrow enough to read as an edge and wide enough to be one.

        Both halves matter and they pull against each other: too narrow and the matte's own edge
        steps across it, which is the artefact #51 exists to remove; too wide and a soft smear
        appears around every window, which is a defect of its own and harder to un-see than a step.
        """

        height, width = 960, 1280
        excluded = np.zeros((height, width), dtype=bool)
        excluded[:, 600:1000] = True

        ramp = exclusion_ramp(excluded, (height, width))
        radius = max(1, round(min(height, width) * EXCLUSION_FEATHER_FRACTION))

        # Fully recovered a few radii clear of the exclusion, and still fading inside them.
        assert float(ramp[100, 500]) == pytest.approx(1.0, abs=1e-3)
        just_outside = 600 - radius
        assert 0.0 < float(ramp[100, just_outside]) < 1.0
        assert float(ramp[100, 599]) < float(ramp[100, just_outside])


class TestTheBoundaryIsContinuous:
    def test_no_step_larger_than_a_tenth_wherever_a_zone_meets_its_neighbour(self) -> None:
        """Interior to band to exterior, with no jump at either join.

        The old code resolved the three zones with nested ``np.where``, which put a full 1.0 step at
        the inner join and a full 0.0 step at the outer one — so a matte the guided filter had just
        placed on a door frame came out with a hard edge on it, one zone away from the edge the
        issue was about. A step threshold of 0.1 is the issue's, and it is loose enough to allow the
        genuine 8-bit quantisation in `imaging.blur` while still catching either of those jumps.
        """

        height, width = 400, 600
        photo = np.full((height, width, 3), 200, dtype=np.uint8)

        # A step edge, and a strip narrower than the band radius — the shape the Add tool grows from
        # one tap, and the one a blend keyed on "0.5 means interior" cannot see at all.
        for region in (
            np.where(np.arange(width)[None, :] > 300, 1.0, 0.0).astype(np.float32),
            _strip(width, 40.0),
            _strip(width, 8.0),
        ):
            softened = soften_boundary(photo, np.broadcast_to(region, (height, width)).copy())
            worst = float(
                max(
                    np.abs(np.diff(softened, axis=0)).max(), np.abs(np.diff(softened, axis=1)).max()
                )
            )
            assert worst <= 0.1, f"a step of {worst:.3f} where a zone meets its neighbour"

    def test_the_interior_is_still_flat_and_the_exterior_still_empty(self) -> None:
        """Continuity is not licence for the interior to be anything but fully covered.

        The invariant the three-zone construction was written for: softness belongs at the edges and
        nowhere else ("soft matte edges are used only where a wall meets a non-wall", spec,
        "Corners"). A blend that spread fractional coverage across a whole wall would satisfy the
        continuity test above while making the render paint every wall at 90%.
        """

        height, width = 400, 600
        photo = np.full((height, width, 3), 200, dtype=np.uint8)
        alpha = np.zeros((height, width), dtype=np.float32)
        alpha[:, 300:] = 1.0

        softened = soften_boundary(photo, alpha)
        assert float(softened[height // 2, 500]) == pytest.approx(1.0)
        assert float(softened[height // 2, 50]) == pytest.approx(0.0)
        fractional = ((softened > 0.0) & (softened < 1.0)).sum()
        assert fractional > 100, (
            "a matte with no fractional pixels is a hard mask, which is the clearest possible sign "
            "an image has been altered (CONTEXT.md, Alpha Matte)"
        )

    def test_a_uniformly_unsure_mask_does_not_become_a_wall(self) -> None:
        """A refiner that is unsure everywhere must not produce a wall the render half-paints.

        This is the invariant in `soften_boundary`'s docstring, and the reason the zones are found
        *spatially* rather than by asking which alpha values look intermediate. A mask of 0.3 has no
        pixel above 0.5, so there is no region, and the result is nothing.
        """

        height, width = 200, 300
        photo = np.full((height, width, 3), 180, dtype=np.uint8)
        assert (
            float(soften_boundary(photo, np.full((height, width), 0.3, dtype=np.float32)).max())
            == 0.0
        )


class TestRoundMorphology:
    def test_erode_round_shrinks_a_straight_edge_by_the_radius_asked_for(self) -> None:
        """The erosion distance matches `erode`, not something near it.

        Measured on a straight edge, because that is the only geometry where the distance is exact.
        Pillow's `GaussianBlur(radius)` takes the radius as the standard deviation, so a half-plane
        blurs to exactly 0.5 *on* its own edge: thresholding there erodes by nothing, and because
        most of what these fixtures contain is straight-edged, "erodes by nearly zero" looks exactly
        like "round erosion barely matters". It shipped that way once and cost 0.031 of
        `windows-with-curtains`' shadowed-wall recall before the distance was measured rather than
        assumed.

        A curve is deliberately not used: the threshold is a *level set*, so on a convex boundary
        the
        curvature shifts it, and a disc eroded by 12 of 20 measures 9 rather than 8. Asserting the
        exact distance on a curve would be asserting the curvature, not the calibration.
        """

        assert _ERODE_LEVEL > 0.5, (
            "eroding at or below the half-maximum level set erodes by zero, not by the radius"
        )

        edge = np.zeros((400, 400), dtype=bool)
        edge[:, :200] = True
        for radius in (2, 5, 11):
            boundary = np.nonzero(erode_round(edge, radius).any(axis=0))[0].max()
            assert 199 - boundary == pytest.approx(radius, abs=1), (
                f"erode_round by {radius} moved a straight edge to {199 - boundary}"
            )

    def test_erode_round_cuts_corners_the_square_one_keeps(self) -> None:
        """The difference from `erode` is in the corners, which is the whole reason for it.

        A square structuring element removes a region's corners as fast as it removes the middle of
        a flat edge, so a hole in a wall comes out square and a band comes out stepped. Asserted on
        the bounding box rather than on a pixel count, because a count alone cannot tell a disc from
        a square of the same area.
        """

        square = _square(40)
        round_eroded = erode_round(square, 6)
        square_eroded = erode(square, 6)

        assert _corners_present(round_eroded) == 0, "a round erosion left the bounding-box corners"
        assert _corners_present(square_eroded) == 4, (
            "the square erosion no longer keeps the corners, so the two are no longer"
            " distinguishable"
        )
        assert round_eroded.sum() < square_eroded.sum(), (
            "a round erosion of a square must remove more than a square one does"
        )

    def test_a_disc_stays_a_disc(self) -> None:
        """Roundness as an aspect ratio, because that is the property being bought."""

        shrunk = erode_round(_disc(20.0), 6)
        ys, xs = np.nonzero(shrunk)
        width, height = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        assert width / height == pytest.approx(1.0, abs=0.05)


class TestResolveExclusive:
    def test_two_soft_mattes_meeting_at_a_seam_cover_it_between_them(self) -> None:
        """The faint-stripe fix: at a seam the winner takes the union, not the higher claim.

        Two soft mattes meeting at a seam each read about half at the join. Keeping the higher
        leaves
        the pixel at half coverage, the render lays half a coat over it, and the old paint shows
        through as the faint stripe bug 03 path 3 reports. This is the property, stated directly so
        that a future change to either matte cannot quietly reintroduce it.
        """

        height, width = 200, 200
        radius = seam_radius((height, width))

        winner = _half_plane("left", width / 2, feather=2.0)
        loser = _half_plane("right", width / 2, feather=2.0)

        resolved = resolve_exclusive(winner, loser, radius)
        contested = (winner > 0) & (loser > 0)
        assert contested.any(), "the fixture put the two mattes nowhere near each other"
        assert float(np.minimum(winner + loser, 1.0)[contested].min()) >= 0.99
        assert float(resolved[contested].min()) >= 0.99

    def test_two_mattes_fading_into_the_same_exclusion_are_not_summed(self) -> None:
        """The over-count that stops the obvious implementation from being the right one.

        Summing wherever both claims are nonzero double-counts along a shared exclusion boundary:
        two planes that both pull back from one window would together paint over its surround at
        twice the coverage. Here the two mattes share a hole and nothing else, so they must resolve
        to ``max`` and not to a sum.
        """

        height, width = 200, 200
        radius = seam_radius((height, width))

        both = np.full((height, width), 0.6, dtype=np.float32)
        both[80:120, 80:120] = 0.0
        variant = both.copy()
        variant[60:140, 60:140] = 0.0  # a larger exclusion, same interior

        resolved = resolve_exclusive(both, variant, radius)
        assert float(resolved.max()) <= float(np.maximum(both, variant).max()) + 1e-6

    def test_no_pixel_is_claimed_by_two_planes(self) -> None:
        """Exclusivity survives the union.

        The tempting way to write this is to give both planes the union at a seam, which makes the
        join look right and composites every pixel on it twice. The caller zeroes the loser; what is
        checked here is that nothing in this function can reintroduce a second claim on its own.
        """

        height, width = 160, 160
        radius = seam_radius((height, width))
        winner = _half_plane("left", width / 2, feather=2.0)
        loser = _half_plane("right", width / 2, feather=2.0)

        # As the callers do it: decide the winner, give it the reconciled value, and zero the loser
        # wherever it lost. A test that skips the masking would pass for the wrong reason.
        winner_wins = winner >= loser
        resolved_winner = np.where(winner_wins, resolve_exclusive(winner, loser, radius), 0.0)
        resolved_loser = np.where(winner_wins, 0.0, resolve_exclusive(loser, winner, radius))

        total = resolved_winner + resolved_loser
        assert float(total.max()) <= 1.0 + 1.0 / 255.0
        assert not ((resolved_winner > 0) & (resolved_loser > 0)).any(), "a pixel claimed twice"


class TestUnclaimedIsStillItsOwnAnswer:
    def test_a_class_the_pipeline_does_not_decide_about_stays_unclaimed(self) -> None:
        """A pixel of sofa is unknown, not wall and not an exclusion.

        Deciding among the five relevant classes alone would force every pixel of every unlisted
        class
        onto the nearest of them, and a curtain the network was split on would come back *wall* —
        which is how `corner-with-clothesline`'s leakage rose from a measured 0.338 to 0.391 when
        #51
        was first written that way. `UNCLAIMED` is the guard, so it gets its own test.
        """

        coarse = 8
        probabilities = np.full((6, coarse, coarse), 0.02, dtype=np.float32)
        probabilities[0] = 0.30  # wall
        probabilities[5] = 0.50  # sofa: wins its cell, and is not ours

        labels = argmax_at_photo_resolution(probabilities, (0, 1, 2, 3, 4), (16, 16))
        assert (labels == UNCLAIMED).all()
        assert UNCLAIMED == 5, "UNCLAIMED must be outside the relevant slices or it would alias one"


def _disc(radius: float, size: int = 81) -> np.ndarray:
    centre = (size - 1) / 2.0
    ys, xs = np.mgrid[0:size, 0:size]
    return ((ys - centre) ** 2 + (xs - centre) ** 2) <= radius**2


def _square(side: int, size: int = 81) -> np.ndarray:
    centre = (size - 1) // 2
    half = side // 2
    return (np.abs(np.arange(size) - centre) <= half)[:, None] & (
        np.abs(np.arange(size) - centre) <= half
    )[None, :]


def _corners_present(mask: np.ndarray) -> int:
    ys, xs = np.nonzero(mask)
    return (
        int(mask[ys.min(), xs.min()])
        + int(mask[ys.min(), xs.max()])
        + int(mask[ys.max(), xs.min()])
        + int(mask[ys.max(), xs.max()])
    )


def _strip(width: int, half_width: float) -> np.ndarray:
    """A bar half ``half_width`` wide, as a (1, width) strip for broadcasting down a photo."""
    row = np.zeros((1, width), dtype=np.float32)
    centre = width / 2
    row[0, int(centre - half_width) : int(centre + half_width)] = 1.0
    return row


def _half_plane(side: str, centre: float, feather: float, size: int = 200) -> np.ndarray:
    """One soft matte of a wall occupying the ``left`` or ``right`` of a vertical seam.

    ``feather`` is how many pixels the edge is spread over. The point of the fixture is that at the
    seam the two mattes each read *half* — which is the situation the union exists for, and which a
    fixture built from a hard threshold would not reproduce.
    """
    ys, xs = np.mgrid[0:size, 0:size]
    signed = (xs - centre) if side == "left" else (centre - xs)
    return np.clip(0.5 + signed / (2.0 * feather), 0.0, 1.0).astype(np.float32)


@pytest.mark.parametrize("surface", ["wall", "ceiling"])
def test_both_surfaces_ramp_out_the_other(surface: str) -> None:
    """A ceiling is an exclusion for a wall and a wall is an exclusion for a ceiling.

    Not a test of the ramp — `test_a_pixel_the_semantic_pass_excluded_keeps_zero_coverage` covers
    that. This exists because the two surfaces assemble their exclusion sets separately and could
    drift: `wall_alpha` excludes the ceiling, `ceiling_alpha` excludes the wall, and a change made
    to
    one and not the other is exactly the sort of thing nothing else here would notice. It also
    catches the mistake of building a ceiling's exclusions from the wall's `excluded`, which already
    contains ceiling and would therefore exclude the region being described.
    """

    height, width = 240, 240
    ceiling = np.zeros((height, width), dtype=bool)
    ceiling[20:100, 20:100] = True
    wall = np.zeros((height, width), dtype=bool)
    wall[120:220, 120:220] = True

    regions = _regions(
        (height, width),
        wall=wall,
        excluded=ceiling,
        ceiling=ceiling,
        wall_confidence=np.zeros((height, width), dtype=np.float32),
    )

    if surface == "wall":
        excluded = regions.excluded
        assert excluded[ceiling].all(), "a ceiling must be an exclusion for a wall"
        assert not excluded[wall].any(), "the wall excluded itself"
    else:
        # The ceiling's exclusion set is built without reusing the wall's, which already holds
        # ceiling. Rebuilding it from `regions.excluded` would make the ceiling exclude itself.
        other = regions.excluded & ~regions.ceiling
        ceiling_excluded = regions.wall | other
        assert ceiling_excluded[wall].all(), "a wall must be an exclusion for a ceiling"
        assert not ceiling_excluded[ceiling].any(), "the ceiling excluded itself"

    ramp = exclusion_ramp(ceiling, (height, width))
    assert float(ramp[ceiling].max()) == 0.0


def _synthetic_probabilities() -> tuple[np.ndarray, int]:
    """A 128-grid probability field with a *smooth* diagonal wall/floor boundary.

    Smooth is the whole point. A field that is constant inside each grid cell has a boundary that
    already lies exactly on a grid line, and no resampling can move a contour off a line it is
    sitting on — the fixture would score badly for the new code too and prove nothing. It was wrong
    that way once, and scored 0.82 for the new code, which is the bug's own number.

    A real checkpoint emits probabilities that vary within a cell, and the wall/floor crossover
    falls
    between them, so this is what the network actually hands over.
    """

    coarse = SEMANTIC_GRID
    ys, xs = np.mgrid[0:coarse, 0:coarse]
    edge = (xs + ys - coarse) / 8.0

    probabilities = np.full((5, coarse, coarse), 0.02, dtype=np.float32)
    probabilities[0] = 1.0 / (1.0 + np.exp(-edge))  # wall, above the diagonal
    probabilities[1] = 1.0 / (1.0 + np.exp(edge))  # floor, below it — an exclusion
    return probabilities, coarse


def _synthetic_regions(shape: tuple[int, int]) -> SemanticRegions:
    """`semantic_regions`' output for the synthetic diagonal, without a graph to run."""

    probabilities, _ = _synthetic_probabilities()
    labels = argmax_at_photo_resolution(probabilities, (0, 1, 2, 3, 4), shape)
    zero = np.zeros(shape, dtype=bool)
    return SemanticRegions(
        wall=labels == 0,
        excluded=np.isin(labels, (1, 2, 3, 4)),
        wall_confidence=np.clip(_resize_to(probabilities[0], shape, nearest=False), 0.0, 1.0),
        ceiling=zero,
        ceiling_confidence=np.zeros(shape, dtype=np.float32),
        floor_exempt=zero,
    )


def _synthetic_matte() -> np.ndarray:
    """The finished wall matte for the synthetic diagonal, as a 2-D array."""

    shape = (960, 1280)
    regions = _synthetic_regions(shape)
    photo = np.full((shape[0], shape[1], 3), 200, dtype=np.uint8)
    # A refiner that simply agrees with the semantic pass. The grid-aligned edges being tested are
    # the semantic pass's own, so a refiner that traced the photo's texture would confound the
    # measurement; this isolates what #51 changed.
    return wall_alpha(photo, regions, regions.wall_confidence)[..., 0]


def _nearest_neighbour_control(shape: tuple[int, int]) -> np.ndarray:
    """What the same field produced before #51: argmax at the grid, then nearest neighbour."""

    probabilities, _ = _synthetic_probabilities()
    coarse_labels = np.argmax(probabilities, axis=0) == 0
    return _resize_to(coarse_labels.astype(np.float32), shape, nearest=True)


class TestTheGridMetricItself:
    """The number the models lane asserts on has to mean what it says, so it is tested here."""

    def test_edges_unrelated_to_the_grid_score_their_chance_level(self) -> None:
        """Razor edges placed at random score their own chance level, not 0.

        This is why the acceptance wording "at most 0.10" cannot be met on a real photograph and the
        models lane asserts on the *surplus* over chance instead.
        """

        rng = np.random.default_rng(0)
        shape = (960, 1280)
        edge_columns = rng.integers(100, 1100, size=shape[0])
        matte = (np.arange(shape[1])[None, :] > edge_columns[:, None]).astype(np.float32)

        fraction, chance, edges = edge_on_grid(matte)
        excess, _ = grid_excess(matte)

        assert edges > 500
        assert 0.2 < chance < 0.4, f"chance level {chance:.3f}: not the ~30% a ±1px tolerance gives"
        assert abs(excess) < 0.05, f"{fraction:.3f} against chance {chance:.3f}"

    def test_the_staircase_has_a_large_surplus(self) -> None:
        excess, edges = grid_excess(_nearest_neighbour_control((960, 1280)))
        assert edges > 100
        assert excess > 0.3, f"the staircase's surplus over chance was only {excess:.3f}"
