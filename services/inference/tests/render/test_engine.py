"""Seam 2 — the render engine as a pure function (issue #3 criteria 1, 2).

These tests assert the *shape* of the contract -- pure numpy, no I/O, linear
composite then one encode -- and the invariant that the composite happens in
linear space. The analytical correctness properties (criteria 5-9) are the next
checkpoint's suite.
"""

import numpy as np

from spectrapaint.render.colour import linear_to_srgb
from spectrapaint.render.engine import (
    estimate_base_colour,
    estimate_light_tint,
    light_map_of,
    render,
)
from spectrapaint.render.luts import linearise_u8


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


def test_base_colour_is_the_interior_median() -> None:
    """The median of the photo's interior, so a bright window can't drag it white."""
    interior_value = [0.35, 0.42, 0.28]
    window_value = [0.99, 1.00, 0.98]
    linear = np.zeros((10, 10, 3), dtype=np.float32)
    interior = np.tile(np.array(interior_value, dtype=np.float32), (8, 8, 1))
    window = np.tile(np.array(window_value, dtype=np.float32), (2, 2, 1))
    linear[:8, :8] = interior
    linear[8:, 8:] = window

    got = estimate_base_colour(linear)

    assert got.shape == (3,)
    assert np.allclose(got, interior_value, atol=1e-6)


def test_base_colour_dark_photo_never_drops_below_the_floor() -> None:
    """A near-black photo must floor, not hand render() a zero divisor."""
    linear = np.zeros((6, 6, 3), dtype=np.float32)

    got = estimate_base_colour(linear)

    assert np.all(got > 0.0)


def test_base_colour_ignores_the_frame_edge() -> None:
    """A white border band must not influence the estimate."""
    interior_value = [0.4, 0.45, 0.3]
    linear = np.full((10, 10, 3), 1.0, dtype=np.float32)
    interior = np.tile(np.array(interior_value, dtype=np.float32), (8, 8, 1))
    linear[1:9, 1:9] = interior

    got = estimate_base_colour(linear)

    assert np.allclose(got, interior_value, atol=1e-6)


def test_light_tint_of_a_neutral_photo_is_exactly_neutral() -> None:
    """Grey light has no colour: the tint must be (1, 1, 1)."""
    linear = np.full((8, 8, 3), 0.5, dtype=np.float32)

    got = estimate_light_tint(linear)

    assert np.allclose(got, 1.0, atol=1e-6)


def test_light_tint_captures_the_photographing_light_colour() -> None:
    """A warm-lit scene yields a tint whose ratios match the light, not its intensity."""
    light = np.array([0.72, 0.60, 0.44], dtype=np.float32) * 0.6  # warm, dim
    linear = np.tile(light, (8, 8, 1))

    got = estimate_light_tint(linear)

    # Normalised to luma 1: neutral channels equal, and warm stays > neutral > blue.
    assert np.allclose(got, light / float(np.mean(light)), atol=1e-5)
    assert got[0] > got[1] > got[2]


def test_light_tint_is_invariant_to_brightness() -> None:
    """Twice the light level changes the luma channel, not the tint ratio."""
    base = np.array([0.72, 0.60, 0.44], dtype=np.float32)
    dark = np.tile(base * 0.4, (8, 8, 1))
    bright = np.tile(base * 0.8, (8, 8, 1))

    dark_tint = estimate_light_tint(dark)
    bright_tint = estimate_light_tint(bright)

    assert np.allclose(dark_tint, bright_tint, atol=1e-6)
