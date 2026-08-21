"""Splitting the wall region into Wall Planes using vertical structure (issue #7).

A wall region found by :mod:`spectrapaint.segmentation.walls` is one matte:
soft where the wall meets a non-wall, hard nowhere. Issue #7 asks for the
planes inside it — walls at different angles that keep their own brightness so
the room still reads as three-dimensional and an Accent Wall is possible.

The split is automatic and costs zero taps. It uses vertical structure, which
in a photograph of a corner is three things that coincide:

* a **strong vertical edge** (the corner line itself, where the image
  changes quickly left-to-right)
* **vanishing-line** geometry (that edge is near-vertical in the world, so it
  is near-vertical in the photo)
* a **shading-gradient reversal** (each wall grows darker toward the corner,
  so the horizontal luminance gradient changes sign there)

Implementation:

* ``energy[x] = mean |dL/dx| over interior rows of column x`` — the
  vertical-edge cue. Computed on raw luminance, thresholded on unsmoothed
  prominence (not a heavily smoothed absolute) so a narrow corner is not
  diluted by its neighbours.
* ``valley[x] = median luminance per column`` — the shading cue. A corner
  is a dark valley where the median dips, or a step where two paints meet.
  This cue is **primary**: a column with a clear valley/step is kept even
  when its edge energy is modest (the same-colour shading-only archetype),
  while a column with high energy but no valley (curtain, furniture edge)
  is rejected.

Peaks become seams; seams become a hard partition of the original Alpha Matte.

Partition guarantees:

* every wall pixel belongs to **exactly one** plane (hard vertical cut, no
  overlap)
* no dark seam (disjoint alphas, never double-composited)
* soft matte only wall-to-non-wall; wall-to-wall stays crisp
"""

from __future__ import annotations

import logging

import numpy as np

from spectrapaint.imaging import erode
from spectrapaint.segmentation.matte import luminance_of

logger = logging.getLogger(__name__)

# Minimum plane area as fraction of the whole wall area. A return wall is
# normally a narrow strip near the frame edge (Room 1 left strip ≈4.4% of width,
# ≈11% of area); a side-fraction margin of 15% would exclude it structurally.
# Area is the honest discriminator: a texture line near the edge leaves no
# material wall on one side, a real corner does.
_MIN_PLANE_AREA_FRACTION = 0.04
_MIN_PLANE_WIDTH_FRACTION = 0.03
# Seam candidates must be this far apart (as fraction of wall width), or the
# weaker is a duplicate of the same corner.
_MIN_SEAM_SEPARATION_FRACTION = 0.18
# How far inside the matte the column energy is measured, as fraction of the
# photo's shorter side. Matches the erosion the Base Colour uses.
_EROSION_FRACTION = 0.01
# Valley / step neighbourhood radius, as fraction of wall width. Larger than
# the smoothing radius so a true corner valley sees the bright wall centre.
_VALLEY_RADIUS_FRACTION = 0.15
# Peak prominence as fraction of the global maximum. A secondary texture ridge
# at 20% of the main corner must not split the wall again.
_PROMINENCE_FRACTION = 0.25
# Interior test: a column must have this share of its rows as interior wall
# to be considered, or it is mostly window/furniture gap.
_MIN_COLUMN_COVERAGE = 0.08
# Maximum seams to emit (3 planes needs 2 seams). Typical photo has 2-3 planes.
_MAX_SEAMS = 2
# Energy floors. _ENERGY_FLOOR is the strong-edge threshold; _ENERGY_FLOOR_LOW
# is the permissive floor used when a clear valley/step is present (the
# same-colour shading-only corner has raw ≈0.008 but a deep valley).
_ENERGY_FLOOR = 0.010
_ENERGY_FLOOR_LOW = 0.004
# Valley / step thresholds on a 0-1 luminance scale.
_VALLEY_DEPTH_FRACTION = 0.030
_STEP_FRACTION = 0.090
# Small smoothing for the median profile, to quieten single-column texture
# without diluting a narrow corner. Fixed radius in pixels, not wall-fraction.
_MEDIAN_SMOOTH_RADIUS = 3


def _column_energy(luminance: np.ndarray, interior: np.ndarray) -> np.ndarray:
    """Mean |dL/dx| per column, over interior rows only."""

    gx = np.abs(np.gradient(luminance.astype(np.float32), axis=1))
    height = luminance.shape[0]
    energy = np.zeros(luminance.shape[1], dtype=np.float32)
    column_counts = interior.sum(axis=0).astype(np.float32)
    sums = np.sum(np.where(interior, gx, 0.0), axis=0)
    valid = column_counts > (height * _MIN_COLUMN_COVERAGE)
    energy[valid] = sums[valid] / column_counts[valid]
    return energy


