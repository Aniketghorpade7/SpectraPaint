"""Seam 2 — photo quality assessment (issue #15, "never dead-end").

Pure function, synthetic inputs. What matters is behaviour a Dealer would recognise — a dark photo
reads as dark, a sharp photo reads as sharp — not the exact numbers the heuristic computes inside.
"""

from __future__ import annotations

import numpy as np

from spectrapaint.quality import (
    MESSAGE_PHOTO_BLURRY,
    MESSAGE_PHOTO_CLIPPED,
    MESSAGE_PHOTO_DARK,
    assess_quality,
)

H, W = 90, 120


def _flat(value: int) -> np.ndarray:
    return np.full((H, W, 3), value, dtype=np.uint8)


def _checkerboard(low: int, high: int, square: int = 4) -> np.ndarray:
    """Sharp, high-frequency edges everywhere — the opposite of a blurred photo."""
    y, x = np.mgrid[0:H, 0:W]
    tile = ((y // square) + (x // square)) % 2
    grey = np.where(tile == 0, low, high).astype(np.uint8)
    return np.repeat(grey[:, :, None], 3, axis=2)


def _well_lit_wall() -> np.ndarray:
    """A plausible, unremarkable wall photo: mid-brightness, some texture, no clipping."""
    rng = np.random.default_rng(0)
    base = 170
    noise = rng.integers(-6, 7, size=(H, W, 3))
    return np.clip(base + noise, 0, 255).astype(np.uint8)


def test_a_well_lit_sharp_photo_gets_no_note() -> None:
    assert assess_quality(_well_lit_wall()) is None


def test_a_dark_photo_gets_a_dark_note() -> None:
    assert assess_quality(_flat(10)) == MESSAGE_PHOTO_DARK


def test_darkness_is_checked_before_anything_else() -> None:
    """A dark, flat photo is also technically blurred (no edge energy at all) — the Dealer should
    hear the more obvious problem, not both."""
    assert assess_quality(_flat(5)) == MESSAGE_PHOTO_DARK


def test_a_heavily_clipped_photo_gets_a_clipped_note() -> None:
    # Half pure black, half pure white: no mid-tones, nothing recoverable in either half.
    photo = np.zeros((H, W, 3), dtype=np.uint8)
    photo[:, : W // 2] = 0
    photo[:, W // 2 :] = 255
    assert assess_quality(photo) == MESSAGE_PHOTO_CLIPPED


def test_a_blurred_photo_gets_a_blurry_note() -> None:
    # Bright enough and not clipped, but perfectly flat: no edge energy anywhere, which is what an
    # out-of-focus photo of real texture would collapse to.
    assert assess_quality(_flat(150)) == MESSAGE_PHOTO_BLURRY


def test_a_sharp_high_contrast_photo_is_not_mistaken_for_dark_or_clipped() -> None:
    # Plenty of edge energy and a mid-range mean, so none of the three checks should misfire.
    assert assess_quality(_checkerboard(low=90, high=180)) is None


def test_never_raises_on_a_single_pixel_photo() -> None:
    # The smallest possible input a decoded photo could ever be — no wide-window filter here may
    # assume a minimum size the way a real photo happens to satisfy.
    assess_quality(np.full((1, 1, 3), 128, dtype=np.uint8))
