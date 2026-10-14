"""Seam 2 — Issue #52: stains suppressed, sunlit walls paint the right colour.

Pure function, synthetic inputs, analytically known answers. Built the same way
the probe did: ``srgb_to_linear`` of a flat wall plus patches, a full-coverage
matte, and ``lab_to_linear_rgb`` for the Shade. Fast lane, no models.
"""

import numpy as np
import pytest

from spectrapaint.render.colour import lab_to_linear_rgb, srgb_to_linear
from spectrapaint.render.engine import (
    estimate_base_colour,
    light_map_of,
    render,
)
from spectrapaint.render.luts import encode_srgb

# ---------------------------------------------------------------------------
# Test-only colour science: linear RGB -> Lab (D65, 2°) and CIEDE2000 ΔE00.
# Kept here, not in render/, so render/ stays pure domain code and the test
# pins its ownorrery rather than calling the implementation under test.
# ---------------------------------------------------------------------------

_XYZ_TO_LAB_EPS = 216.0 / 24389.0
_XYZ_TO_LAB_KAP = 24389.0 / 27.0
_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
_D65_XYZ = (0.95047, 1.0, 1.08883)


def _linear_to_lab(linear: np.ndarray) -> np.ndarray:
    xyz = linear.reshape(-1, 3) @ _RGB_TO_XYZ.T
    x = xyz[:, 0] / _D65_XYZ[0]
    y = xyz[:, 1] / _D65_XYZ[1]
    z = xyz[:, 2] / _D65_XYZ[2]

    def _f(t: np.ndarray) -> np.ndarray:
        return np.where(
            t > _XYZ_TO_LAB_EPS, np.cbrt(np.maximum(t, 0.0)), (_XYZ_TO_LAB_KAP * t + 16.0) / 116.0
        )

    fx, fy, fz = _f(x), _f(y), _f(z)
    lab = np.stack([116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], axis=1)
    return lab.reshape(linear.shape)


def _delta_e00(lab1: np.ndarray, lab2: np.ndarray) -> float:
    a = np.asarray(lab1, dtype=np.float64).ravel()
    b = np.asarray(lab2, dtype=np.float64).ravel()
    L1, A1, B1 = a[0], a[1], a[2]
    L2, A2, B2 = b[0], b[1], b[2]
    C1 = float(np.hypot(A1, B1))
    C2 = float(np.hypot(A2, B2))
    c_bar = (C1 + C2) / 2.0
    g = 0.5 * (1.0 - np.sqrt(c_bar**7 / (c_bar**7 + 25.0**7)))
    a1p = (1.0 + g) * A1
    a2p = (1.0 + g) * A2
    c1p = float(np.hypot(a1p, B1))
    c2p = float(np.hypot(a2p, B2))
    h1p = (np.degrees(np.arctan2(B1, a1p)) % 360.0) if c1p > 0 else 0.0
    h2p = (np.degrees(np.arctan2(B2, a2p)) % 360.0) if c2p > 0 else 0.0
    d_lp = L2 - L1
    d_cp = c2p - c1p
    if c1p * c2p == 0:
        d_hp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        d_hp = h2p - h1p
    elif h2p <= h1p:
        d_hp = h2p - h1p + 360.0
    else:
        d_hp = h2p - h1p - 360.0
    d_hp_rad = np.radians(d_hp)
    d_Hp = 2.0 * np.sqrt(c1p * c2p) * np.sin(d_hp_rad / 2.0)
    l_bar = (L1 + L2) / 2.0
    c_bar_p = (c1p + c2p) / 2.0
    if c1p * c2p == 0:
        h_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        h_bar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        h_bar = (h1p + h2p + 360.0) / 2.0
    else:
        h_bar = (h1p + h2p - 360.0) / 2.0
    t = (
        1.0
        - 0.17 * np.cos(np.radians(h_bar - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * h_bar))
        + 0.32 * np.cos(np.radians(3.0 * h_bar + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * h_bar - 63.0))
    )
    d_ro = 30.0 * np.exp(-(((h_bar - 275.0) / 25.0) ** 2))
    r_c = 2.0 * np.sqrt(c_bar_p**7 / (c_bar_p**7 + 25.0**7))
    s_l = 1.0 + 0.015 * (l_bar - 50.0) ** 2 / np.sqrt(20.0 + (l_bar - 50.0) ** 2)
    s_c = 1.0 + 0.045 * c_bar_p
    s_h = 1.0 + 0.015 * c_bar_p * t
    r_t = -np.sin(np.radians(2.0 * d_ro)) * r_c
    return float(
        np.sqrt(
            (d_lp / s_l) ** 2
            + (d_cp / s_c) ** 2
            + (d_Hp / s_h) ** 2
            + r_t * (d_cp / s_c) * (d_Hp / s_h)
        )
    )


