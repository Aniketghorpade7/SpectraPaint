"""Colour science the render engine is pinned to.

The spec (docs/specs/v1-spectrapaint.md, "Colour management") pins two things
that library defaults would gloss over: the **piecewise sRGB transfer function**
-- never a 2.2 power curve -- and the Lab reference white **D65, 2° observer**.

The render engine works in linear RGB (issue #3 criterion 2); the Lab constants
live here so the Catalogue work that stores and compares Shades is held to the
same pin. Nothing in this module does I/O; every function is pure numpy.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Lab reference white: D65, 2° observer (CIE 1931).
# Pinned here; no call site may fall back to a library default.
# ---------------------------------------------------------------------------
D65_2DEGREE_XY: tuple[float, float] = (0.3127, 0.3290)
D65_2DEGREE_XYZ: tuple[float, float, float] = (0.95047, 1.0, 1.08883)

# ---------------------------------------------------------------------------
# Piecewise sRGB transfer function (IEC 61966-2-1), exactly as the spec pins it.
# ---------------------------------------------------------------------------
_LINEAR_SLOPE = 12.92
_ENCODED_TRANSITION = 0.04045  # sRGB value where the two branches meet
_DECODED_TRANSITION = 0.0031308  # linear value where the two branches meet
_GAMMA = 2.4


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    """sRGB (0..1) to linear light, using the piecewise curve.

    Branch points are the real ones (0.04045 / 12.92); a 2.2 power curve is not
    a substitute and is rejected by the tests.
    """
    # np.where evaluates both branches, so the power is fed a base floored at the transition
    # point. Values at or below it take the linear branch regardless; without the floor a negative
    # input raises an invalid-value warning computing a result that is then discarded.
    above = np.maximum(x, _ENCODED_TRANSITION)
    return np.where(
        x <= _ENCODED_TRANSITION,
        x / _LINEAR_SLOPE,
        ((above + 0.055) / 1.055) ** _GAMMA,
    )


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    """Linear light (0..1) to sRGB; the inverse of :func:`srgb_to_linear`.

    Inputs are clipped to (0, 1) on a copy -- the caller's array is never
    mutated, keeping the engine pure (issue #3 criterion 1).
    """
    x = np.clip(x, 0.0, 1.0)
    return np.where(
        x <= _DECODED_TRANSITION,
        _LINEAR_SLOPE * x,
        1.055 * x ** (1.0 / _GAMMA) - 0.055,
    )


# ---------------------------------------------------------------------------
# Lab -> linear RGB. The Catalogue stores Shades in CIELAB (the spec's colour
# management table); the engine works in linear RGB (issue #3 criterion 2).
# The decode sits here so the render path is held to the same D65, 2 degree
# pin as everything else in this module.
# ---------------------------------------------------------------------------
_LAB_EPSILON = 216.0 / 24389.0  # (6/29)^3 -- the Lab branch point
_LAB_KAPPA = 24389.0 / 27.0  # 116 * (6/29)^3 -- the linear-branch slope


def lab_to_linear_rgb(lab: np.ndarray) -> np.ndarray:
    """Decode CIELAB (D65, 2 degree observer) to linear RGB (0..1).

    ``lab`` is an (..., 3) array of L*, a*, b* values as the Catalogue stores
    them. Output is linear RGB, clipped to (0, 1) on a copy -- a Lab value
    outside the sRGB gamut cannot be displayed, and out-of-range lights would
    poison the render maths.
    """
    lab = np.asarray(lab, dtype=np.float64)
    l_star = lab[..., 0:1]
    a_star = lab[..., 1:2]
    b_star = lab[..., 2:3]

    f_y = (l_star + 16.0) / 116.0
    f_x = f_y + a_star / 500.0
    f_z = f_y - b_star / 200.0

    def _inverse_lab(f: np.ndarray) -> np.ndarray:
        return np.where(
            f**3 > _LAB_EPSILON,
            f**3,
            (116.0 * f - 16.0) / _LAB_KAPPA,
        )

    xyz = np.concatenate(
        [
            D65_2DEGREE_XYZ[0] * _inverse_lab(f_x),
            D65_2DEGREE_XYZ[1] * _inverse_lab(f_y),
            D65_2DEGREE_XYZ[2] * _inverse_lab(f_z),
        ],
        axis=-1,
    )

    # sRGB primary matrix (IEC 61966-2-1): XYZ -> linear sRGB.
    linear = xyz @ np.array(
        [
            [3.2404542, -1.5371385, -0.4985314],
            [-0.9692660, 1.8760108, 0.0415560],
            [0.0556434, -0.2040259, 1.0572252],
        ]
    )
    return np.clip(linear, 0.0, 1.0)
