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
    lab_to_linear_rgb,
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


# ---------------------------------------------------------------------------
# Lab -> linear RGB. Untested until #7, which is how a transposed primary matrix survived from #3:
# every Shade decoded to the wrong colour — a near-white Shade came out hot pink — while the render
# tests passed, because they assert that a wall stopped being grey and that the two modes differ,
# and both of those are true of the wrong colour too (difficulty 16).
# ---------------------------------------------------------------------------

# Reference values, computed from the CIE formulae by hand rather than from this module: Lab -> XYZ
# with the D65 2 degree white, XYZ -> linear sRGB with the IEC 61966-2-1 primaries.
_LAB_TO_LINEAR_REFERENCE = [
    ((100.0, 0.0, 0.0), (1.0, 1.0, 1.0)),  # the reference white itself
    ((50.0, 0.0, 0.0), (0.184, 0.184, 0.184)),  # mid grey stays neutral
    ((97.0, 0.49, 0.85), (0.940, 0.921, 0.911)),  # PS-1001, a Catalogue near-white
    ((66.0, 38.14, 22.02), (0.821, 0.230, 0.198)),  # PS-6010, the reddest Shade in the Catalogue
    ((80.0, -0.0, -30.94), (0.360, 0.584, 1.0)),  # PS-12011, the bluest
]


@pytest.mark.parametrize(("lab", "expected"), _LAB_TO_LINEAR_REFERENCE)
def test_lab_decodes_to_the_reference_linear_rgb(
    lab: tuple[float, float, float], expected: tuple[float, float, float]
) -> None:
    """The decode matches values worked out from the standard, not from this implementation."""

    decoded = lab_to_linear_rgb(np.asarray(lab, dtype=np.float64))
    assert decoded == pytest.approx(np.asarray(expected), abs=1e-3)


@pytest.mark.parametrize("l_star", [0.0, 18.0, 50.0, 82.0, 97.0, 100.0])
def test_a_neutral_lab_decodes_to_equal_channels(l_star: float) -> None:
    """a* = b* = 0 is grey by definition, so the three channels must come out equal.

    The property that catches a transposed primary matrix on the first run, which is why it is here
    and not only in the reference table above: a matrix read by columns instead of rows turns every
    grey into a colour, and a table of expected values can always be regenerated from the broken
    implementation by somebody who assumes it is right.
    """

    decoded = lab_to_linear_rgb(np.asarray([l_star, 0.0, 0.0], dtype=np.float64))
    assert decoded[0] == pytest.approx(decoded[1], abs=1e-6)
    assert decoded[1] == pytest.approx(decoded[2], abs=1e-6)


def test_lab_decodes_a_stack_of_shades_at_once() -> None:
    """The Catalogue decodes many Shades in one call, so the shape must survive."""

    stack = np.asarray([lab for lab, _ in _LAB_TO_LINEAR_REFERENCE], dtype=np.float64)
    decoded = lab_to_linear_rgb(stack)
    assert decoded.shape == stack.shape
    for row, (_, expected) in zip(decoded, _LAB_TO_LINEAR_REFERENCE, strict=True):
        assert row == pytest.approx(np.asarray(expected), abs=1e-3)