def _column_median(luminance: np.ndarray, interior: np.ndarray) -> np.ndarray:
    """Median luminance per column, over interior rows only (NaN where sparse)."""

    width = luminance.shape[1]
    height = luminance.shape[0]
    median = np.full(width, np.nan, dtype=np.float32)
    for x in range(width):
        rows = interior[:, x]
        if rows.sum() >= height * _MIN_COLUMN_COVERAGE:
            median[x] = float(np.median(luminance[rows, x]))
    return median


def _smooth_1d(signal: np.ndarray, radius: int) -> np.ndarray:
    """Box-mean smoothing with edge padding (O(n) via cumulative sum)."""

    if radius <= 0:
        return signal
    padded = np.pad(signal, radius, mode="edge")
    cumsum = np.concatenate([[0.0], np.cumsum(padded, dtype=np.float64)])
    window = 2 * radius + 1
    # Padded length n+2r → result length exactly n
    result = (cumsum[window:] - cumsum[:-window]) / float(window)
    return result.astype(np.float32)


def _fill_nans_nearest(arr: np.ndarray) -> np.ndarray:
    """Fill NaN by nearest valid (forward then backward)."""

    filled = arr.copy()
    # forward
    for i in range(1, len(filled)):
        if np.isnan(filled[i]) and not np.isnan(filled[i - 1]):
            filled[i] = filled[i - 1]
    for i in range(len(filled) - 2, -1, -1):
        if np.isnan(filled[i]) and not np.isnan(filled[i + 1]):
            filled[i] = filled[i + 1]
    return filled