def _hue_deg(lab: np.ndarray) -> float:
    return float(np.degrees(np.arctan2(lab[2], lab[1])) % 360.0)


def _srgb_u8_to_linear(u8: np.ndarray) -> np.ndarray:
    return srgb_to_linear(u8.astype(np.float64) / 255.0).astype(np.float32)


def _render_u8(photo_u8: np.ndarray, alpha: np.ndarray, shade_lab: tuple[float, float, float]):
    linear = _srgb_u8_to_linear(photo_u8)
    base = estimate_base_colour(linear, alpha)
    light_map = light_map_of(linear, base, alpha)
    shade = lab_to_linear_rgb(np.array(shade_lab, dtype=np.float64)).astype(np.float32)
    out = render(linear, alpha, light_map, shade, np.ones(3, dtype=np.float32))
    return out, base


H = W = 200


def test_stain_disappears_cream_wall_brown_patch() -> None:
    """Bug 2: 40×40 brown patch on cream, pale-blue Shade → ΔE00 < 3 (20.6 today)."""
    cream = np.array([225, 215, 190], dtype=np.uint8)
    brown = np.array([170, 150, 110], dtype=np.uint8)
    photo = np.full((H, W, 3), cream, dtype=np.uint8)
    photo[80:120, 80:120] = brown
    alpha = np.ones((H, W, 1), dtype=np.float32)

    out, _ = _render_u8(photo, alpha, (85.0, -5.0, -12.0))
    lab_wall = _linear_to_lab(srgb_to_linear(out[10, 10].astype(np.float64) / 255.0))
    lab_patch = _linear_to_lab(srgb_to_linear(out[100, 100].astype(np.float64) / 255.0))
    assert _delta_e00(lab_wall, lab_patch) < 3.0


def test_illumination_gradient_survives_two_to_one() -> None:
    """Left-to-right 2:1 light gradient renders within 2% of 2:1."""
    lin_base = np.array([0.60, 0.55, 0.50], dtype=np.float32)
    grad = np.linspace(1.0, 0.5, W, dtype=np.float32)[None, :]
    grad = np.broadcast_to(grad, (H, W)).copy()
    photo = (np.broadcast_to(lin_base, (H, W, 3)).copy() * grad[..., None]).astype(np.float32)
    alpha = np.ones((H, W, 1), dtype=np.float32)

    base = estimate_base_colour(photo, alpha)
    light_map = light_map_of(photo, base, alpha)
    shade = np.array([0.70, 0.60, 0.50], dtype=np.float32)
    left = light_map[100, 0] * shade
    right = light_map[100, W - 1] * shade
    luma = lambda px: 0.2126 * px[0] + 0.7152 * px[1] + 0.0722 * px[2]  # noqa: E731
    ratio = float(luma(left) / luma(right))
    assert abs(ratio - 2.0) / 2.0 < 0.02


def test_texture_survives_plus_minus_five_percent_noise() -> None:
    """±5% high-frequency noise keeps within 20% of its relative std."""
    lin_base = _srgb_u8_to_linear(np.full((1, 1, 3), np.array([200, 190, 170], dtype=np.uint8)))[
        0, 0
    ]
    rng = np.random.default_rng(0)
    noise = (1.0 + 0.05 * rng.standard_normal((H, W))).astype(np.float32)
    photo = (np.broadcast_to(lin_base, (H, W, 3)).copy() * noise[..., None]).astype(np.float32)
    photo = np.clip(photo, 0.0, 1.0)
    alpha = np.ones((H, W, 1), dtype=np.float32)

    base = estimate_base_colour(photo, alpha)
    light_map = light_map_of(photo, base, alpha)
    in_std = float(noise.std())
    out_std = float((light_map[..., 1] / np.mean(light_map[..., 1])).std())
    assert abs(out_std - in_std) / in_std < 0.20


