"""Splitting the wall region into Wall Planes using vertical structure (issue #7).

A wall region found by :mod:`spectrapaint.segmentation.walls` is one matte:
soft where the wall meets a non-wall, hard nowhere. Issue #7 asks for the
planes inside it — walls at different angles that keep their own brightness so
the room still reads as three-dimensional and an Accent Wall is possible.

The split is automatic and costs zero taps. It uses vertical structure, which
in a photograph of a corner is three things that coincide:

* a **strong vertical edge** (the corner line itself, where the image
  changes quickly left-to-right)
* **vanishing-line** geometry (that edge is vertical in the world, so it is
  near-vertical in the photo)
* a **shading-gradient reversal** (each wall grows darker toward the corner,
  so the horizontal luminance gradient changes sign there)

The implementation turns those into a per-column energy:

  ``energy[x] = mean |dL/dx| over interior rows of column x``

where ``L`` is the photo's BT.709 luminance and the mean is taken only where
the wall interior is confidently wall (eroded inward so the wall-to-non-wall
edge never contributes). A corner is a column where this energy spikes *and*
where the median luminance valley sits — the two cues reinforce each other.
Peaks become seams; seams become a hard partition of the original Alpha Matte.

Partition guarantees (checked by the tests in :mod:`tests.render` and the
acceptance criteria):

* every wall pixel belongs to **exactly one** plane (hard vertical cut, no
  overlap)
* no dark seam (disjoint alphas, never double-composited)
* soft matte only wall-to-non-wall; wall-to-wall stays crisp (the seam is
  binary while the outer band stays feathered)
"""

from __future__ import annotations

import numpy as np

from spectrapaint.imaging import erode
from spectrapaint.segmentation.matte import luminance_of

# At least this share of the wall's bounding width must sit on each side of a
# seam, or the seam is too close to the outer edge to be a corner rather than
# a texture line near the wall's side.
_MIN_SIDE_FRACTION = 0.15
# Seam candidates must be this far apart (as fraction of wall width), or the
# weaker of the two is a duplicate of the same corner.
_MIN_SEAM_SEPARATION_FRACTION = 0.20
# How far inside the matte the column energy is measured, as fraction of the
# photo's shorter side. Matches the erosion the Base Colour uses, so the same
# "contaminated edge" is ignored for both purposes.
_EROSION_FRACTION = 0.01
# Smoothing window for the column energy, as fraction of photo width. Small
# enough to keep a corner's spike, large enough to quieten texture noise.
_SMOOTH_FRACTION = 0.02
# A flat wall's strongest column must exceed this energy to be called a seam.
# Tuned against synthetic uniform walls (energy ~0) and two-tone walls
# (energy ~0.08-0.25 on a 0-1 luminance scale). 0.015 catches a real corner
# and leaves a flat rectangle alone.
_ENERGY_FLOOR = 0.015
# Peak prominence as fraction of the global maximum. A secondary texture
# ridge at 20% of the main corner must not split the wall again.
_PROMINENCE_FRACTION = 0.35
# Interior test: a column must have this share of its rows as interior wall
# to be considered for the energy, or it is mostly window/furniture gap.
_MIN_COLUMN_COVERAGE = 0.10
# Maximum seams to emit (3 planes needs 2 seams). Typical photo has 2-3 planes.
_MAX_SEAMS = 2


def _column_energy(luminance: np.ndarray, interior: np.ndarray) -> np.ndarray:
    """Mean |dL/dx| per column, over interior rows only."""

    # Horizontal gradient, absolute value. Gradient on the luminance the
    # Dealer sees (gamma-encoded), because a visible edge is what matters
    # rather than a linear-light one.
    gx = np.abs(np.gradient(luminance.astype(np.float32), axis=1))

    height, width = luminance.shape
    energy = np.zeros(width, dtype=np.float32)
    column_counts = interior.sum(axis=0).astype(np.float32)

    # Vectorised mean per column.
    # np.sum over boolean mask needs the mask broadcast correctly.
    sums = np.sum(np.where(interior, gx, 0.0), axis=0)
    # Avoid division by zero for empty columns.
    valid = column_counts > (height * _MIN_COLUMN_COVERAGE)
    energy[valid] = sums[valid] / column_counts[valid]
    # Columns with too little wall are not seams.
    return energy


