"""Seam 2 — analytical colour correctness (issue #3 criteria 5-9).

Every analytical bullet under "Seam 2 — the render engine" in
docs/specs/v1-spectrapaint.md is asserted here. The engine's per-tap steps are
pure numpy, so each check is exact linear algebra (float32, atol ~1e-5) rather
than a learned-model approximation:

- Synthetic photo = known_shading x known_base -> output = known_shading x target.
- Flat, evenly-lit wall -> output is uniformly the target Shade.
- Shaded regions stay proportionally darker and their chroma attenuates.
- Texture present in the input survives to the output.
- alpha 0 leaves pixels untouched, alpha 1 fully replaces, fractional alpha
  blends in linear space.
- Saturated Base Colour produces no runaway values (no NaN / inf / wild).
- Two Wall Planes with different Base Colours retain relative brightness
  (regression for the per-plane flattening bug).
- Corner pixels belong to exactly one plane; partitioned alphas leave no seam.
- Dark input plus pale target degrades gracefully (finite, bounded, no NaN).
"""

import numpy as np
import pytest

from spectrapaint.render.colour import linear_to_srgb
from spectrapaint.render.engine import (
    composite_linear,
    light_map_of,
    new_wall_of,
    render,
)

# A typical pale Shade, in linear RGB (fractional, 0..1).
SHADE = np.array([0.78, 0.70, 0.58], dtype=np.float32)
# A typical neutral wall Base Colour.
BASE = np.array([0.55, 0.52, 0.48], dtype=np.float32)
TINT = np.ones(3, dtype=np.float32)


def _shading(shape=(7, 9, 1), seed=0, floor=0.05) -> np.ndarray:
    """Smooth per-pixel illumination on the wall, kept away from zero.

    Smooth rather than random: the robust Light Map (#9) quiets *measured* grain, so an
    analytic check of the per-tap formula wants an input whose noise measures below the noise
    floor and therefore leaves the division untouched. ``seed`` is kept for call-site
    stability and deliberately ignored.
    """
    del seed
    count = int(np.prod(shape))
    return np.linspace(floor, 1.0 + floor, count, dtype=np.float32).reshape(shape)


def _alpha(shape=(7, 9, 1)) -> np.ndarray:
    return np.ones(shape, dtype=np.float32)


def test_core_property_shading_times_base_renders_shading_times_target() -> None:
    """The core correctness property: photo = s*base -> output = s*target."""
    shading = _shading()
    photo = shading * BASE
    light_map = light_map_of(photo, BASE)

    composite = composite_linear(photo, _alpha(), new_wall_of(light_map, SHADE, TINT))
    assert composite.shape == photo.shape
    assert np.allclose(composite, shading * SHADE, atol=1e-5)

    # End-to-end: what the Dealer sees is the same colour, after one encode.
    out = render(photo, _alpha(), light_map, SHADE, TINT)
    expected = (linear_to_srgb(shading * SHADE) * 255.0 + 0.5).astype(np.uint8)
    assert out.shape == photo.shape
    assert out.dtype == np.uint8
    assert np.allclose(out, expected, atol=2)  # encode LUT quantisation


def test_light_tint_is_part_of_the_analytical_output() -> None:
    """The spec's per-tap formula includes light_tint: s*base -> s*target*tint."""
    tint = np.array([1.06, 1.00, 0.92], dtype=np.float32)
    shading = _shading(seed=3)
    photo = shading * BASE

    out = composite_linear(photo, _alpha(), new_wall_of(light_map_of(photo, BASE), SHADE, tint))
    assert np.allclose(out, shading * SHADE * tint, atol=1e-5)


def test_flat_evenly_lit_wall_is_uniformly_the_target_shade() -> None:
    """Flat wall (shading = 1): every pixel is exactly the target Shade."""
    photo = np.broadcast_to(BASE, (11, 13, 3)).astype(np.float32).copy()
    light_map = light_map_of(photo, BASE)

    out = composite_linear(photo, _alpha((11, 13, 1)), new_wall_of(light_map, SHADE, TINT))
    assert np.allclose(out, SHADE, atol=1e-6)

    rendered = render(photo, _alpha((11, 13, 1)), light_map, SHADE, TINT)
    # Uniform per channel -- a flat wall repainted in a flat light stays flat.
    assert (rendered.max(axis=(0, 1)) == rendered.min(axis=(0, 1))).all()
    # ... and that uniform value is the requested Shade, correctly gamma-encoded.
    expected_u8 = (linear_to_srgb(SHADE) * 255.0 + 0.5).astype(np.uint8)
    assert np.allclose(rendered[0, 0], expected_u8, atol=2)


