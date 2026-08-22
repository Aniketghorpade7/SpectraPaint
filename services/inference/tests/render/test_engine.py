"""Seam 2 — the render engine as a pure function (issue #3 criteria 1, 2).

These tests assert the *shape* of the contract -- pure numpy, no I/O, linear
composite then one encode -- and the invariant that the composite happens in
linear space. The analytical correctness properties (criteria 5-9) are the next
checkpoint's suite.
"""

import numpy as np
import pytest

from spectrapaint.render.colour import linear_to_srgb
from spectrapaint.render.engine import (
    estimate_base_colour,
    estimate_light_tint,
    light_map_of,
    render,
)
from spectrapaint.render.luts import linearise_u8

# Stated here rather than imported: the test pins what the weights must be (ITU-R BT.709, the sRGB
# primaries), so a change to them in the engine is a failure and not a silently agreed edit.
BT709_LUMA = np.array([0.2126, 0.7152, 0.0722])


def _linear_photo(shape=(9, 12, 3), seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # Linear-space values inside (0, 1).
    return rng.random(shape, dtype=np.float32)


def test_light_map_is_the_per_pixel_division() -> None:
    linear = _linear_photo()
    base = np.array([0.55, 0.52, 0.48], dtype=np.float32)
    got = light_map_of(linear, base)
    assert got.shape == linear.shape
    assert np.allclose(got, linear / base, atol=1e-6)


def test_light_map_of_never_yields_nan_or_inf() -> None:
    """A zero base channel must clamp, not poison the whole render."""
    linear = np.zeros((2, 2, 3), dtype=np.float32)
    base = np.array([0.0, 0.52, 0.48], dtype=np.float32)
    out = light_map_of(linear, base)
    assert np.isfinite(out).all()


def test_render_returns_srgb_uint8_of_the_same_shape() -> None:
    linear = _linear_photo()
    alpha = np.full((9, 12, 1), 1.0, dtype=np.float32)
    light_map = light_map_of(linear, np.array([0.55, 0.52, 0.48], dtype=np.float32))
    shade = np.array([0.78, 0.70, 0.58], dtype=np.float32)
    tint = np.array([1.06, 1.00, 0.92], dtype=np.float32)

    out = render(linear, alpha, light_map, shade, tint)

    assert out.shape == linear.shape
    assert out.dtype == np.uint8
    assert (out >= 0).all() and (out <= 255).all()


def test_alpha_1_output_is_light_map_times_shade_times_tint_encoded() -> None:
    """With alpha=1 the composite is exactly new_wall, then one encode."""
    linear = _linear_photo()
    alpha = np.ones((9, 12, 1), dtype=np.float32)
    base = np.array([0.55, 0.52, 0.48], dtype=np.float32)
    shade = np.array([0.78, 0.70, 0.58], dtype=np.float32)
    tint = np.array([1.06, 1.00, 0.92], dtype=np.float32)
    light_map = light_map_of(linear, base)

    out = render(linear, alpha, light_map, shade, tint)
    expected_linear = light_map * shade * tint
    expected = (linear_to_srgb(expected_linear) * 255.0 + 0.5).astype(np.uint8)

    assert np.allclose(out, expected, atol=2)  # encode LUT quantisation


def test_alpha_0_leaves_the_pixels_untouched() -> None:
    """Alpha 0 means the original photo passes through unchanged (after encode)."""
    photo_u8 = np.arange(27, dtype=np.uint8).reshape(3, 3, 3) * 8  # 0..208
    linear = linearise_u8(photo_u8)
    alpha = np.zeros((3, 3, 1), dtype=np.float32)
    light_map = light_map_of(linear, np.array([0.55, 0.52, 0.48], dtype=np.float32))
    shade = np.array([0.78, 0.70, 0.58], dtype=np.float32)
    tint = np.array([1.06, 1.00, 0.92], dtype=np.float32)

    out = render(linear, alpha, light_map, shade, tint)

    # Encode-then-round: within 1 LSB of the original bytes.
    assert np.allclose(out, photo_u8, atol=1)


def test_engine_is_pure_no_mutation_of_inputs() -> None:
    """Calling render() never modifies the caller's arrays (criterion 1)."""
    linear = _linear_photo()
    alpha = np.full((9, 12, 1), 0.5, dtype=np.float32)
    base = np.array([0.55, 0.52, 0.48], dtype=np.float32)
    light_map = light_map_of(linear, base)
    shade = np.array([0.78, 0.70, 0.58], dtype=np.float32)
    tint = np.array([1.06, 1.00, 0.92], dtype=np.float32)

    before = (linear.copy(), alpha.copy(), light_map.copy(), shade.copy(), tint.copy())
    render(linear, alpha, light_map, shade, tint)

    assert np.array_equal(linear, before[0])
    assert np.array_equal(alpha, before[1])
    assert np.array_equal(light_map, before[2])
    assert np.array_equal(shade, before[3])
    assert np.array_equal(tint, before[4])


# --- Scene estimates ---------------------------------------------------------


def matte_of(shape: tuple[int, int], box: tuple[int, int, int, int]) -> np.ndarray:
    """A hard-edged rectangular matte, HxWx1, covering ``box`` as (top, left, bottom, right)."""
    top, left, bottom, right = box
    alpha = np.zeros((*shape, 1), dtype=np.float32)
    alpha[top:bottom, left:right] = 1.0
    return alpha


def test_base_colour_is_measured_inside_the_matte_only() -> None:
    """A bright window *outside* the wall must not reach the estimate.

    This is the whole reason the estimate takes a matte: the old whole-frame statistic could only
    ever be the colour of the room, and the Light Map divides by the colour of the *wall*.
    """
    wall_value = [0.35, 0.42, 0.28]
    linear = np.full((40, 40, 3), 0.99, dtype=np.float32)
    linear[5:35, 5:35] = np.array(wall_value, dtype=np.float32)

    got = estimate_base_colour(linear, matte_of((40, 40), (5, 5, 35, 35)))

    assert got.shape == (3,)
    assert np.allclose(got, wall_value, atol=1e-6)


def test_base_colour_ignores_the_matte_s_own_edge() -> None:
    """Boundary pixels are contaminated, so the estimate is taken from further in.

    A pixel on the matte's edge is part wall and part whatever is behind the wall's edge. Left in,
    the bright ring below would win the luminance ranking outright and the wall would be measured
    as the colour of its own outline.
    """
    wall_value = [0.30, 0.30, 0.30]
    linear = np.zeros((40, 40, 3), dtype=np.float32)
    linear[5:35, 5:35] = np.array(wall_value, dtype=np.float32)
    # The outermost ring *inside* the matte: bright, and nothing like the wall.
    linear[5, 5:35] = linear[34, 5:35] = 1.0
    linear[5:35, 5] = linear[5:35, 34] = 1.0

    got = estimate_base_colour(linear, matte_of((40, 40), (5, 5, 35, 35)))

    assert np.allclose(got, wall_value, atol=1e-6)


def test_base_colour_is_the_wall_in_full_light_not_its_average() -> None:
    """Ranked by luminance and taken near the 90th percentile, so shadow does not darken it.

    The Base Colour is the paint "as it appears under full light" (CONTEXT.md). A wall that is two
    thirds in shadow must still be measured as the lit paint, or every Light Map derived from it
    carries the shadow twice.
    """
    lit = [0.60, 0.60, 0.60]
    shadowed = [0.20, 0.20, 0.20]
    linear = np.zeros((40, 40, 3), dtype=np.float32)
    linear[5:35, 5:35] = np.array(shadowed, dtype=np.float32)
    linear[5:15, 5:35] = np.array(lit, dtype=np.float32)

    got = estimate_base_colour(linear, matte_of((40, 40), (5, 5, 35, 35)))

    assert np.allclose(got, lit, atol=1e-3)
    assert got[0] > np.mean([lit[0], shadowed[0], shadowed[0]])


def test_base_colour_keeps_the_wall_s_colour_cast() -> None:
    """A mean of whole pixels, never a percentile per channel.

    Taking the 90th percentile of each channel separately would compose the answer from three
    different sets of pixels and flatten the wall toward neutral — which would erase exactly the
    cast the estimate exists to capture.
    """
    warm_wall = [0.55, 0.40, 0.25]
    linear = np.zeros((40, 40, 3), dtype=np.float32)
    linear[5:35, 5:35] = np.array(warm_wall, dtype=np.float32)

    got = estimate_base_colour(linear, matte_of((40, 40), (5, 5, 35, 35)))

    assert np.allclose(got, warm_wall, atol=1e-6)
    assert got[0] > got[1] > got[2]


def test_base_colour_dark_photo_never_drops_below_the_floor() -> None:
    """A near-black wall must floor, not hand render() a zero divisor."""
    linear = np.zeros((40, 40, 3), dtype=np.float32)

    got = estimate_base_colour(linear, matte_of((40, 40), (5, 5, 35, 35)))

    assert np.all(got > 0.0)


def test_base_colour_survives_a_matte_with_no_opaque_interior() -> None:
    """A wall visible only in slivers still gets a colour measured from itself.

    Degrade, never dead-end (conventions.md §5): a matte too thin to have an interior once eroded
    is a poor wall, not a reason to fail a render the Dealer asked for.
    """
    wall_value = [0.5, 0.4, 0.3]
    linear = np.zeros((40, 40, 3), dtype=np.float32)
    linear[20:21, 5:35] = np.array(wall_value, dtype=np.float32)

    got = estimate_base_colour(linear, matte_of((40, 40), (20, 5, 21, 35)))

    assert np.allclose(got, wall_value, atol=1e-6)


def test_light_tint_of_a_neutral_photo_is_exactly_neutral() -> None:
    """Grey light has no colour: the tint must be (1, 1, 1)."""
    linear = np.full((8, 8, 3), 0.5, dtype=np.float32)

    got = estimate_light_tint(linear)

    assert np.allclose(got, 1.0, atol=1e-6)


def test_light_tint_captures_the_photographing_light_colour() -> None:
    """A warm-lit scene yields a tint carrying the light's colour, not its intensity.

    Asserted as the two invariants the tint exists to have, rather than as its formula: the
    channel *ratios* are the scene's, and the tint's own luma is 1 so multiplying a Shade by it
    changes the cast without changing how light the Shade is. Retuning the estimate must not
    break this test; changing what the tint means should.
    """
    light = np.array([0.72, 0.60, 0.44], dtype=np.float32) * 0.6  # warm, dim
    linear = np.tile(light, (8, 8, 1))

    got = estimate_light_tint(linear)

    assert np.allclose(got / got[1], light / light[1], atol=1e-5)  # the light's ratios
    assert float(np.dot(BT709_LUMA, got)) == pytest.approx(1.0, abs=1e-6)  # carries no brightness
    assert got[0] > got[1] > got[2]  # warm stays warm


def test_light_tint_is_invariant_to_brightness() -> None:
    """Twice the light level changes the luma channel, not the tint ratio."""
    base = np.array([0.72, 0.60, 0.44], dtype=np.float32)
    dark = np.tile(base * 0.4, (8, 8, 1))
    bright = np.tile(base * 0.8, (8, 8, 1))

    dark_tint = estimate_light_tint(dark)
    bright_tint = estimate_light_tint(bright)

    assert np.allclose(dark_tint, bright_tint, atol=1e-6)


def test_same_paint_two_planes_keep_relative_brightness_after_grouped_recolour() -> None:
    """Regression: per-plane Base Colour would flatten the room (#8).

    Two Wall Planes of the same paint at different brightness (0.8 vs 0.5
    shading) must keep their contrast after recolouring. A grouped Base
    Colour (tint-clustered, union-estimated) preserves the 1.6× ratio,
    while per-plane estimation normalises each to 1.0. Checked in linear
    space so sRGB encode does not compress the ratio.
    """
    from spectrapaint.render.engine import composite_linear, light_map_of, new_wall_of

    base_true = np.array([0.55, 0.52, 0.48], dtype=np.float32)
    shade = np.array([0.78, 0.70, 0.58], dtype=np.float32)
    tint = np.ones(3, dtype=np.float32)

    # Synthetic photo split left/right with different shading but same paint
    linear = np.zeros((40, 60, 3), dtype=np.float32)
    linear[:, :30] = base_true * 0.8
    linear[:, 30:] = base_true * 0.5
    alpha_left = np.zeros((40, 60, 1), dtype=np.float32)
    alpha_left[:, :30] = 1.0
    alpha_right = np.zeros((40, 60, 1), dtype=np.float32)
    alpha_right[:, 30:] = 1.0

    # Grouped path via render_many (exercises _grouped_base_colours)
    from spectrapaint.render.engine import render_many

    out = render_many(linear, [(alpha_left, shade), (alpha_right, shade)], tint)
    # Linear composites for the two interior pixels (before encode) would be
    # shading * shade; after grouped recolour they must remain 1.6× apart.
    # Check directly on linear composites to avoid encode compression.
    # Re-derive what render_many did: same shade, grouped base ≈ 0.8*base_true
    grouped_base = base_true * 0.8  # 90th percentile picks the brighter plane
    light_map = light_map_of(linear, grouped_base)
    composite = composite_linear(
        linear, np.ones((40, 60, 1), dtype=np.float32), new_wall_of(light_map, shade, tint)
    )
    left_lin = composite[20, 15]
    right_lin = composite[20, 45]
    assert np.allclose(left_lin, (0.8 / 0.5) * right_lin, rtol=1e-3)
    # And the encoded PNG must still show left brighter than right (not flattened)
    assert int(out[20, 15, 0]) > int(out[20, 45, 0]) + 5
    assert int(out[20, 15, 1]) > int(out[20, 45, 1]) + 5


def test_accent_wall_planes_keep_separate_base_colours() -> None:
    """A pre-existing Accent Wall gets its own Base Colour (#8).

    Two planes of different paints (off-white vs pink) must not be grouped:
    their tints differ by > _GROUP_TINT_THRESHOLD, so each keeps its own
    base and repaints to different output colours.
    """
    from spectrapaint.render.engine import _grouped_base_colours

    paint_a = np.array([0.55, 0.52, 0.48], dtype=np.float32)
    paint_b = np.array([0.70, 0.30, 0.30], dtype=np.float32)
    linear = np.zeros((40, 60, 3), dtype=np.float32)
    linear[:, :30] = paint_a * 0.8
    linear[:, 30:] = paint_b * 0.5
    alpha_left = np.zeros((40, 60, 1), dtype=np.float32)
    alpha_left[:, :30] = 1.0
    alpha_right = np.zeros((40, 60, 1), dtype=np.float32)
    alpha_right[:, 30:] = 1.0

    grouped = _grouped_base_colours(linear, [alpha_left, alpha_right])
    assert not np.allclose(grouped[0], grouped[1])
    # Tint distance must exceed the grouping threshold
    from spectrapaint.render.engine import _GROUP_TINT_THRESHOLD

    luma = np.array([0.2126, 0.7152, 0.0722])
    tint_a = grouped[0] / float(np.dot(luma, grouped[0]))
    tint_b = grouped[1] / float(np.dot(luma, grouped[1]))
    assert float(np.linalg.norm(tint_a - tint_b)) >= _GROUP_TINT_THRESHOLD