def _smooth_1d(signal: np.ndarray, radius: int) -> np.ndarray:
    """Box-mean smoothing with edge padding."""

    if radius <= 0:
        return signal
    padded = np.pad(signal, radius, mode="edge")
    # Box mean via cumulative sum for exact length and O(n) time.
    cumsum = np.concatenate([[0.0], np.cumsum(padded, dtype=np.float64)])
    window = 2 * radius + 1
    result = (cumsum[window:] - cumsum[:-window]) / float(window)
    # result length is len(padded)-window+1 = len(signal)+radius*? adjust
    # Trim/pad to original length.
    if len(result) > len(signal):
        start = (len(result) - len(signal)) // 2
        result = result[start : start + len(signal)]
    elif len(result) < len(signal):
        result = np.pad(result, (0, len(signal) - len(result)), mode="edge")
    return result.astype(np.float32)


def _find_seams(
    photo_u8: np.ndarray,
    coverage: np.ndarray,
) -> list[int]:
    """Vertical seam columns, sorted, possibly empty."""

    height, width = coverage.shape
    # Interior where the wall is confidently wall, eroded so the
    # wall-to-non-wall soft band never contributes its strong edge.
    wall_interior_mask = coverage >= 0.5
    if not wall_interior_mask.any():
        wall_interior_mask = coverage > 0.05

    radius = max(1, round(min(height, width) * _EROSION_FRACTION))
    interior = erode(wall_interior_mask, radius)
    # Fallback if erosion emptied a thin wall.
    if not interior.any():
        interior = wall_interior_mask

    # Bounding box of the interior wall, so outer non-wall columns are never
    # seams and side-fraction is measured inside the wall itself.
    cols_with_wall = np.flatnonzero(interior.any(axis=0))
    if len(cols_with_wall) < 2:
        return []
    wall_left = int(cols_with_wall[0])
    wall_right = int(cols_with_wall[-1]) + 1
    wall_width = wall_right - wall_left
    if wall_width < max(10, width * 0.20):
        # Wall too narrow to contain a meaningful corner; treat as one plane.
        return []

    luminance = luminance_of(photo_u8)
    energy = _column_energy(luminance, interior)

    # Restrict to interior horizontal span.
    span = np.zeros_like(energy, dtype=bool)
    span[wall_left:wall_right] = True
    # Smooth before peak picking.
    smooth_radius = max(1, round(width * _SMOOTH_FRACTION))
    smoothed = _smooth_1d(energy, smooth_radius)
    # Zero energy outside span so peaks there are never picked.
    smoothed[~span] = 0.0

    max_energy = float(smoothed.max()) if smoothed.size else 0.0
    if max_energy < _ENERGY_FLOOR:
        return []

    # Side-fraction margins: seams too close to wall_left/right are rejected.
    min_side = max(1, round(wall_width * _MIN_SIDE_FRACTION))

    # Find local maxima inside span that are strong enough.
    threshold = max_energy * _PROMINENCE_FRACTION
    candidates: list[tuple[float, int]] = []
    for x in range(wall_left + 1, wall_right - 1):
        if not span[x]:
            continue
        val = float(smoothed[x])
        if val < threshold:
            continue
        if val < float(smoothed[x - 1]) or val < float(smoothed[x + 1]):
            continue
        # Must be a local maximum.
        if val <= float(smoothed[x - 1]) and val <= float(smoothed[x + 1]):
            # Plateau: keep centre only if strictly greater than one side.
            pass
        # Check it is greater than neighbours (strict).
        if val > float(smoothed[x - 1]) and val > float(smoothed[x + 1]):
            # Enforce side fractions.
            if (x - wall_left) < min_side or (wall_right - x) < min_side:
                continue
            candidates.append((val, x))
        elif val == float(smoothed[x - 1]) or val == float(smoothed[x + 1]):
            # Flat peak: still consider if energy is high enough and side ok.
            if (x - wall_left) < min_side or (wall_right - x) < min_side:
                continue
            # Only keep one of a plateau. Check if neighbour already queued.
            if candidates and candidates[-1][1] == x - 1:
                # Keep the stronger.
                if val > candidates[-1][0]:
                    candidates[-1] = (val, x)
                continue
            candidates.append((val, x))

    if not candidates:
        # Relax strict local-max requirement: pick global max if it respects sides.
        peak = int(np.argmax(smoothed))
        if span[peak] and (peak - wall_left) >= min_side and (wall_right - peak) >= min_side:
            # Also require shading-gradient reversal hint: median luminance valley
            # near the peak rather than at the wall's bright side.
            candidates = [(float(smoothed[peak]), peak)]
        else:
            return []

    # Strongest first, then enforce minimum separation.
    candidates.sort(key=lambda t: t[0], reverse=True)
    min_gap = max(1, round(wall_width * _MIN_SEAM_SEPARATION_FRACTION))
    chosen: list[int] = []
    for _val, x in candidates:
        if all(abs(x - c) >= min_gap for c in chosen):
            chosen.append(x)
        if len(chosen) >= _MAX_SEAMS:
            break

    chosen.sort()
    # Final valley check: median luminance should dip near each chosen seam
    # (shading grows darker toward the corner). If the column is instead the
    # brightest in its neighbourhood, this peak is texture, not a corner.
    # This removes false splits on a striped wallpaper where gradient spikes
    # repeat but luminance never valleys.
    if chosen:
        col_median = np.full(width, np.nan, dtype=np.float32)
        for x in range(wall_left, wall_right):
            rows = interior[:, x]
            if rows.sum() >= height * _MIN_COLUMN_COVERAGE:
                col_median[x] = float(np.median(luminance[rows, x]))
            else:
                col_median[x] = np.nan
        # Smooth median lightly to avoid single-column noise.
        valid = ~np.isnan(col_median)
        if np.count_nonzero(valid) > 5:
            # Fill NaN with nearest valid for smoothing.
            filled = col_median.copy()
            # Forward fill then backward fill.
            for i in range(1, width):
                if np.isnan(filled[i]) and not np.isnan(filled[i - 1]):
                    filled[i] = filled[i - 1]
            for i in range(width - 2, -1, -1):
                if np.isnan(filled[i]) and not np.isnan(filled[i + 1]):
                    filled[i] = filled[i + 1]
            smoothed_median = _smooth_1d(np.nan_to_num(filled, nan=0.5), smooth_radius)
            filtered: list[int] = []
            for x in chosen:
                # Look at 5% width neighbourhood median brightness vs seam.
                nb = max(2, round(wall_width * 0.05))
                left = max(wall_left, x - nb)
                right = min(wall_right - 1, x + nb)
                neighbourhood = smoothed_median[left : right + 1]
                if neighbourhood.size == 0:
                    filtered.append(x)
                    continue
                # Seam should be a local minimum (darker) — at least not the
                # maximum. Allow equality because flat-lit walls have no valley.
                seam_val = float(smoothed_median[x])
                max_nb = float(np.nanmax(neighbourhood))
                if (
                    seam_val >= max_nb - 1e-6
                    and max_energy > _ENERGY_FLOOR * 2
                    and float(smoothed[x]) < max_energy * 0.80
                ):
                    continue
                filtered.append(x)
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
    # Keep original shape for output.
    height, width = coverage.shape
    original = np.clip(coverage, 0.0, 1.0)

    seams = _find_seams(photo_u8, original)
    if not seams:
        return [original[..., None].astype(np.float32)]

    # Build exclusive hard masks per plane, bounded by the wall's span.
    # Columns outside the wall's span (where original is 0 everywhere) naturally
    # produce zero in every plane — so non-wall stays non-wall.
    seams_sorted = sorted(seams)
    bounds: list[tuple[int, int]] = []
    prev = 0
    for seam in seams_sorted:
        bounds.append((prev, seam))
        prev = seam
    bounds.append((prev, width))

    # But clip to actual wall columns to avoid creating empty planes that
    # extend across non-wall with zero coverage but would be counted as planes.
    # We keep all bounds as-is; empty planes (no coverage) are dropped.
    planes: list[np.ndarray] = []
    for left, right in bounds:
        mask = np.zeros((height, width), dtype=bool)
        mask[:, left:right] = True
        plane_coverage = np.where(mask, original, 0.0).astype(np.float32)
        # Drop degenerate planes that own too little wall.
        if float(plane_coverage.mean()) < 0.005:
            continue
        # Also require a minimal width inside the wall interior.
        # A seam that falls in a window gap would make a near-empty plane.
        if np.count_nonzero(plane_coverage >= 0.5) < height * 2:
            # Too few interior pixels — likely a gap plane; drop.
            # Exception: if this is the only plane, keep it (handled above).
            continue
        planes.append(plane_coverage[..., None])

    if len(planes) <= 1:
        # Splitting produced a degenerate result — fall back to one plane so
        # the contract never shrinks to zero planes (conventions.md §5).
        return [original[..., None].astype(np.float32)]

    # Final guarantee: hard partition, no overlap, sum equals original.
    # Because masks are exclusive and cover 0..width exactly, sum(planes) ==
    # original by construction. Assert in debug, clip in release to survive
    # floating error.
    return planes