def test_shaded_region_stays_proportionally_darker_and_chroma_attenuates() -> None:
    """A shaded pixel scales by its shading factor, chroma included.

    This is the property the CIELAB shortcut loses: a lab-space hue-preserving
    recolor keeps chroma constant under shading, flattening the room. Linear
    maths scales the whole vector toward black, so chroma attenuates
    proportionally.
    """
    shading = np.linspace(1.0, 0.4, 8, dtype=np.float32)[:, None, None]
    photo = np.broadcast_to(shading * BASE, (8, 1, 3)).copy()
    light_map = light_map_of(photo, BASE)
    alpha = np.ones((8, 1, 1), dtype=np.float32)

    out = composite_linear(photo, alpha, new_wall_of(light_map, SHADE, TINT))
    lit, shaded = out[0, 0], out[-1, 0]
    factor = float(shading[0, 0, 0] / shading[-1, 0, 0])

    # Proportionally darker, channel by channel.
    assert np.allclose(lit, factor * shaded, rtol=1e-4)

    # Chroma (RGB span) attenuates by the same factor.
    chroma = lambda px: float(np.max(px) - np.min(px))  # noqa: E731
    assert chroma(shaded) == pytest.approx(chroma(lit) / factor, rel=1e-4)
    assert chroma(shaded) < chroma(lit)


def test_texture_survives_the_recolour() -> None:
    """Fine shading texture is carried through unchanged, not flattened."""
    shading = np.linspace(0.9, 0.5, 24, dtype=np.float32)[:, None, None]
    photo = np.broadcast_to(shading * BASE, (24, 1, 3)).copy()
    light_map = light_map_of(photo, BASE)
    alpha = np.ones((24, 1, 1), dtype=np.float32)

    out = composite_linear(photo, alpha, new_wall_of(light_map, SHADE, TINT))
    # Interior texels: the frame's outermost rows are where edge padding puts
    # step artefacts into the high-pass residual, and this check is about
    # texture, not boundaries.
    texel_a, texel_b = out[6, 0], out[-7, 0]

    # The brightness ratio between two texels is preserved exactly.
    expected_ratio = float(shading[6, 0, 0] / shading[-7, 0, 0])
    assert np.allclose(texel_a, expected_ratio * texel_b, rtol=1e-4)
    # ... and the texture is still visible in the output.
    assert not np.allclose(texel_a, texel_b, atol=1e-3)


def test_alpha_semantics_blend_in_linear_space_analytically() -> None:
    """alpha 0 untouched, alpha 1 fully replaced, fractional blends linearly."""
    rng = np.random.default_rng(1)
    photo = rng.random((7, 9, 3), dtype=np.float32)
    light_map = light_map_of(photo, BASE)
    new_wall = new_wall_of(light_map, SHADE, TINT)

    alpha0 = np.zeros((7, 9, 1), dtype=np.float32)
    alpha1 = np.ones((7, 9, 1), dtype=np.float32)
    frac = np.full((7, 9, 1), 0.3, dtype=np.float32)

    assert np.allclose(composite_linear(photo, alpha0, new_wall), photo, atol=1e-6)
    assert np.allclose(composite_linear(photo, alpha1, new_wall), new_wall, atol=1e-6)
    got = composite_linear(photo, frac, new_wall)
    assert np.allclose(got, 0.3 * new_wall + 0.7 * photo, atol=1e-6)