def test_contact_shadow_near_matte_edge_survives() -> None:
    """Darkening ramp at the matte edge keeps ≥ 80% of its depth."""
    from spectrapaint.render.engine import _STAIN_EDGE_PROTECT_RADIUS_FRACTION

    lin_base = _srgb_u8_to_linear(np.full((1, 1, 3), np.array([200, 190, 170], dtype=np.uint8)))[
        0, 0
    ]
    photo = np.broadcast_to(lin_base, (H, W, 3)).copy().astype(np.float32)
    edge_w = max(1, round(W * _STAIN_EDGE_PROTECT_RADIUS_FRACTION))
    ramp = np.ones((H, W), dtype=np.float32)
    for x in range(edge_w):
        ramp[:, x] = 0.5 + 0.5 * (x / edge_w)
    photo = (photo * ramp[..., None]).astype(np.float32)
    alpha = np.ones((H, W, 1), dtype=np.float32)

    base = estimate_base_colour(photo, alpha)
    light_map = light_map_of(photo, base, alpha)
    out_ratio = float(light_map[100, 0, 1] / light_map[100, W // 2, 1])
    # Input edge/centre is 0.5; keeping ≥80% depth means out ≤ 0.5 + 0.2*0.5 = 0.6.
    assert out_ratio <= 0.6


def test_sun_does_not_skew_base_colour_yellow_wall_strip() -> None:
    """Yellow wall + 20% near-white strip: unlit wall within ΔE00 < 3 of no-strip (8.6 today)."""
    yellow = np.array([240, 190, 60], dtype=np.uint8)
    sun = np.array([250, 248, 240], dtype=np.uint8)
    photo = np.full((H, W, 3), yellow, dtype=np.uint8)
    photo[:, int(W * 0.8) :] = sun
    photo_clean = np.full((H, W, 3), yellow, dtype=np.uint8)
    alpha = np.ones((H, W, 1), dtype=np.float32)

    out, _ = _render_u8(photo, alpha, (65.0, 35.0, 60.0))
    out_clean, _ = _render_u8(photo_clean, alpha, (65.0, 35.0, 60.0))
    lab = _linear_to_lab(srgb_to_linear(out[100, 10].astype(np.float64) / 255.0))
    lab_clean = _linear_to_lab(srgb_to_linear(out_clean[100, 10].astype(np.float64) / 255.0))
    assert _delta_e00(lab, lab_clean) < 3.0


def test_no_yellow_blob_pale_blue_wall_warm_patch() -> None:
    """5% warm patch on pale-blue, pale-blue Shade: patch b* ≤ 0 and L* above wall."""
    pale_blue = np.array([200, 215, 225], dtype=np.uint8)
    warm = np.array([255, 245, 200], dtype=np.uint8)
    photo = np.full((H, W, 3), pale_blue, dtype=np.uint8)
    photo[78:122, 78:122] = warm
    alpha = np.ones((H, W, 1), dtype=np.float32)

    out, _ = _render_u8(photo, alpha, (85.0, -5.0, -12.0))
    lab_patch = _linear_to_lab(srgb_to_linear(out[100, 100].astype(np.float64) / 255.0))
    lab_wall = _linear_to_lab(srgb_to_linear(out[10, 10].astype(np.float64) / 255.0))
    assert float(lab_patch[2]) <= 0.0
    assert float(lab_patch[0]) > float(lab_wall[0])


def test_no_hard_clip_strip_at_one_point_seven_x() -> None:
    """1.7× strip on orange Shade: no 255 inside matte, hue within 5°."""
    lin_base = _srgb_u8_to_linear(np.full((1, 1, 3), np.array([200, 190, 170], dtype=np.uint8)))[
        0, 0
    ]
    photo = np.broadcast_to(lin_base, (H, W, 3)).copy().astype(np.float32)
    photo[:, 120:140] *= 1.7
    photo = np.clip(photo, 0.0, 1.0).astype(np.float32)
    alpha = np.ones((H, W, 1), dtype=np.float32)

    base = estimate_base_colour(photo, alpha)
    light_map = light_map_of(photo, base, alpha)
    shade = lab_to_linear_rgb(np.array([65.0, 35.0, 60.0], dtype=np.float64)).astype(np.float32)
    out = render(photo, alpha, light_map, shade, np.ones(3, dtype=np.float32))

    inside = out[100, 120:140]
    assert not (inside == 255).any()
    lab_patch = _linear_to_lab(srgb_to_linear(out[100, 130].astype(np.float64) / 255.0))
    assert abs(_hue_deg(lab_patch) - _hue_deg(np.array([65.0, 35.0, 60.0]))) < 5.0


def test_outside_matte_is_bit_identical() -> None:
    """alpha == 0 pixels equal encode_srgb(photo) exactly."""
    rng = np.random.default_rng(1)
    photo_u8 = rng.integers(0, 256, size=(20, 20, 3)).astype(np.uint8)
    linear = _srgb_u8_to_linear(photo_u8)
    alpha = np.zeros((20, 20, 1), dtype=np.float32)
    alpha[5:15, 5:15] = 1.0

    base = estimate_base_colour(linear, alpha)
    light_map = light_map_of(linear, base, alpha)
    shade = lab_to_linear_rgb(np.array([80.0, 0.0, 0.0], dtype=np.float64)).astype(np.float32)
    out = render(linear, alpha, light_map, shade, np.ones(3, dtype=np.float32))
    expected = (encode_srgb(np.ascontiguousarray(linear)) * 255.0 + 0.5).astype(np.uint8)
    mask = alpha[..., 0] == 0
    assert np.array_equal(out[mask], expected[mask])


def test_flat_clean_wall_still_exact_division() -> None:
    """Flat wall: light_map_of == photo / base (the docstring contract)."""
    base = np.array([0.55, 0.52, 0.48], dtype=np.float32)
    photo = np.broadcast_to(base, (16, 16, 3)).astype(np.float32).copy()
    got = light_map_of(photo, base)
    assert np.allclose(got, photo / base, atol=1e-5)


def test_a_repeat_tap_reuses_the_preparation_and_recomputes_nothing() -> None:
    """Review 1: the per-tap path must not re-estimate or re-derive anything.

    ``render_preparation_of`` does the once-per-photo work; ``render_many``
    with ``_preparation`` must call neither the base-colour grouping nor the
    Light Map derivation again, and must return exactly what the uncached path
    returns. A spy counter pins the mechanism (not the milliseconds), so this
    cannot regress silently the way the old gate did.
    """
    import spectrapaint.render.engine as engine

    rng = np.random.default_rng(3)
    linear = rng.random((48, 64, 3), dtype=np.float32)
    alpha = np.ones((48, 64, 1), dtype=np.float32)
    shade = np.array([0.78, 0.70, 0.58], dtype=np.float32)
    tint = np.ones(3, dtype=np.float32)

    calls = {"grouped": 0, "light_map": 0}
    real_grouped = engine._grouped_base_colours
    real_light_map = engine.light_map_of

    def count_grouped(photo, alphas, surfaces=None):
        calls["grouped"] += 1
        return real_grouped(photo, alphas, surfaces)

    def count_light_map(photo, base, alpha=None):
        calls["light_map"] += 1
        return real_light_map(photo, base, alpha)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(engine, "_grouped_base_colours", count_grouped)
    monkeypatch.setattr(engine, "light_map_of", count_light_map)
    try:
        plain = engine.render_many(linear, [(alpha, shade)], tint)
        first = dict(calls)
        assert first["grouped"] >= 1 and first["light_map"] >= 1

        prep = engine.render_preparation_of(linear, [alpha], ["wall"])
        calls["grouped"] = 0
        calls["light_map"] = 0
        cached = engine.render_many(linear, [(alpha, shade)], tint, _preparation=prep)
        assert calls == {"grouped": 0, "light_map": 0}
        assert np.array_equal(cached, plain)

        # A second Shade on the same preparation also recomputes nothing.
        other = np.array([0.30, 0.40, 0.60], dtype=np.float32)
        cached2 = engine.render_many(linear, [(alpha, other)], tint, _preparation=prep)
        assert calls == {"grouped": 0, "light_map": 0}
        assert not np.array_equal(cached2, plain)
    finally:
        monkeypatch.undo()


def test_a_cached_tap_costs_a_fraction_of_a_full_recompute() -> None:
    """Review 1: timing guard that the cached tap is the cheap path.

    Medians over repeats with a 1/2 threshold: a full recompute does grouping
    plus Light Map derivation (seconds at photo scale even on this synthetic
    input), a cached tap does multiply–composite–rolloff–encode only. The gap
    is an order of magnitude, so 1/2 cannot flake on a busy machine the way an
    absolute millisecond budget would.
    """
    import time

    import spectrapaint.render.engine as engine

    rng = np.random.default_rng(4)
    linear = rng.random((240, 320, 3), dtype=np.float32)
    alpha = np.ones((240, 320, 1), dtype=np.float32)
    shade = np.array([0.78, 0.70, 0.58], dtype=np.float32)
    tint = np.ones(3, dtype=np.float32)

    def median_ms(fn, repeats=5):
        for _ in range(2):
            fn()
        samples = []
        for _ in range(repeats):
            start = time.perf_counter()
            fn()
            samples.append((time.perf_counter() - start) * 1000.0)
        return float(np.median(samples))

    full_ms = median_ms(lambda: engine.render_many(linear, [(alpha, shade)], tint))
    prep = engine.render_preparation_of(linear, [alpha], ["wall"])
    cached_ms = median_ms(
        lambda: engine.render_many(linear, [(alpha, shade)], tint, _preparation=prep)
    )
    assert cached_ms < full_ms / 2.0
