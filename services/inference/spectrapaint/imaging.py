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
