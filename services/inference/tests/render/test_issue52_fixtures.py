"""Seam 2 — Issue #52 on the real sunlit and shadowed fixtures (review 4 and 2).

Fast lane, no models: the fixture photographs plus their hand-drawn wall
labels, through the pure ``estimate_base_colour`` / ``light_map_of`` /
``render`` path. The synthetic probes in ``test_issue52.py`` pin the mechanism
(ΔE00, hue angles); these pin that the same code reads correctly on the
Dealer-testing rooms from #48:

* ``blue-wall-sunlit.jpg`` is the page-6 photograph itself: a pale-blue wall
  with warm sun, repainted pale blue, must stay on the blue side (Lab b* ≤ 0)
  and brighter where the sun falls — never the pale-yellow blob (b* +14.7).
* ``green-room-sunlit.jpg`` and ``yellow-wall-sunlight-band.jpg`` repainted
  orange must keep the Shade's hue within 5° between their sunlit tenth and
  their shaded quartile, brighter in the sun.
* ``dim-room-with-mirror.jpg`` repainted neutral grey must keep at least 40%
  of the chair-shadow fan's log-depth (measured 0.52): suppression may soften
  mid-frequency shadows, never flatten them.

Sunlit means the brightest tenth of the labelled wall, shaded the darkest
quartile — the same quantiles the models-lane recall criteria use
(``tests/api/test_walls.py``). Thresholds carry the measured values in the
assert messages, like the other fixture tests.
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from spectrapaint.render.colour import lab_to_linear_rgb, srgb_to_linear
from spectrapaint.render.engine import estimate_base_colour, light_map_of, render
from spectrapaint.render.luts import linearise_u8

FIXTURE_DIR = Path(__file__).resolve().parents[4] / "data" / "fixtures" / "rooms"
NO_FIXTURES = "no room fixtures in data/fixtures/rooms — see its README"

_LUMA = np.array([0.2126, 0.7152, 0.0722])

# Test-only linear → Lab (D65, 2°), same maths as test_issue52.py, kept local
# so this file depends only on the implementation under test.
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


def _hue_deg(a: float, b: float) -> float:
    return float(np.degrees(np.arctan2(b, a)) % 360.0)


def _hue_diff_deg(lab1: np.ndarray, lab2: np.ndarray) -> float:
    diff = abs(_hue_deg(lab1[1], lab1[2]) - _hue_deg(lab2[1], lab2[2]))
    return min(diff, 360.0 - diff)


def _labelled_wall(photo: Path) -> tuple[np.ndarray, np.ndarray]:
    """Linear photo plus hand-drawn wall mask (True on wall)."""
    with Image.open(photo) as image:
        linear = linearise_u8(np.asarray(image.convert("RGB"), dtype=np.uint8))
    with Image.open(photo.with_suffix(".wall.png")) as image:
        wall = np.asarray(image.convert("L"), dtype=np.uint8) > 127
    return linear, wall


def _render_lab(
    linear: np.ndarray, wall: np.ndarray, shade_lab: tuple[float, float, float]
) -> np.ndarray:
    alpha = wall.astype(np.float32)[..., None]
    base = estimate_base_colour(linear, alpha)
    light_map = light_map_of(linear, base, alpha)
    shade = lab_to_linear_rgb(np.array(shade_lab, dtype=np.float64)).astype(np.float32)
    out = render(linear, alpha, light_map, shade, np.ones(3, dtype=np.float32))
    return _linear_to_lab(srgb_to_linear(out.astype(np.float64) / 255.0))


def _sunlit_and_shaded(linear: np.ndarray, wall: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    luminance = linear @ _LUMA.astype(np.float32)
    wall_lum = luminance[wall]
    sunlit = wall & (luminance >= np.quantile(wall_lum, 0.90))
    shaded = wall & (luminance <= np.quantile(wall_lum, 0.25))
    return sunlit, shaded


@pytest.mark.fixtures
@pytest.mark.skipif(not (FIXTURE_DIR / "blue-wall-sunlit.jpg").exists(), reason=NO_FIXTURES)
def test_page_six_wall_stays_blue_in_the_sun() -> None:
    """Page 6's wall, pale-blue Shade: no yellow blob on the real photo either."""
    linear, wall = _labelled_wall(FIXTURE_DIR / "blue-wall-sunlit.jpg")
    lab = _render_lab(linear, wall, (85.0, -5.0, -12.0))
    sunlit, shaded = _sunlit_and_shaded(linear, wall)

    lab_sun = np.median(lab[sunlit], axis=0)
    lab_shade = np.median(lab[shaded], axis=0)
    # Measured: sun b* −7.5, shaded b* −3.0 (today's code renders +14.7-style
    # yellow on the synthetic analogue).
    assert float(lab_sun[2]) <= 0.0, f"sunlit wall went yellow: {lab_sun}"
    assert float(lab_shade[2]) <= 0.0, f"shaded wall went yellow: {lab_shade}"
    assert float(lab_sun[0]) > float(lab_shade[0]), "sun must read brighter"


