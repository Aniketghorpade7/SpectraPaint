"""How much a matte's razor edges line up with SegFormer's 128x128 output grid (issue #51).

Shared by the fast-lane unit tests (synthetic mattes, ``test_matte_edges.py``) and the models lane
(real photographs, ``tests/api/test_walls.py``), so the number means the same thing in both. Not a
test module: pytest does not collect it.

**The figure is only meaningful next to its chance level.** Grid lines fall every ~10 px on a
1280 px photograph and an edge counts as "on" one when it lies within ``tolerance`` px of it, so an
edge placed *at random* lands on a line about 30% of the time. A matte with no relationship to the
grid at all therefore scores ~0.30, not 0 — and the issue's acceptance wording ("at most 0.10 on
every fixture") cannot be met on any photograph that has razor edges. What the staircase bug did
was push the fraction to 0.5–0.66 on real photographs, which is a *surplus over chance* of 0.2–0.36.
That surplus, :func:`grid_excess`, is what the models lane asserts on.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# The grid the checkpoint's stride-4 head produces for the 512x512 input it expects.
SEMANTIC_GRID = 128


def grid_lines(dimension: int) -> set[int]:
    """Photo positions where a nearest-upsampled SEMANTIC_GRID axis changes value.

    Derived from Pillow's own NEAREST mapping rather than assumed to be multiples of the grid size:
    on a 1600px photo a source column moves every 12.5px, not every 128px, and a metric that checked
    the wrong positions reports near-zero for a mask that is entirely staircase.
    """
    source = np.arange(SEMANTIC_GRID).reshape(-1, 1).astype(np.float32)
    resized = Image.fromarray(source, mode="F").resize(
        (1, dimension), resample=Image.Resampling.NEAREST
    )
    return set(np.nonzero(np.diff(np.asarray(resized, dtype=np.float32).ravel().astype(int)))[0])


def _near(indices: np.ndarray, dimension: int, tolerance: int) -> int:
    lines = np.asarray(sorted(grid_lines(dimension)))
    distances = np.abs(indices[:, None] - lines[None, :]).min(axis=1)
    return int((distances <= tolerance).sum())


def _chance(dimension: int, tolerance: int) -> float:
    """The share of this axis's edge positions that lie within ``tolerance`` of a grid line."""
    positions = np.arange(dimension - 1)
    return _near(positions, dimension, tolerance) / len(positions)


def edge_on_grid(alpha: np.ndarray, tolerance: int = 1) -> tuple[float, float, int]:
    """``(fraction, chance, edges)`` for a matte's *razor* edges (a jump over 0.5).

    ``fraction`` is the share of razor edges within ``tolerance`` px of a grid line, counted over
    edge pixels rather than over distinct rows and columns, because that is what the figure in
    docs/bugs/root-causes.md §A means and what it took to reproduce its 75–84%: a staircase crosses
    many pixel positions per step, and counting distinct rows instead divides the answer by the step
    length. ``tolerance`` is 1 rather than 0 because a nearest-upsampled boundary lands on a grid
    line and a bilinear one lands between two, and only the former is the defect.

    ``chance`` is the fraction a matte with the same edges *unrelated to the grid* would score:
    each axis's own share of positions near a line, weighted by how many edges run across it.

    A matte with no razor edge at all is soft along every boundary — the best possible answer, not a
    missing measurement — and is ``(0.0, 0.0, 0)``.
    """
    rows = np.nonzero(np.abs(np.diff(alpha, axis=0)) > 0.5)[0]
    cols = np.nonzero(np.abs(np.diff(alpha, axis=1)) > 0.5)[0]
    total = len(rows) + len(cols)
    if total == 0:
        return 0.0, 0.0, 0

    on_grid = _near(rows, alpha.shape[0], tolerance) + _near(cols, alpha.shape[1], tolerance)
    chance = (
        len(rows) * _chance(alpha.shape[0], tolerance)
        + len(cols) * _chance(alpha.shape[1], tolerance)
    ) / total
    return on_grid / total, chance, total


def edge_on_grid_fraction(alpha: np.ndarray, tolerance: int = 1) -> tuple[float, int]:
    """``(fraction, edges)`` — see :func:`edge_on_grid`, without the chance level."""
    fraction, _chance_level, total = edge_on_grid(alpha, tolerance)
    return fraction, total


def grid_excess(alpha: np.ndarray, tolerance: int = 1) -> tuple[float, int]:
    """``(surplus over chance, edges)``: how much more grid-aligned than an unrelated matte.

    0 is a matte whose edges know nothing about the grid; the nearest-neighbour staircase scored
    0.2–0.36 on the fixtures. Can be slightly negative on a few hundred edges — sampling noise, not
    anti-alignment.
    """
    fraction, chance, total = edge_on_grid(alpha, tolerance)
    return fraction - chance, total
