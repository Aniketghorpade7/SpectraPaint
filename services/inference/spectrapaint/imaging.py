"""Small image operations shared by the pipeline and the render engine.

Morphology, and nothing that knows what a wall is. It lives here rather than inside
:mod:`spectrapaint.segmentation` because the render engine needs the same erosion to find
uncontaminated wall pixels for the Base Colour, and a render module importing from the
segmentation package to borrow a loop would be a dependency in the wrong direction.

Pillow's filters are used rather than scipy's morphology: the service depends on numpy and Pillow,
both of which it already needs for photos, and adding scipy to a Dealer's installer for two
functions would be a poor trade.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter


def _apply(mask: np.ndarray, radius: int, kernel: type[ImageFilter.RankFilter]) -> np.ndarray:
    """``radius`` passes of a 3x3 rank filter.

    Repeated small kernels rather than one large one: a single filter of side 2r+1 costs r squared
    work per pixel, while r passes of a 3x3 reach the same distance for far less.
    """

    if radius <= 0 or not mask.any():
        return mask

    image = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    for _ in range(radius):
        image = image.filter(kernel(3))
    return np.asarray(image, dtype=np.uint8) > 127


def erode(mask: np.ndarray, radius: int) -> np.ndarray:
    """Shrink a boolean region by ``radius`` pixels."""
    return _apply(mask, radius, ImageFilter.MinFilter)


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Grow a boolean region by ``radius`` pixels.

    With :func:`erode`, gives a ring around a region's boundary (dilated minus eroded), which is
    how the matte's boundary band is found.
    """
    return _apply(mask, radius, ImageFilter.MaxFilter)


def blur(values: np.ndarray, radius: float) -> np.ndarray:
    """A Gaussian blur of ``values`` in [0, 1], returned as float32 at the same shape.

    The soft half of :func:`erode_round`, and the thing the Alpha Matte's exclusion ramp and its
    boundary blend are both built out of. A rank filter can only answer yes or no, so a
    morphological boundary it produces is a staircase however many times it is applied; a blur is
    continuous, and thresholding a blur at 0.5 gives the same boundary a rank filter would without
    the corners.

    Pillow's ``GaussianBlur`` only accepts ``L``, ``RGB`` and ``CMYK``, not the ``F`` mode this
    module's other resizes use — it rejects an ``F`` image outright rather than converting it. So
    the values make a round trip through 8-bit ``L``, which costs a quantisation step of 1/255. That
    is immaterial for both callers: one thresholds at 0.5, the other subtracts twice the result from
    one. Were a caller ever to need the precision back, the fix is a separable convolution in numpy
    rather than a wider ``L`` — not a wider ``L``, which buys nothing.
    """
    if radius <= 0:
        return values.astype(np.float32)
    quantised = np.clip(np.rint(values * 255.0), 0, 255).astype(np.uint8)
    blurred = Image.fromarray(quantised, mode="L").filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(blurred, dtype=np.float32) / 255.0


# The level a Gaussian's blurred profile takes one standard deviation *inside* a straight edge:
# Φ(1) for the error function. Keeping the pixels at or above it erodes by exactly ``radius``, which
# is what makes :func:`erode_round` mean the same thing as :func:`erode` — measured, not assumed,
# because neither of the two obvious thresholds works. Pillow's ``GaussianBlur(radius)`` takes
# ``radius`` as the standard deviation, so for a signed distance ``d`` inside an edge the blurred
# profile is Φ(d/radius): exactly 0.5 *on* the edge, so the obvious ``>= 0.5`` erodes by nothing at
# all, and 0.1587 — the complementary value, and equally tempting — goes the other way and dilates.
# This constant was wrong twice in that direction before it was measured rather than reasoned about,
# and because a straight edge is most of what these fixtures contain, "erodes by nearly zero" read
# as "round erosion barely changes anything" and passed a test run. It cost 0.031 of
# ``windows-with-curtains``' shadowed-wall recall while it did.
_ERODE_LEVEL = 0.8413


def erode_round(mask: np.ndarray, radius: int) -> np.ndarray:
    """Shrink a boolean region by ``radius`` pixels along a *round* structuring element.

    A rank filter shrinks along a square: the corners of the shape are removed as fast as the middle
    of a flat edge is, so a hole in a wall comes out square and the boundary of a region comes out
    stepped. Blurring and thresholding is the standard stand-in for a disc structuring element — the
    disc is the isotropic one — so the boundary follows a curve and only the curve costs anything.
    The threshold is :data:`_ERODE_LEVEL` so that the distance matches :func:`erode`; see it for why
    neither 0.5 nor its complement is the right one.

    Uses :func:`blur`, and so stays inside the numpy + Pillow rule this module's docstring sets.
    """
    if radius <= 0 or not mask.any():
        return mask
    return blur(mask.astype(np.float32), radius) >= _ERODE_LEVEL


def box_mean(values: np.ndarray, radius: int) -> np.ndarray:
    """Mean of ``values`` over a square window, in time independent of the window size.

    A summed-area table, so a wide window costs what a narrow one does. Written out rather than
    taken from a library because the service depends on numpy and Pillow only, and this is the
    one piece of the edge-aware pass that would otherwise want scipy. Accepts ``(H, W)`` or
    ``(H, W, C)``; the window always spans the two spatial axes.
    """

    padded = np.pad(
        values,
        [(radius + 1, radius + 1)] * 2 + [(0, 0)] * (values.ndim - 2),
        mode="edge",
    )
    integral = padded.cumsum(axis=0).cumsum(axis=1)

    height, width = values.shape[:2]
    side = 2 * radius + 1
    bottom = slice(side, side + height)
    top = slice(0, height)
    right = slice(side, side + width)
    left = slice(0, width)

    total = (
        integral[bottom, right]
        - integral[top, right]
        - integral[bottom, left]
        + integral[top, left]
    )
    return (total / float(side * side)).astype(np.float32)


def guided_filter(guide: np.ndarray, target: np.ndarray, radius: int, epsilon: float) -> np.ndarray:
    """Smooth ``target`` while following the edges of ``guide``.

    The standard formulation: fit ``target ≈ a * guide + b`` over every window, then average the
    coefficients. Where the guide has an edge the fit follows it; where the guide is flat the fit
    degenerates to a local mean, which is exactly the behaviour wanted — sharp at the wall's
    boundary, smooth across its shadows.
    """

    mean_guide = box_mean(guide, radius)
    mean_target = box_mean(target, radius)
    mean_product = box_mean(guide * target, radius)
    mean_square = box_mean(guide * guide, radius)

    covariance = mean_product - mean_guide * mean_target
    variance = mean_square - mean_guide * mean_guide

    a = covariance / (variance + epsilon)
    b = mean_target - a * mean_guide
    return (box_mean(a, radius) * guide + box_mean(b, radius)).astype(np.float32)