@pytest.mark.fixtures
@pytest.mark.skipif(not (FIXTURE_DIR / "green-room-sunlit.jpg").exists(), reason=NO_FIXTURES)
def test_green_room_sun_keeps_the_shade_hue() -> None:
    """Daylight on the back wall, orange Shade: sunlit and shaded share the hue."""
    linear, wall = _labelled_wall(FIXTURE_DIR / "green-room-sunlit.jpg")
    lab = _render_lab(linear, wall, (65.0, 35.0, 60.0))
    sunlit, shaded = _sunlit_and_shaded(linear, wall)

    lab_sun = np.median(lab[sunlit], axis=0)
    lab_shade = np.median(lab[shaded], axis=0)
    # Measured hue difference 0.9° (synthetic budget: 5°).
    assert _hue_diff_deg(lab_sun, lab_shade) < 5.0, f"{lab_sun} vs {lab_shade}"
    assert float(lab_sun[0]) > float(lab_shade[0]), "sun must read brighter"


@pytest.mark.fixtures
@pytest.mark.skipif(
    not (FIXTURE_DIR / "yellow-wall-sunlight-band.jpg").exists(), reason=NO_FIXTURES
)
def test_sunlight_band_reads_brighter_in_the_same_hue() -> None:
    """Page 7's wall, orange Shade: the band is the Shade, brighter."""
    linear, wall = _labelled_wall(FIXTURE_DIR / "yellow-wall-sunlight-band.jpg")
    lab = _render_lab(linear, wall, (65.0, 35.0, 60.0))
    sunlit, shaded = _sunlit_and_shaded(linear, wall)

    lab_sun = np.median(lab[sunlit], axis=0)
    lab_shade = np.median(lab[shaded], axis=0)
    # Measured hue difference 0.0° (synthetic budget: 5°).
    assert _hue_diff_deg(lab_sun, lab_shade) < 5.0, f"{lab_sun} vs {lab_shade}"
    assert float(lab_sun[0]) > float(lab_shade[0]), "band must read brighter"


@pytest.mark.fixtures
@pytest.mark.skipif(not (FIXTURE_DIR / "dim-room-with-mirror.jpg").exists(), reason=NO_FIXTURES)
def test_a_real_shadow_keeps_its_depth() -> None:
    """The chair-shadow fan on the wainscot survives suppression (review 2).

    Repainted neutral grey so chroma cannot hide a luminance flattening: the
    log-depth between the labelled wall's lit and shadowed quartiles must keep
    at least 40% (measured 0.52). Suppression may soften mid-frequency shadow,
    never flatten it — the ghosting failure mode.
    """
    linear, wall = _labelled_wall(FIXTURE_DIR / "dim-room-with-mirror.jpg")
    luminance = linear @ _LUMA.astype(np.float32)
    wall_lum = luminance[wall]
    dark = wall & (luminance <= np.quantile(wall_lum, 0.25))
    lit = wall & (luminance >= np.quantile(wall_lum, 0.75))

    depth_in = float(np.log(np.median(luminance[lit]) / np.median(luminance[dark])))

    alpha = wall.astype(np.float32)[..., None]
    base = estimate_base_colour(linear, alpha)
    light_map = light_map_of(linear, base, alpha)
    grey = lab_to_linear_rgb(np.array([70.0, 0.0, 0.0], dtype=np.float64)).astype(np.float32)
    out = render(linear, alpha, light_map, grey, np.ones(3, dtype=np.float32))
    lum_out = srgb_to_linear(out.astype(np.float64) / 255.0) @ _LUMA
    depth_out = float(np.log(np.median(lum_out[lit]) / np.median(lum_out[dark])))

    assert depth_out / depth_in >= 0.40, f"kept {depth_out / depth_in:.2f} (in {depth_in:.2f})"
    assert float(np.median(lum_out[lit])) > float(np.median(lum_out[dark]))
