"""The robust Light Map against the real photographs it was tuned on (issue #9).

The tunables at the top of ``engine.py`` exist to be set against real photographs, and a tuning
that no test pins can silently drift back. These tests run the shipped ``light_map_of`` — no
models, just the fixture photographs and their hand labels — and pin where each fixture lands:

* ``empty-corner.jpg``, the flat-daylight control, measures below ``_NOISE_FLOOR`` and so keeps
  the exact division: its stains and scuffs must survive a repaint untouched.
* ``windows-with-curtains.jpg``, the underexposed night shot, repainted pale degrades gracefully
  — finite, bounded, no NaN in the darkest quartile.
* ``corner-with-clothesline.jpg``, split by its hand-labelled planes, engages the saturation
  blend on the saturated plane while the neutral one keeps its cast exactly.

The numbers in the constant comments in ``engine.py`` were measured with exactly this script; if
one of these tests fails after a retune, re-record the reasoning in the comment, not just the
constant.
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from spectrapaint.render.engine import (
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

    If this fixture crosses the noise floor, every slightly grainy daylight photo will have its
    stains smoothed away — the failure the issue's table assigns this photograph to catch.
    """
    photo = FIXTURE_DIR / "empty-corner.jpg"
    alpha = wall_matte(photo)
    linear = linear_photo(photo)
    base = estimate_base_colour(linear, alpha)

    plain = np.nan_to_num(linear / base)
    robust = light_map_of(linear, base, alpha)

    # The daylight control must not be smoothed: robust map equals plain division.
    assert np.allclose(robust, plain, atol=1e-5)


@pytest.mark.fixtures
@pytest.mark.skipif(not rooms(), reason=NO_FIXTURES)
def test_the_night_fixture_repainted_pale_degrades_gracefully() -> None:
    """The darkest wall in the fixtures, repainted in the palest shade: sane bytes only.

    windows-with-curtains is shot at night under one tube light; its darkest quartile is the
    input that produces runaway values if the Light Map divides carelessly (issue #9's table).
    """
    photo = FIXTURE_DIR / "windows-with-curtains.jpg"
    alpha = wall_matte(photo)
    linear = linear_photo(photo)
    base = estimate_base_colour(linear, alpha)

    light_map = light_map_of(linear, base, alpha)
    assert np.isfinite(light_map).all()

    # Repaint pale and check that every pixel stays finite and in the valid byte range.
    from spectrapaint.render.colour import lab_to_linear_rgb

    pale = lab_to_linear_rgb(np.array([90.0, 0.0, 0.0], dtype=np.float64))
    new_wall = light_map * pale
    composite = alpha * new_wall + (1.0 - alpha) * linear
    assert np.isfinite(composite).all()
    assert (composite >= 0.0).all() and (composite <= 1.0).all()

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
    """Split by the hand-labelled planes: saturated wall blends, neutral wall keeps its cast.

    corner-with-clothesline is the issue's saturation-blend fixture: a near-neutral wall and a
    saturated one in the same frame. The blend is decided per Base Colour, so the two planes
    must come out on different sides of it.
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

    # Observable behaviour: neutral plane keeps exact division, saturated plane blends.
    weights = []
    for mask in masks:
        alpha = mask.astype(np.float32)[..., None]
        base = estimate_base_colour(linear, alpha)
        # Use light_map_of to check if saturation blend engaged
        plain = np.nan_to_num(linear / base)
        robust = light_map_of(linear, base, alpha)
        # If saturation blend engaged, robust != plain
        weights.append(not np.allclose(robust, plain, atol=1e-5))

    neutral_blended, saturated_blended = weights
    assert not neutral_blended, "the neutral plane must keep its three-channel cast exactly"
    assert saturated_blended, "the saturated plane's weak channels must blend toward brightness"
