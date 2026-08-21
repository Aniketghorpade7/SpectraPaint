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

"Coincide" is the operative word, and it is what the implementation checks.
Each cue is computed as a signal over columns of the eroded wall interior:

* ``energy[x]`` — mean ``|dL/dx|`` over the interior rows of column x. The
  vertical-edge cue, on raw luminance: a corner is often only a few pixels
  wide and smoothing before thresholding dilutes it away.
* ``valley[x]`` — how far the column's median luminance sits below the
  brightest column near it. The shading cue at a point.
* ``reversal[x]`` — the smoothed column median's slope to the right of x
  minus its slope to the left, over a window either side. The shading cue as
  the ticket words it: each wall grows darker toward the corner, so the
  horizontal gradient changes sign there. A step edge (a door, a picture
  frame) has no reversal; a corner does.

No single cue survives a real photograph. On a real unoccluded corner the
strongest column energy in the whole wall sits two pixels from the corner while
no single column is a clean median minimum; on a corner behind hanging clothes
the deepest valley is the corner but the strongest reversal is a curtain fold;
on a night photograph with no second plane at all, each cue has a confident
strongest column and they point at three different places.

So a seam is where **at least two cues agree**: peaks are found per cue,
non-maximum suppressed, and grouped by proximity. A group carrying two or more
distinct cues is a corner; a group carrying one is texture. Where the group has
an energy peak, that column is the seam, because the edge localises the corner
more sharply than a shading cue can.

Seams become a hard partition of the original Alpha Matte.

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
# Interior test: a column must have this share of its rows as interior wall
# to be considered, or it is mostly window/furniture gap.
_MIN_COLUMN_COVERAGE = 0.08

# How many seams may be emitted. One, for now, which is two Wall Planes — the
# common room. Rooms with three visible walls exist and this is the number to
# raise, but not before there are fixtures with three labelled planes to raise
# it against: on the three rooms in data/fixtures/rooms a second seam is always
# a curtain fold or a stretch of wall the matte wrongly claimed (#31), never a
# third wall, so allowing two would split a two-wall room into three.
_MAX_SEAMS = 1

# How close two cues must land to count as the same corner, as a fraction of
# photo width. Wide enough that an edge and a shading valley either side of the
# same corner agree (they sat 16 px apart on the unoccluded fixture, 19 on the
# occluded one), narrow enough that a corner and a curtain fold do not.
_CUE_AGREEMENT_FRACTION = 0.03

# How many distinct cues must agree before a column is called a corner. Two, so
# a lone strong edge (a wardrobe, a door frame) does not split a wall, and a
# lone shading dip (a shadow, a stain) does not either.
_MINIMUM_AGREEING_CUES = 2

# Window either side of a column over which the median's slope is measured for
# the reversal cue, as a fraction of width. A corner's shading valley is
# rounded over tens of pixels, so the slopes either side are what identifies it;
# the single darkest column is noise-dominated and moves photo to photo.
_SLOPE_WINDOW_FRACTION = 0.03

# Cue floors, below which a peak is not evidence of anything. A flat wall's
# signals are all zero, and these are what keep it one plane. Measured on the
# fixtures: at a real corner energy was 0.0065-0.0085 and reversal 0.0024-0.0085,
# against 0.0003 and below for texture ripples on the same walls.
_ENERGY_FLOOR = 0.004
_VALLEY_DEPTH_FLOOR = 0.030
_REVERSAL_FLOOR = 0.001

# Small smoothing for the median profile, to quieten single-column texture
# without diluting a narrow corner. Fixed radius in pixels, not wall-fraction.
_MEDIAN_SMOOTH_RADIUS = 3

# How many peaks per cue are considered. Three: a corner, and two chances for
# the photograph's loudest distractions to be ranked above it.
_PEAKS_PER_CUE = 3


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


def _valley_signal(
    smoothed_median: np.ndarray,
    wall_left: int,
    wall_right: int,
    wall_width: int,
) -> np.ndarray:
    """How far each column's median luminance sits below the brightest column near it.

    The shading cue measured at a point rather than as a shape: a corner is darker than the wall
    either side of it. Kept alongside the reversal cue because the two fail differently — a corner
    lit evenly from one side has a weak valley and a clear reversal, and a corner in a room lit from
    both sides has the opposite.
    """

    radius = max(2, round(wall_width * _VALLEY_RADIUS_FRACTION))
    valley = np.zeros_like(smoothed_median, dtype=np.float32)
    for x in range(wall_left + 1, wall_right - 1):
        near_from, near_to = max(wall_left, x - radius), min(wall_right - 1, x + radius)
        neighbourhood = smoothed_median[near_from : near_to + 1]
        if neighbourhood.size:
            valley[x] = max(0.0, float(np.nanmax(neighbourhood)) - float(smoothed_median[x]))
    return valley


def _reversal_signal(
    smoothed_median: np.ndarray,
    wall_left: int,
    wall_right: int,
    window: int,
) -> np.ndarray:
    """Shading-gradient reversal per column: slope to the right minus slope to the left.

    Positive where the wall stops darkening and starts brightening, which is what a corner does to
    a horizontal luminance profile and what a step edge — a door, a picture frame, the join between
    two paints on one flat wall — does not. Slopes are least-squares fits over ``window`` columns
    either side, because a corner's valley is rounded over tens of pixels: its single darkest column
    is noise, while the slopes either side of it are stable.
    """

    reversal = np.zeros_like(smoothed_median, dtype=np.float32)
    for x in range(wall_left + 1, wall_right - 1):
        left_from, left_to = max(wall_left, x - window), x
        right_from, right_to = x + 1, min(wall_right, x + 1 + window)
        if left_to - left_from < 3 or right_to - right_from < 3:
            continue
        left = smoothed_median[left_from:left_to]
        right = smoothed_median[right_from:right_to]
        slope_left = float(np.polyfit(np.arange(left.size), left, 1)[0])
        slope_right = float(np.polyfit(np.arange(right.size), right, 1)[0])
        reversal[x] = max(0.0, slope_right - slope_left)
    return reversal


