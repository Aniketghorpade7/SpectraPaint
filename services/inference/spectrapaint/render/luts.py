"""Lookup tables for both gamma directions.

The spec (docs/specs/v1-spectrapaint.md, "Performance") makes LUTs mandatory:
256 entries for linearising 8-bit input -- exact, since photos are 8-bit -- and
~4096 for encoding, because the encode runs on every Shade tap and is ~38% of
the per-tap path.

Both tables are built exactly once, lazily, from the pinned piecewise transfer
function in :mod:`spectrapaint.render.colour`. Nothing here does I/O.
"""

from functools import cache

import numpy as np

from spectrapaint.render.colour import linear_to_srgb, srgb_to_linear

LINEARISE_ENTRIES = 256  # 8-bit input: exact, one entry per possible byte value
ENCODE_ENTRIES = 4096  # ~38% of the per-tap path; the larger table keeps error tiny


@cache
def _linearise_table() -> np.ndarray:
    """sRGB (0..255) -> linear float32, one row per byte value."""
    grid = np.linspace(0.0, 1.0, LINEARISE_ENTRIES, dtype=np.float64)
    return srgb_to_linear(grid).astype(np.float32)


@cache
def _encode_table() -> np.ndarray:
    """Linear 0..1 -> sRGB float32, 4096 entries, piecewise-exact."""
    grid = np.linspace(0.0, 1.0, ENCODE_ENTRIES, dtype=np.float64)
    return linear_to_srgb(grid).astype(np.float32)


def linearise_u8(photo_u8: np.ndarray) -> np.ndarray:
    """Linearise an 8-bit photo (HxWx3 uint8) via the 256-entry LUT.

    Photos arrive as uint8, so a per-pixel pow is never needed.
    """
    table = _linearise_table()
    return table[photo_u8]


def encode_srgb(linear: np.ndarray) -> np.ndarray:
    """Encode linear float32 (0..1) to sRGB via the 4096-entry LUT.

    The table is reached by one index + gather, exactly as the latency spike
    does -- that is the whole point of the LUT path. NaN and infinities clamp
    to black/white instead of poisoning the index, and round-to-nearest halves
    the worst-case table-quantisation error. The caller's array is never
    mutated (issue #3 criterion 1); ``np.nan_to_num`` copies by default.
    """
    x = np.nan_to_num(linear, nan=0.0, posinf=1.0, neginf=0.0)
    x = np.clip(x, 0.0, 1.0)
    idx = np.floor(x * (ENCODE_ENTRIES - 1) + 0.5).astype(np.int32)
    return _encode_table()[idx]