def test_saturated_base_colour_produces_no_runaway_values() -> None:
    """Deep-red wall: the near-zero blue channel is blended away, never amplified (#9).

    The blue channel here is pure noise up to 2.5x the true base value — exactly the input
    three-channel division would turn into speckle. Past the saturation blend's end the Light
    Map is single-brightness: one shading value shared by every channel, bounded by the ceiling,
    so nothing can run away.
    """
    from spectrapaint.render.engine import _LIGHT_MAP_CEILING

    saturated = np.array([0.99, 0.05, 0.02], dtype=np.float32)
    shading = _shading(seed=2)
    rng = np.random.default_rng(9)
    # The blue channel is all noise on a deep red wall: its offset is up to
    # 2.5x the true base value, which is what made division there speckle.
    noise = rng.uniform(0.0, 0.05, size=shading.shape).astype(np.float32)
    photo = (shading * saturated).copy()
    photo[..., 2:3] += noise

    light_map = light_map_of(photo, saturated)

    assert np.isfinite(light_map).all()
    assert (light_map >= 0.0).all()
    assert (light_map <= _LIGHT_MAP_CEILING + 1e-6).all()
    assert np.allclose(light_map[..., 0], light_map[..., 1], atol=1e-5)
    assert np.allclose(light_map[..., 1], light_map[..., 2], atol=1e-5)

    new_wall = new_wall_of(light_map, SHADE, TINT)
    composite = composite_linear(photo, _alpha(), new_wall)
    assert np.isfinite(composite).all()
    assert composite.max() < _LIGHT_MAP_CEILING * SHADE.max() + 1e-4

    out = render(photo, _alpha(), light_map, SHADE, TINT)
    assert np.isfinite(out).all()
    assert out.min() >= 0 and out.max() <= 255


def test_two_planes_with_different_base_colours_keep_relative_brightness() -> None:
    """Regression for the per-plane flattening bug.

    Per-plane Base Colour estimation used to normalise every wall to the same
    brightness, flattening the room. Two walls lit 0.8 and 0.5, in different
    paints, must keep that 1.6x brightness contrast after repainting.
    """
    shading_a = np.array([[[0.8]]], dtype=np.float32)
    shading_b = np.array([[[0.5]]], dtype=np.float32)
    base_a = np.array([0.55, 0.52, 0.48], dtype=np.float32)
    base_b = np.array([0.30, 0.28, 0.60], dtype=np.float32)
    alpha1 = np.ones((1, 1, 1), dtype=np.float32)

    wall_a = new_wall_of(light_map_of(shading_a * base_a, base_a), SHADE, TINT)
    out_a = composite_linear(shading_a * base_a, alpha1, wall_a)
    wall_b = new_wall_of(light_map_of(shading_b * base_b, base_b), SHADE, TINT)
    out_b = composite_linear(shading_b * base_b, alpha1, wall_b)
    assert np.allclose(out_a, (0.8 / 0.5) * out_b, rtol=1e-4)


def test_corner_pixels_belong_to_exactly_one_plane_no_double_composite() -> None:
    """Partitioned alphas (a + b = 1) leave no photo leak at a seam.

    The spec: "every pixel belongs to exactly one Wall Plane...
    double-claimed pixels composite twice and produce a dark seam." When the
    alphas partition the wall region (a + b = 1), the photo term carries the
    coefficient (1 - a - b) = 0: the corner is painted once, never twice.
    """
    photo = np.array([[[0.2, 0.3, 0.4]]], dtype=np.float32)
    wall_a = np.array([[[0.78, 0.70, 0.58]]], dtype=np.float32)
    wall_b = np.array([[[0.90, 0.60, 0.40]]], dtype=np.float32)
    alpha_a = np.array([[[0.6]]], dtype=np.float32)
    alpha_b = np.array([[[0.4]]], dtype=np.float32)

    assert np.allclose(alpha_a + alpha_b, 1.0)
    blended_wall = alpha_a * wall_a + alpha_b * wall_b
    seam = composite_linear(photo, alpha_a + alpha_b, blended_wall)
    assert np.allclose(seam, blended_wall, atol=1e-6)


def test_dark_input_pale_target_degrades_gracefully_not_nan() -> None:
    """Near-black walls repainted in a pale Shade stay finite and bounded."""
    shading = np.array([[[1e-4], [0.0]]], dtype=np.float32)
    photo = shading * BASE
    light_map = light_map_of(photo, BASE)
    alpha = np.ones((1, 2, 1), dtype=np.float32)

    composite = composite_linear(photo, alpha, new_wall_of(light_map, SHADE, TINT))
    assert np.isfinite(composite).all()
    assert (composite >= 0).all()

    out = render(photo, alpha, light_map, SHADE, TINT)
    assert np.isfinite(out).all()
    assert out.min() >= 0 and out.max() <= 255
    # The fully-unlit pixel stays essentially black -- no invented detail.
    assert float(out[0, 1].mean()) <= 2.0
