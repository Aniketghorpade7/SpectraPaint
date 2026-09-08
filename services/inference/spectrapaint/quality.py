"""Judging whether a Room Photo is usable, without ever refusing it.

design-decisions.md, "never dead-end": *"Photo unusable (dark, blurred, heavy HDR) → Proceed
anyway with a quiet quality note; never refuse outright."* Preparation still produces Wall Planes
from a poor photo if it can; this module's only job is to say, in plain language, why a repaint
might look rougher than usual (conventions.md §5 — plain language, no model or technique named).

Three checks, run once per photo at preview scale on the plain sRGB pixels — this is about what
the Dealer's phone actually captured, not the render engine's linear light (that distinction is
:mod:`spectrapaint.render`'s, not this one's). Whichever check fires first is the one note shown: a
photo rarely needs to hear it is dark *and* blurred *and* clipped, and stacking every reason would
read as nagging rather than help.

Thresholds are picked plausibly rather than measured, in the sense docs/design-decisions.md §12
describes for the render engine's own tunable constants — this project has no labelled corpus of
bad photos yet (see docs/technical-difficulties.md and issue #15's fixture gap). Revisit against
real photographs once collected.
"""

from __future__ import annotations

import numpy as np

# Mean perceptual luminance (0-255, sRGB as captured) below this reads as too dark to judge paint
# colour by.
DARK_LUMINANCE_THRESHOLD = 40.0

# Above this fraction of pixels sitting within CLIPPED_LOW/CLIPPED_HIGH of pure black or pure white,
# a photo is treated as heavily clipped — blown highlights or crushed shadows, the "heavy HDR" case
# design-decisions.md names.
CLIPPED_PIXEL_FRACTION = 0.15
CLIPPED_LOW = 8
CLIPPED_HIGH = 247

# Variance of the Laplacian below this reads as too little edge energy to be in focus. Computed on
# the preview-scale luminance image, so the threshold is stable across photos — the scale is already
# fixed upstream (api/preparation.py's MAX_PREPARED_DIMENSION) before this ever runs.
BLUR_VARIANCE_THRESHOLD = 35.0

MESSAGE_PHOTO_DARK = (
    "This photo is quite dark, so the colours shown may look muted. It can still be used — a "
    "brighter photo will give a truer result."
)
MESSAGE_PHOTO_CLIPPED = (
    "This photo has very bright or very dark areas with no detail in them, so those areas may not "
    "repaint convincingly. It can still be used — a more evenly lit photo will look better."
)
MESSAGE_PHOTO_BLURRY = (
    "This photo looks a little out of focus, so wall edges may come out rougher than usual. It can "
    "still be used — a sharper photo will give a cleaner result."
)


def assess_quality(srgb: np.ndarray) -> str | None:
    """One plain-language note if this photo is worth a quiet warning, else ``None``.

    Never raises and never blocks preparation — see the module docstring. Checked in the order a
    Dealer would notice the problem: a dark photo is usually dark before anything else about it is
    visible at all, clipping is visible next, and focus is the subtlest of the three.
    """

    luminance = _luminance(srgb)

    if float(luminance.mean()) < DARK_LUMINANCE_THRESHOLD:
        return MESSAGE_PHOTO_DARK

    if _clipped_fraction(luminance) > CLIPPED_PIXEL_FRACTION:
        return MESSAGE_PHOTO_CLIPPED

    if _laplacian_variance(luminance) < BLUR_VARIANCE_THRESHOLD:
        return MESSAGE_PHOTO_BLURRY

    return None


def _luminance(srgb: np.ndarray) -> np.ndarray:
    """Perceptual grey in the photo's own captured sRGB, HxW."""

    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    return (srgb.astype(np.float32) * weights).sum(axis=-1)


def _clipped_fraction(luminance: np.ndarray) -> float:
    clipped = (luminance <= CLIPPED_LOW) | (luminance >= CLIPPED_HIGH)
    return float(clipped.mean())


def _laplacian_variance(luminance: np.ndarray) -> float:
    """A cheap, dependency-free sharpness score.

    The discrete Laplacian kernel ``[[0,1,0],[1,-4,1],[0,1,0]]`` responds strongly at edges and
    weakly on smooth or blurred regions; its variance across the photo is the standard blur proxy.
    Written out with numpy slicing rather than taken from a library, the same reasoning as
    :mod:`spectrapaint.imaging` — the service depends on numpy and Pillow only.
    """

    padded = np.pad(luminance, 1, mode="edge")
    laplacian = (
        padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:] - 4 * luminance
    )
    return float(laplacian.var())


__all__ = [
    "MESSAGE_PHOTO_BLURRY",
    "MESSAGE_PHOTO_CLIPPED",
    "MESSAGE_PHOTO_DARK",
    "assess_quality",
]