def _cue_peaks(
    signal: np.ndarray,
    low: int,
    high: int,
    floor: float,
    min_separation: int,
) -> list[int]:
    """The strongest few local maxima of one cue, non-maximum suppressed.

    Suppression before anything else is the point. Counting every dip or ripple is what made a
    photograph of a plain wall look like striped wallpaper: a real median-luminance profile has
    ten or twenty local minima, and only their strongest, well-separated few are candidates for
    being a corner.
    """

    candidates = [
        x
        for x in range(low + 1, high - 1)
        if float(signal[x]) >= floor
        and float(signal[x]) >= float(signal[x - 1])
        and float(signal[x]) >= float(signal[x + 1])
    ]
    candidates.sort(key=lambda x: float(signal[x]), reverse=True)

    kept: list[int] = []
    for x in candidates:
        if all(abs(x - other) >= min_separation for other in kept):
            kept.append(x)
        if len(kept) >= _PEAKS_PER_CUE:
            break
    return kept


def _agreeing_groups(
    peaks: dict[str, list[int]],
    tolerance: int,
) -> list[dict[str, int]]:
    """Group peaks from different cues that land close enough to be the same corner.

    One entry per group, keyed by cue name, so a group's size is the number of cues that agree and
    its members say where each of them put the corner.
    """

    groups: list[dict[str, int]] = []
    for cue, columns in peaks.items():
        for column in columns:
            for group in groups:
                centre = sum(group.values()) / len(group)
                if abs(centre - column) <= tolerance and cue not in group:
                    group[cue] = column
                    break
            else:
                groups.append({cue: column})
    return groups


def _find_seams(
    photo_u8: np.ndarray,
    coverage: np.ndarray,
) -> list[int]:
    """Vertical seam columns, sorted, possibly empty.

    A seam is a column where at least ``_MINIMUM_AGREEING_CUES`` of the three cues agree — see the
    module docstring for why no single one of them is enough on a photograph.
    """

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

    # A seam is only considered where both sides could be a plane at all, rather than where a
    # margin from the frame edge allows. A return wall is normally a narrow strip near the edge —
    # the geometry a side-fraction margin excludes structurally — so the test is plane viability.
    min_plane_width = max(1, round(wall_width * _MIN_PLANE_WIDTH_FRACTION))
    low = wall_left + min_plane_width
    high = wall_right - min_plane_width
    if high - low < 3:
        return []

    luminance = luminance_of(photo_u8)
    energy = np.nan_to_num(_column_energy(luminance, interior))
    column_median = _column_median(luminance, interior)
    smoothed_median = _smooth_1d(
        np.nan_to_num(_fill_nans_nearest(column_median), nan=0.5), _MEDIAN_SMOOTH_RADIUS
    )

    slope_window = max(4, round(width * _SLOPE_WINDOW_FRACTION))
    valley = _valley_signal(smoothed_median, wall_left, wall_right, wall_width)
    reversal = _reversal_signal(smoothed_median, wall_left, wall_right, slope_window)

    min_separation = max(1, round(wall_width * _MIN_SEAM_SEPARATION_FRACTION))
    peaks = {
        "energy": _cue_peaks(energy, low, high, _ENERGY_FLOOR, min_separation),
        "valley": _cue_peaks(valley, low, high, _VALLEY_DEPTH_FLOOR, min_separation),
        "reversal": _cue_peaks(reversal, low, high, _REVERSAL_FLOOR, min_separation),
    }
    if not any(peaks.values()):
        return []

    tolerance = max(4, round(width * _CUE_AGREEMENT_FRACTION))
    groups = [
        group
        for group in _agreeing_groups(peaks, tolerance)
        if len(group) >= _MINIMUM_AGREEING_CUES
    ]
    if not groups:
        return []

    # Rank by how strongly the cues that agree speak, each normalised by the strongest value that
    # cue reached anywhere in this wall — so the score compares "how much this corner stands out"
    # rather than adding a luminance slope to a gradient magnitude.
    signals = {"energy": energy, "valley": valley, "reversal": reversal}
    strongest = {cue: max(float(signal[low:high].max()), 1e-9) for cue, signal in signals.items()}

    def score(group: dict[str, int]) -> tuple[int, float]:
        agreement = sum(
            float(signals[cue][column]) / strongest[cue] for cue, column in group.items()
        )
        return len(group), agreement

    groups.sort(key=score, reverse=True)

    chosen: list[int] = []
    for group in groups:
        # The energy peak localises a corner more sharply than a shading cue can — the edge is the
        # corner line itself, while a valley is the shading around it — so it places the seam when
        # the group has one.
        column = group.get("energy", int(round(sum(group.values()) / len(group))))
        if all(abs(column - other) >= min_separation for other in chosen):
            chosen.append(column)
        if len(chosen) >= _MAX_SEAMS:
            break

    logger.debug(
        "seam cues: peaks=%s groups=%s chosen=%s",
        peaks,
        [sorted(group.items()) for group in groups],
        chosen,
    )
    return sorted(chosen)


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
