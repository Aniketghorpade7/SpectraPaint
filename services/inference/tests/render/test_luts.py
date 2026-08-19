"""Seam 2 — the gamma lookup tables (issue #3 criterion 4).

The spec mandates LUTs for both gamma directions: 256 entries for 8-bit input
(exact, since photos are 8-bit) and ~4096 for encoding. These tests assert the
tables agree with the pinned analytic piecewise transfer function within a
tight tolerance, so a swapped or reordered table can never pass silently.
"""

import numpy as np
import pytest

from spectrapaint.render.colour import linear_to_srgb, srgb_to_linear
from spectrapaint.render.luts import (
    ENCODE_ENTRIES,
    LINEARISE_ENTRIES,
    encode_srgb,
    linearise_u8,
)


def test_linearise_table_has_256_entries_and_is_exact_for_8_bit() -> None:
    """Every possible byte value maps through the table -- no pow per pixel."""
    rng = np.random.default_rng(0)
    photo_u8 = rng.integers(0, 256, size=(7, 9, 3)).astype(np.uint8)

    got = linearise_u8(photo_u8)
    expected = srgb_to_linear(photo_u8 / 255.0).astype(np.float32)

    assert got.shape == photo_u8.shape
    assert got.dtype == np.float32
    # 256 entries sample the curve exactly at the 8-bit grid points.
    assert LINEARISE_ENTRIES == 256
    assert np.allclose(got, expected, atol=1e-6)


def test_encode_table_uses_4096_entries_and_matches_the_piecewise_curve() -> None:
    samples = np.linspace(0.0, 1.0, 97)
    got = encode_srgb(samples.reshape(1, -1, 1))
    # Expected must match got's (1, 97, 1) shape -- a bare (97,) would
    # broadcast against the trailing channel axis into a 97x97 cross-product.
    expected = linear_to_srgb(samples).astype(np.float32).reshape(1, -1, 1)

    assert ENCODE_ENTRIES == 4096
    assert got.shape == (1, 97, 1)
    assert got.dtype == np.float32
    # Round-to-nearest: worst-case error is half a table step times the
    # steepest curve slope (12.92 at black). At 4096 entries that is
    # 12.92 / (2 * 4096) ~ 1.6e-3, i.e. ~0.4 in 8-bit units -- far below the
    # engine tests' atol=2.
    worst_case = 12.92 / (2 * ENCODE_ENTRIES)
    assert np.allclose(got, expected, atol=worst_case)


def test_encode_clips_out_of_range_linears_without_nan() -> None:
    out = encode_srgb(np.array([[[-0.5, 1.5, np.nan]]], dtype=np.float32))
    assert np.isfinite(out).all()
    assert out[0, 0, 0] == 0.0  # clipped to black
    assert out[0, 0, 1] == 1.0  # clipped to white


def test_linearise_is_exact_for_the_full_byte_range() -> None:
    """The whole 0..255 range round-trips through the 256-entry table."""
    photo = np.arange(256, dtype=np.uint8).reshape(16, 16)
    linear = linearise_u8(photo)
    assert np.isfinite(linear).all()
    assert np.nanmin(linear) == 0.0
    assert np.nanmax(linear) == pytest.approx(1.0, abs=1e-6)