def _find_seams(
    photo_u8: np.ndarray,
    coverage: np.ndarray,
) -> list[int]:
    """Vertical seam columns, sorted, possibly empty."""

    height, width = coverage.shape
    wall_interior_mask = coverage >= 0.5
    if not wall_interior_mask.any():
        wall_interior_mask = coverage > 0.05

    radius = max(1, round(min(height, width) * _EROSION_FRACTION))
    interior = erode(wall_interior_mask, radius)
    if not interior.any():
        interior = wall_interior_mask

    cols_with_wall = np.flatnonzero(interior.any(axis=0))
    if len(cols_with_wall) < 2:
        return []
    wall_left = int(cols_with_wall[0])
    wall_right = int(cols_with_wall[-1]) + 1
    wall_width = wall_right - wall_left
    if wall_width < max(10, width * 0.15):
        return []

    luminance = luminance_of(photo_u8)
    energy = _column_energy(luminance, interior)
    col_median = _column_median(luminance, interior)

    # Restrict to wall span for peak search; outside span energy is zeroed
    # only for thresholding, not for median (which stays NaN there).
    span = np.zeros(width, dtype=bool)
    span[wall_left:wall_right] = True

    # Smoothed median for valley / step detection (small radius, not wall-fraction).
    filled_median = _fill_nans_nearest(col_median)
    # Where still NaN (sparse), fill with neutral 0.5 so smoothing does not pull extremes.
    filled_median = np.nan_to_num(filled_median, nan=0.5)
    smoothed_median = _smooth_1d(filled_median, _MEDIAN_SMOOTH_RADIUS)

    # Raw energy is primary — do NOT heavily smooth it before thresholding.
    # A narrow corner (1-2 px) would be diluted 25× by a 2%-width box (51 px at 1280).
    max_energy = float(np.nanmax(energy[span])) if np.any(span) else 0.0
    # At least one cue must be clearly present.
    # Keep a very low permissive floor when valley is strong.
    if max_energy < _ENERGY_FLOOR_LOW:
        # No vertical edge at all — only a valley could still be a corner if
        # shading alone is present, but check that a valley exists.
        # Quick valley check: does any column dip sufficiently?
        valley_depth_global = 0.0
        for x in range(wall_left + 1, wall_right - 1):
            if not span[x] or np.isnan(col_median[x]):
                continue
            nb = max(2, round(wall_width * _VALLEY_RADIUS_FRACTION))
            left = max(wall_left, x - nb)
            right = min(wall_right - 1, x + nb)
            neighbourhood = smoothed_median[left : right + 1]
            if neighbourhood.size == 0:
                continue
            valley_depth_global = max(
                valley_depth_global, float(np.nanmax(neighbourhood) - smoothed_median[x])
            )
        if valley_depth_global < _VALLEY_DEPTH_FRACTION:
            return []

    # Find local maxima in raw energy (strict > neighbours), with prominence.
    threshold = max_energy * _PROMINENCE_FRACTION
    # Also consider valley-driven candidates that may have modest energy.
    # So first collect energy peaks...
    energy_candidates: list[tuple[float, int]] = []
    for x in range(wall_left + 1, wall_right - 1):
        if not span[x]:
            continue
        val = float(energy[x])
        if not (val > float(energy[x - 1]) and val > float(energy[x + 1])):
            continue
        if val < threshold and val < _ENERGY_FLOOR_LOW:
            continue
        energy_candidates.append((val, x))

    valley_candidates: list[tuple[float, int]] = []  # (valley_depth, x)
    for x in range(wall_left + 1, wall_right - 1):
        if not span[x] or np.isnan(smoothed_median[x]):
            continue
        if (
            smoothed_median[x] >= smoothed_median[x - 1]
            or smoothed_median[x] >= smoothed_median[x + 1]
        ):
            continue
        nb = max(2, round(wall_width * _VALLEY_RADIUS_FRACTION))
        left = max(wall_left, x - nb)
        right = min(wall_right - 1, x + nb)
        neighbourhood = smoothed_median[left : right + 1]
        max_nb = float(np.nanmax(neighbourhood))
        depth = max_nb - float(smoothed_median[x])
        if depth >= _VALLEY_DEPTH_FRACTION:
            valley_candidates.append((depth, x))

    # Promote valley score so a true shading valley outranks texture edges
    # that happen to have a shallow local dip.

    # Striped wallpaper has many repeating valleys (every stripe) — not a corner.
    # A true corner has one (or two for three planes) valleys; wallpaper has many.
    if len(valley_candidates) > 4:
        return []

    # Merge candidates: energy peaks filtered by valley/step presence
    # Score each energy peak by valley depth / step, keep those where valley confirms edge
    combined: dict[int, float] = {}  # x -> score
    # Valley candidates contribute their depth as score
    for depth, x in valley_candidates:
        combined[x] = max(combined.get(x, 0.0), depth * 2.0)
    for val, x in energy_candidates:
        # Valley depth at this column
        nb = max(2, round(wall_width * _VALLEY_RADIUS_FRACTION))
        left = max(wall_left, x - nb)
        right = min(wall_right - 1, x + nb)
        neighbourhood = smoothed_median[left : right + 1]
        max_nb = (
            float(np.nanmax(neighbourhood)) if neighbourhood.size else float(smoothed_median[x])
        )
        depth = max_nb - float(smoothed_median[x])
        # Step
        left_med = float(np.nanmedian(smoothed_median[left:x])) if x > left else np.nan
        right_med = (
            float(np.nanmedian(smoothed_median[x + 1 : right + 1])) if x + 1 <= right else np.nan
        )
        step = (
            abs(left_med - right_med) if not np.isnan(left_med) and not np.isnan(right_med) else 0.0
        )
        has_valley = depth >= _VALLEY_DEPTH_FRACTION
        has_step = step >= _STEP_FRACTION
        if has_valley or has_step:
            score = val + depth * 0.5 + step * 0.3
            combined[x] = max(combined.get(x, 0.0), score)

    if not combined:
        return []

    # Rank by score
    ranked = sorted(combined.items(), key=lambda kv: kv[1], reverse=True)
    # Enforce minimum separation (take strongest, suppress neighbours)
    min_gap = max(1, round(wall_width * _MIN_SEAM_SEPARATION_FRACTION))
    chosen: list[int] = []
    for x, _score in ranked:
        if all(abs(x - c) >= min_gap for c in chosen):
            chosen.append(x)
        if len(chosen) >= _MAX_SEAMS:
            break
    chosen.sort()

    # Area-based validation will happen in the caller, but early-reject seams
    # that would create a sliver plane below area threshold (replaces side-fraction).
    # We do a quick width check here to avoid a seam 2 px from the edge that
    # would be merged away anyway.
    if chosen:
        # Simulate bounds to check area
        seams_sorted = sorted(chosen)
        bounds: list[tuple[int, int]] = []
        prev = 0
        for seam in seams_sorted:
            bounds.append((prev, seam))
            prev = seam
        bounds.append((prev, width))
        # Estimate area per plane from coverage span (proxy: width fraction * mean coverage)
        total_wall_pixels = float(np.count_nonzero(coverage >= 0.5))
        if total_wall_pixels == 0:
            total_wall_pixels = float(np.count_nonzero(coverage > 0.05))
        filtered: list[int] = []
        for idx, seam in enumerate(seams_sorted):
            # Left plane width vs right — check if either neighbour would be sliver
            left_bound = bounds[idx]
            right_bound = bounds[idx + 1]
            left_width = left_bound[1] - left_bound[0]
            right_width = right_bound[1] - right_bound[0]
            # Width fractions
            left_frac_w = left_width / max(1, wall_width)
            right_frac_w = right_width / max(1, wall_width)
            # Rough area: width * height * mean coverage in that slice (approx)
            # Use coverage mean as proxy; if either side is below width and area thresholds, the seam is too close to edge  # noqa: E501
            if (
                left_frac_w < _MIN_PLANE_WIDTH_FRACTION
                and left_width < wall_width * _MIN_PLANE_WIDTH_FRACTION
            ):
                # Left sliver — only keep seam if left slice still has meaningful wall area
                left_slice = coverage[:, left_bound[0] : left_bound[1]]
                left_area = float(np.count_nonzero(left_slice >= 0.5))
                if left_area / max(1, total_wall_pixels) < _MIN_PLANE_AREA_FRACTION:
                    continue
            if right_frac_w < _MIN_PLANE_WIDTH_FRACTION:
                right_slice = coverage[:, right_bound[0] : right_bound[1]]
                right_area = float(np.count_nonzero(right_slice >= 0.5))
                if right_area / max(1, total_wall_pixels) < _MIN_PLANE_AREA_FRACTION:
                    # Seam too close to right edge creating sliver — drop this seam, keep stronger
                    # Instead of dropping seam outright, we let the merge stage handle it; keep seam for now  # noqa: E501
                    pass
            filtered.append(seam)
        chosen = filtered

    return chosen


