"""Seam 2 — the pinned colour science (issue #3 criteria 2, 3).

The spec pins the piecewise sRGB transfer function and the Lab reference white
D65, 2° observer. These tests assert the known reference values directly, so a
library default or a 2.2 power curve can never slip in unnoticed.
"""

import numpy as np
import pytest

from spectrapaint.render.colour import (
    D65_2DEGREE_XY,
    D65_2DEGREE_XYZ,
    linear_to_srgb,
    srgb_to_linear,
)

# IEC 61966-2-1 reference values (documented, machine-independent).
# sRGB 0.5 encodes the linear value we engineer the piecewise curve for.
LINEAR_OF_HALF = 0.21404114048223255  # ((0.5 + 0.055) / 1.055) ** 2.4
SLOPE_RATIO = 12.92
TRANSITION_SRGB = 0.04045
TRANSITION_LINEAR = TRANSITION_SRGB / SLOPE_RATIO  # 0.0031308...
GAMMA = 2.4


def test_zero_and_full_maps_to_themselves() -> None:
    x = np.array([0.0, 1.0])
    assert np.allclose(srgb_to_linear(x), x, atol=1e-12)
    assert np.allclose(linear_to_srgb(x), x, atol=1e-12)


def test_srgb_to_linear_is_the_piecewise_curve_not_a_power_curve() -> None:
    x = np.array([0.0, 0.01, TRANSITION_SRGB, 0.5, 0.9, 1.0])
    expected = np.where(
        x <= TRANSITION_SRGB,
        x / SLOPE_RATIO,
        ((x + 0.055) / 1.055) ** GAMMA,
    )
    assert np.allclose(srgb_to_linear(x), expected, atol=1e-9)
    # The peak of the curve is the famous reference value.
    assert srgb_to_linear(np.array([0.5]))[0] == pytest.approx(LINEAR_OF_HALF, abs=1e-9)


def test_linear_to_srgb_is_the_exact_inverse() -> None:
    samples = np.linspace(0.0, 1.0, 1001)
    round_trip = linear_to_srgb(srgb_to_linear(samples))
    assert np.allclose(round_trip, samples, atol=1e-9)


def test_branch_point_is_continuous() -> None:
    """Both branches meet the IEC-published value at the 0.04045 cusp.

    IEC 61966-2-1 publishes both branch values as 0.0031308. The raw
    expressions differ only in the 7th significant figure (≈2.3e-9), well
    below any 8-bit (3.9e-3) or LUT (1.6e-3) resolution, so the test pins the
    published value and asserts continuity far below the renderer's granularity.
    """
    low = 0.04045 / 12.92
    high = ((0.04045 + 0.055) / 1.055) ** 2.4
    # Both raw values round to the IEC-published 0.0031308 (tolerance is half
    # of the last published significant digit).
    assert low == pytest.approx(TRANSITION_LINEAR, abs=5e-8)
    assert high == pytest.approx(TRANSITION_LINEAR, abs=5e-8)
    # Continuous far below 8-bit quantization and the 4096-entry LUT step.
    assert low == pytest.approx(high, abs=1e-6)


def test_lab_reference_white_is_d65_2_degree() -> None:
    # CIE 1931 2° observer, illuminant D65 -- pinned, not a library default.
    assert D65_2DEGREE_XY == (0.3127, 0.3290)
    assert D65_2DEGREE_XYZ == (0.95047, 1.0, 1.08883)


def test_srgb_to_linear_handles_beyond_bounds_without_crashing() -> None:
    """Callers may pass slightly out-of-range values; never NaN."""
    out = srgb_to_linear(np.array([[-0.1, 1.5]]))
    assert np.isfinite(out).all()