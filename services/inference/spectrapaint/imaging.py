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