def split_alpha_into_planes(
    photo_u8: np.ndarray,
    alpha: np.ndarray,
) -> list[np.ndarray]:
    """Partition the wall Alpha Matte into per-plane mattes.

    Returns a list of ``HxWx1 float32`` mattes, one per Wall Plane. The list
    is never empty; when no vertical structure is found it returns the
    original matte alone (one plane). When seams are found each matte is a
    hard vertical slice of the original so that every wall pixel belongs to
    exactly one plane and the outer soft edge is preserved.
    """

    coverage = np.asarray(alpha, dtype=np.float32).reshape(alpha.shape[0], alpha.shape[1])
    height, width = coverage.shape
    original = np.clip(coverage, 0.0, 1.0)

    seams = _find_seams(photo_u8, original)
    if not seams:
        return [original[..., None].astype(np.float32)]

    seams_sorted = sorted(seams)
    bounds: list[tuple[int, int]] = []
    prev = 0
    for seam in seams_sorted:
        bounds.append((prev, seam))
        prev = seam
    bounds.append((prev, width))

    planes: list[np.ndarray] = []
    for left, right in bounds:
        mask = np.zeros((height, width), dtype=bool)
        mask[:, left:right] = True
        plane_coverage = np.where(mask, original, 0.0).astype(np.float32)
        # Degenerate check — but do not drop silently (see walls.py merge). Mark for merge.
        if float(plane_coverage.mean()) < 0.001:
            # Truly empty — no wall here, skip but keep at least one plane later
            continue
        if np.count_nonzero(plane_coverage >= 0.5) < max(2, height // 32):
            # Very thin sliver — still keep as candidate for merge stage; do not drop coverage
            pass
        planes.append(plane_coverage[..., None])

    if len(planes) <= 1:
        return [original[..., None].astype(np.float32)]

    # Validate area per plane — merge slivers instead of deleting coverage
    # (conventions.md §5: never dead-end / degrade, not 500). The caller
    # (walls.py) will also handle logging; here we just ensure no sliver is
    # offered as a paintable surface with <4% area unless it is the only way.
    total_pixels = float(np.count_nonzero(original >= 0.5))
    if total_pixels == 0:
        total_pixels = float(np.count_nonzero(original > 0.05))
    # Merge any plane below area threshold into its larger neighbour
    merged: list[np.ndarray] = []
    i = 0
    while i < len(planes):
        cov = planes[i][..., 0]
        area = float(np.count_nonzero(cov >= 0.5)) / max(1.0, total_pixels)
        width_frac = (bounds[i][1] - bounds[i][0]) / max(
            1, (max(b[1] for b in bounds) - min(b[0] for b in bounds))
        )
        if (
            area < _MIN_PLANE_AREA_FRACTION
            and width_frac < _MIN_PLANE_WIDTH_FRACTION
            and len(planes) > 1
        ):
            # Merge into neighbour with larger area
            if merged:
                # Merge into previous
                merged[-1] = (merged[-1] + planes[i]).clip(0, 1)
            elif i + 1 < len(planes):
                # Merge into next (defer)
                planes[i + 1] = (planes[i + 1] + planes[i]).clip(0, 1)
            # else single plane — keep
        else:
            merged.append(planes[i])
        i += 1

    if len(merged) <= 1:
        return [original[..., None].astype(np.float32)]

    # Final partition guarantee: disjoint and sum equals original (no dropped coverage)
    # Because we merged rather than deleted, sum should equal original
    return merged
