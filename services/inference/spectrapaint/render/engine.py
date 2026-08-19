"""The recolour engine: a pure function with no I/O (issue #3 criterion 1).

Test Seam 2 of the spec. The formula, pinned by render/README.md and
docs/specs/v1-spectrapaint.md::

    light_map = linear_photo / base_colour                 (once per photo)
    new_wall  = light_map * target_shade * light_tint      (per Shade change)
    output    = alpha * new_wall + (1 - alpha) * linear_photo

Every step runs in linear RGB, including the alpha composite (criterion 2);
compositing in gamma space produces dark fringing. The only gamma step is the
final encode, done on a copy so caller arrays are never mutated.

Per-photo vs per-tap: light_map_of() is the photo preparation the contract
caches once; render() is the per-tap recolour. Both are pure numpy -- no files,
no network, no models -- which is what makes tests/render/ fast and
deterministic.
"""

import numpy as np

from spectrapaint.render.luts import encode_srgb


def light_map_of(linear_photo: np.ndarray, base_colour: np.ndarray) -> np.ndarray:
    """Divide the linear photo by the wall's base colour (once per photo).

    NaN/inf from a zero or deep-colour channel is clamped to 0 rather than
    propagated (the spec's "never dead-end" rule -- no NaN in outputs).
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        light_map = linear_photo / base_colour
    return np.nan_to_num(light_map, posinf=0.0, neginf=0.0, nan=0.0)


def new_wall_of(
    light_map: np.ndarray,
    target_shade: np.ndarray,
    light_tint: np.ndarray,
) -> np.ndarray:
    """The repainted wall before compositing (per Shade change).

    ``light_map * target_shade * light_tint`` is the spec's per-tap formula.
    """
    return light_map * target_shade * light_tint


def composite_linear(
    linear_photo: np.ndarray,
    alpha: np.ndarray,
    new_wall: np.ndarray,
) -> np.ndarray:
    """Blend the repainted wall over the original photo, in linear RGB.

    ``alpha * new_wall + (1 - alpha) * linear_photo`` is the spec's output
    formula. Compositing in gamma space would produce dark fringing at matte
    edges, so the blend happens before any encoding.
    """
    return alpha * new_wall + (1.0 - alpha) * linear_photo


def render(
    linear_photo: np.ndarray,
    alpha: np.ndarray,
    light_map: np.ndarray,
    target_shade: np.ndarray,
    light_tint: np.ndarray,
) -> np.ndarray:
    """Recolour the wall and return sRGB uint8, ready to be saved as an image.

    The composite runs in linear space; encoding happens once, at the end.
    """
    new_wall = new_wall_of(light_map, target_shade, light_tint)
    composite = composite_linear(linear_photo, alpha, new_wall)
    encoded = encode_srgb(np.ascontiguousarray(composite))
    return (encoded * 255.0 + 0.5).astype(np.uint8)


# ---------------------------------------------------------------------------
# Scene estimates. These turn a bare photo into the light-map inputs, so the
# render endpoint can serve a Realistic / True Colour repaint from nothing but
# the photo. Both are pure numpy -- no I/O -- and both are deliberate stubs
# pending the segmentation tickets: the true wall base colour and the true
# light colour require the real Wall Plane mattes.
# ---------------------------------------------------------------------------
# A median channel at or below this is treated as "the room is too dark to
# recover a base colour", not as a zero divisor -- its floor keeps the later
# light_map_of() division safe (issue #3 criterion 4: never a NaN in outputs).
_BASE_COLOUR_FLOOR = 0.02
# A band around the frame edge is excluded from both estimates: lens vignette
# and door frames are not scene colour.
_EDGE_BAND_FRACTION = 0.05


def estimate_base_colour(linear_photo: np.ndarray) -> np.ndarray:
    """The wall's surface colour, as the photo's interior median.

    The wall is assumed to dominate the frame for this stub; the true wall-only
    estimate arrives with the segmentation tickets. Median over mean so a lamp
    or a window cannot drag the estimate white.
    """
    interior = _interior(linear_photo)
    median = np.median(interior, axis=(0, 1))
    return np.maximum(median, _BASE_COLOUR_FLOOR).astype(linear_photo.dtype)


def estimate_light_tint(linear_photo: np.ndarray) -> np.ndarray:
    """The room's light colour, as the photo's dominant chroma.

    Realistic mode tints the shade by the colour of the light actually in the
    room (CONTEXT.md). Without the segmentation mattes the true light sources
    cannot be masked, so the approximation is the whole-photo interior median:
    a warm-lit room makes the average scene colour warm. Dividing by its own
    luma isolates hue and keeps neutral light exactly (1, 1, 1); True Colour
    mode simply does not apply this tint at all.
    """
    interior = _interior(linear_photo)
    median = np.median(interior, axis=(0, 1))
    luma = float(np.mean(median))
    if luma == 0.0:
        return np.ones(3, dtype=linear_photo.dtype)
    return (median / luma).astype(linear_photo.dtype)


def _interior(linear_photo: np.ndarray) -> np.ndarray:
    """The photo minus a border band, so frame edges and vignette are excluded."""
    height, width = linear_photo.shape[:2]
    band = max(1, round(min(height, width) * _EDGE_BAND_FRACTION))
    return linear_photo[band : height - band, band : width - band]
