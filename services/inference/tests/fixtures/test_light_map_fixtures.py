"""The robust Light Map against the real photographs it was tuned on (issues #9 and #52).

The tunables at the top of ``engine.py`` exist to be set against real photographs, and a tuning
that no test pins can silently drift back. These tests run the shipped ``light_map_of`` — no
models, just the fixture photographs and their hand labels — and pin where each fixture lands:

* ``empty-corner.jpg``, the flat-daylight control, measures below ``_NOISE_FLOOR`` so noise
  smoothing does not engage. Issue #52 stain suppression does reshape it (Decision 1:
  "freshly painted" covers stains), so exact division no longer holds; what is pinned is
  the noise floor itself and a bounded mean change.
* ``windows-with-curtains.jpg``, the underexposed night shot, repainted pale degrades gracefully
  — finite, no NaN. Linear highlights may exceed 1 after the robust Base Colour (issue #52 C)
  and stain brightening; the hue-preserving rolloff in ``render()`` brings them back, so the
  bound is checked after the rolloff and on the final bytes.
* ``corner-with-clothesline.jpg``, split by its hand-labelled planes, decides the saturation
  blend per Base Colour. Issue #52 stain suppression reshapes both planes, so the blend is
  pinned via its weight, not via light-map equality.

The numbers in the constant comments in ``engine.py`` were measured with exactly this script; if
one of these tests fails after a retune, re-record the reasoning in the comment, not just the
constant.
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from spectrapaint.render.engine import (
    _NOISE_FLOOR,
    _brightness_weight_of,
    _highlight_rolloff,
    _measured_noise_sigma,
    estimate_base_colour,
    light_map_of,
    render,
)
from spectrapaint.render.luts import linearise_u8

FIXTURE_DIR = Path(__file__).resolve().parents[4] / "data" / "fixtures" / "rooms"
NO_FIXTURES = "no room fixtures in data/fixtures/rooms — see its README"


def rooms() -> list[Path]:
    if not FIXTURE_DIR.is_dir():
        return []
    return sorted(
        path
        for path in FIXTURE_DIR.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg"} and not path.name.endswith(".wall.png")
    )


def wall_matte(photo: Path) -> np.ndarray:
    """The hand-labelled wall mask, HxWx1 float32 in [0, 1]."""
    with Image.open(photo.with_suffix(".wall.png")) as image:
        return np.asarray(image.convert("L"), dtype=np.float32)[..., None] / 255.0


def linear_photo(photo: Path) -> np.ndarray:
    with Image.open(photo) as image:
        return linearise_u8(np.asarray(image.convert("RGB"), dtype=np.uint8))


@pytest.mark.fixtures
@pytest.mark.skipif(not rooms(), reason=NO_FIXTURES)
def test_the_daylight_control_stays_below_the_noise_floor() -> None:
    """empty-corner is the texture-survives control: its wall must not measure as grainy.

    If this fixture crosses the noise floor, every slightly grainy daylight photo will be
    over-smoothed. Issue #52 stain suppression intentionally reshapes the Light Map even
    here (stains are covered, not kept), so exact division no longer holds; what is pinned
    is the floor itself and that the reshaping stays bounded on average.
    """
    photo = FIXTURE_DIR / "empty-corner.jpg"
    alpha = wall_matte(photo)
    linear = linear_photo(photo)
    base = estimate_base_colour(linear, alpha)

    plain = np.nan_to_num(linear / base)
    robust = light_map_of(linear, base, alpha)

    assert np.isfinite(robust).all()
    assert _measured_noise_sigma(plain, alpha) < _NOISE_FLOOR
    assert _measured_noise_sigma(robust, alpha) < _NOISE_FLOOR
    # Stain suppression moves the map (mean ~0.06 today); a retune that flattens
    # the wall's illumination must not drift far past that.
    assert float(np.abs(robust - plain).mean()) < 0.10


@pytest.mark.fixtures
@pytest.mark.skipif(not rooms(), reason=NO_FIXTURES)
def test_the_night_fixture_repainted_pale_degrades_gracefully() -> None:
    """The darkest wall in the fixtures, repainted in the palest shade: sane bytes only.

    windows-with-curtains is shot at night under one tube light; its darkest quartile is the
    input that produces runaway values if the Light Map divides carelessly (issue #9's table).
    After issue #52's hue-agreeing Base Colour and stain brightening, linear highlights may
    exceed 1; the hue-preserving rolloff in render() (issue #52 E) brings them back, so the
    bound is checked there and on the final bytes.
    """
    photo = FIXTURE_DIR / "windows-with-curtains.jpg"
    alpha = wall_matte(photo)
    linear = linear_photo(photo)
    base = estimate_base_colour(linear, alpha)

    light_map = light_map_of(linear, base, alpha)
    assert np.isfinite(light_map).all()

    # Repaint pale and check that every pixel stays finite and non-negative in linear;
    # highlights above 1 are expected and are tamed by the rolloff before encode.
    from spectrapaint.render.colour import lab_to_linear_rgb

    pale = lab_to_linear_rgb(np.array([90.0, 0.0, 0.0], dtype=np.float64))
    new_wall = light_map * pale
    composite = alpha * new_wall + (1.0 - alpha) * linear
    assert np.isfinite(composite).all()
    assert (composite >= 0.0).all()
    rolled = _highlight_rolloff(composite, alpha)
    assert np.isfinite(rolled).all()
    assert (rolled <= 1.0 + 1e-6).all()

    # Full render end-to-end.
    out = render(
        linear,
        alpha,
        light_map,
        np.array([0.78, 0.70, 0.58], dtype=np.float32),
        np.ones(3, dtype=np.float32),
    )
    assert np.isfinite(out).all()
    assert out.min() >= 0 and out.max() <= 255


@pytest.mark.fixtures
@pytest.mark.skipif(not rooms(), reason=NO_FIXTURES)
def test_the_saturation_blend_engages_on_the_pink_plane_only() -> None:
    """Split by the hand-labelled planes: saturated wall blends, neutral wall does not.

    corner-with-clothesline is the issue's saturation-blend fixture: a near-neutral wall and a
    saturated one in the same frame. The blend is decided per Base Colour, so the two planes
    must come out on different sides of it. Issue #52 stain suppression reshapes both planes'
    Light Maps, so the decision is pinned via its weight, not via map equality.
    """
    photo = FIXTURE_DIR / "corner-with-clothesline.jpg"
    linear = linear_photo(photo)

    with Image.open(photo.with_suffix(".planes.png")) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    colours = {tuple(c) for c in rgb.reshape(-1, 3).tolist()} - {(0, 0, 0)}
    masks = sorted(
        ((rgb == np.asarray(c, np.uint8)).all(-1) for c in colours),
        key=lambda m: float(np.flatnonzero(m.any(axis=0)).mean()),
    )
    assert len(masks) == 2, "this test is written for the two-plane corner fixture"

    # The blend decision itself: neutral base keeps three-channel division (weight 0),
    # saturated base blends toward brightness (weight > 0).
    bases = []
    for mask in masks:
        alpha = mask.astype(np.float32)[..., None]
        bases.append(estimate_base_colour(linear, alpha))

    neutral_weight = _brightness_weight_of(bases[0])
    saturated_weight = _brightness_weight_of(bases[1])
    assert neutral_weight == 0.0, "the neutral plane must keep its three-channel cast exactly"
    assert saturated_weight > 0.0, (
        "the saturated plane's weak channels must blend toward brightness"
    )

    # Observable behaviour on the saturated plane: its weak channels blend, so the
    # shipped map differs from plain division there.
    alpha_sat = masks[1].astype(np.float32)[..., None]
    plain_sat = np.nan_to_num(linear / bases[1])
    robust_sat = light_map_of(linear, bases[1], alpha_sat)
    assert not np.allclose(robust_sat, plain_sat, atol=1e-5)
