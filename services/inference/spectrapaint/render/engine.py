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

from spectrapaint.imaging import box_mean, erode
from spectrapaint.render.luts import encode_srgb


def light_map_of(
    linear_photo: np.ndarray,
    base_colour: np.ndarray,
    alpha: np.ndarray | None = None,
) -> np.ndarray:
    """Divide the linear photo by the wall's base colour (once per photo).

    The spec's division is the spine, but an uncontrolled phone photograph makes three refinements
    necessary (issue #9); all three degrade toward the plain division as the photograph gets
    easier, so a clean synthetic input still comes back as exactly ``photo / base``:

    * **Saturation blend.** A saturated Base Colour has at least one channel near zero, and
      dividing that channel amplifies sensor noise into runaway values and speckle. As the base's
      saturation rises (between ``_SATURATION_BLEND_START`` and ``_SATURATION_BLEND_END``) the
      Light Map therefore blends toward a single-brightness division — luma over luma, broadcast
      across channels — which keeps the shading but throws away the poisoned channels.
    * **A ceiling.** Even away from saturation, pixels far brighter than the full-light level are
      noise, not scene; values above ``_LIGHT_MAP_CEILING`` are clamped.
    * **Noise-proportional smoothing, where the wall is dark.** Noise is measured locally from the
      photo itself (a robust high-pass estimate — see :func:`_local_noise_sigma`). Below
      ``_NOISE_FLOOR`` nothing is smoothed; above it, each region is blended toward its local mean
      in proportion to how much noise was measured in that neighbourhood and how dark the pixel is,
      so a well-lit wall keeps its texture while an underexposed one is quieted.

    ``alpha`` is the Wall Plane matte, and the noise estimate and the smoothing are the wall's,
    not the room's: without it a curtain's fold or a window's glare decides how much the wall is
    smoothed (review of this ticket). With no matte given the whole frame is measured, which is
    the right fallback for a caller that genuinely means the whole frame — and what synthetic
    tests pass.

    A zero channel in ``base_colour`` would yield NaN (0/0) or infinity, which would travel
    through the composite into every pixel of the output. Both are mapped to 0 — an unlit result
    rather than a poisoned one — because the render must degrade, never dead-end (conventions.md
    §5). :func:`estimate_base_colour` floors its estimate, so the endpoint cannot reach this
    guard; it is here because this function is public and its callers' bases are not its to
    trust.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        light_map = linear_photo / base_colour
    light_map = np.nan_to_num(light_map, posinf=0.0, neginf=0.0, nan=0.0)

    weight = _brightness_weight_of(base_colour)
    if weight > 0.0:
        luma_base = float(np.dot(_LUMA_WEIGHTS.astype(base_colour.dtype), base_colour))
        if luma_base > 0.0:
            luma_photo = _luma_of(linear_photo)
            brightness_only = (luma_photo / luma_base)[..., None]
            light_map = (1.0 - weight) * light_map + weight * brightness_only

    light_map = np.clip(light_map, 0.0, _LIGHT_MAP_CEILING)

    # Use global sigma for the floor gate (robust decision whether to smooth at all)
    global_sigma = _measured_noise_sigma(light_map, alpha)
    # Use local sigma map for spatially-varying smoothing strength
    sigma_map = _local_noise_sigma(light_map, alpha)
    if global_sigma > _NOISE_FLOOR:
        light_map = _smooth_where_dark(light_map, sigma_map, alpha)

    return light_map.astype(linear_photo.dtype)


def _luma_of(image: np.ndarray) -> np.ndarray:
    """BT.709 luma of an HxWx3 linear image, as HxW."""
    return image @ _LUMA_WEIGHTS.astype(image.dtype)


def _brightness_weight_of(base_colour: np.ndarray) -> float:
    """How far the Base Colour's saturation pushes toward single-brightness division.

    Saturation is ``(max - min) / max``, in [0, 1]. Mapped through
    [_SATURATION_BLEND_START, _SATURATION_BLEND_END] to a blend weight: 0 keeps the three-channel
    division exactly, 1 replaces it with luma-over-luma.
    """
    bright = float(np.max(base_colour))
    if bright <= 0.0:
        return 0.0
    saturation = min(1.0, (bright - float(np.min(base_colour))) / bright)
    span = _SATURATION_BLEND_END - _SATURATION_BLEND_START
    return float(np.clip((saturation - _SATURATION_BLEND_START) / span, 0.0, 1.0))


def _local_noise_sigma(light_map: np.ndarray, alpha: np.ndarray | None = None) -> np.ndarray:
    """Per-region noise estimate modulated from the global baseline.

    The global MAD (see :func:`_measured_noise_sigma`) is a robust estimate of
    the overall sensor grain. To make this spatially varying without mistaking
    wall texture for noise, we compute a local high-frequency energy map and
    scale the global sigma by the ratio of local energy to global energy. This
    preserves the global noise floor while allowing regions with genuinely
    higher grain (e.g., underexposed corners) to smooth more.
    """
    luma = _luma_of(light_map)
    radius = max(1, round(min(luma.shape) * _NOISE_PROBE_RADIUS_FRACTION))
    residual = luma - box_mean(luma, radius)

    # Global baseline sigma
    if alpha is not None:
        alpha_f = np.asarray(alpha, dtype=np.float32)
        if alpha_f.ndim == 3:
            alpha_f = alpha_f[..., 0]
        on_wall = alpha_f > _NOISE_MATTE_THRESHOLD
        if on_wall.sum() >= _NOISE_MINIMUM_PIXELS:
            # Restrict to wall pixels only
            wall_residual = residual[on_wall]
            wall_luma = luma[on_wall]
            # Further restrict to darkest quartile of wall (issue #9 criterion)
            dark_wall = wall_luma <= np.percentile(wall_luma, 25)
            wall_residual = wall_residual[dark_wall] if dark_wall.any() else wall_residual
        else:
            # Not enough wall pixels, fall back to full frame
            wall_residual = residual
    else:
        # No alpha provided, use full frame
        on_wall = None
        wall_residual = residual
    global_mad = float(np.median(np.abs(wall_residual - np.median(wall_residual))))
    global_sigma = 1.4826 * global_mad

    # Local high-frequency energy: variance of residual in a modest window
    # (2% of side — wide enough for stable variance, narrow enough for spatial
    # variation). Variance is more selective for grain than MAD on small windows.
    energy_radius = max(1, round(min(luma.shape) * _LOCAL_ENERGY_WINDOW_FRACTION))
    local_var = (
        box_mean(residual * residual, energy_radius) - box_mean(residual, energy_radius) ** 2
    )
    global_var = float(np.mean(local_var)) if alpha is None else float(np.mean(local_var[on_wall]))

    # Scale global sigma by local/global variance ratio, clipped to avoid
    # runaway amplification from texture. A clean wall has ratio ~1 everywhere.
    if global_var > 0:
        sigma_map = global_sigma * np.sqrt(np.clip(local_var / global_var, 0.25, 4.0))
    else:
        sigma_map = np.full_like(local_var, global_sigma, dtype=np.float32)

    if alpha is not None:
        sigma_map = sigma_map * (alpha_f > _NOISE_MATTE_THRESHOLD)

    return sigma_map.astype(np.float32)


def _measured_noise_sigma(light_map: np.ndarray, alpha: np.ndarray | None = None) -> float:
    """Global robust noise estimate (kept for backward compatibility and tests).

    Computes a single sigma from the wall-wide residual MAD, but only over the
    darkest quartile of the wall to match the issue's criterion that
    "dark, underexposed walls are smoothed more".
    """
    luma = _luma_of(light_map)
    radius = max(1, round(min(luma.shape) * _NOISE_PROBE_RADIUS_FRACTION))
    residual = luma - box_mean(luma, radius)
    if alpha is not None:
        # Wall-only restriction
        alpha_f = np.asarray(alpha, dtype=np.float32)
        if alpha_f.ndim == 3:
            alpha_f = alpha_f[..., 0]
        on_wall = alpha_f > _NOISE_MATTE_THRESHOLD
        if on_wall.sum() >= _NOISE_MINIMUM_PIXELS:
            # Restrict to wall pixels only
            residual = residual[on_wall]
            luma = luma[on_wall]
            # Further restrict to darkest quartile of wall (issue #9 criterion)
            dark_wall = luma <= np.percentile(luma, 25)
            residual = residual[dark_wall] if dark_wall.any() else residual
    mad = float(np.median(np.abs(residual - np.median(residual))))
    return 1.4826 * mad


def _smooth_where_dark(
    light_map: np.ndarray,
    sigma_map: np.ndarray,
    alpha: np.ndarray | None = None,
) -> np.ndarray:
    """Blend toward the local mean where the wall is dark, in proportion to local measured noise.

    A normalised convolution: every pixel's local mean is taken weighted by its smoothing
    ``weight``, so pixels with no weight contribute nothing and are returned unchanged — and
    because the matte folds into the same weight, the local mean never reaches past the wall's
    edge to borrow a chair's Light Map values. Weight rises with the noise actually measured in
    each pixel's neighbourhood and falls with brightness, which is what lets a well-lit wall keep
    its stains while an underexposed corner is quieted (issue #9).
    """
    # Per-pixel strength from local noise estimate
    strength = np.clip((sigma_map - _NOISE_FLOOR) / (_NOISE_SIGMA_FULL - _NOISE_FLOOR), 0.0, 1.0)
    luma = _luma_of(light_map)
    ramp = (_SMOOTHING_LIT_LUMA - luma) / (_SMOOTHING_LIT_LUMA - _SMOOTHING_DARK_LUMA)
    weight = strength * np.clip(ramp, 0.0, 1.0)
    if alpha is not None:
        alpha_f = np.asarray(alpha, dtype=np.float32)
        if alpha_f.ndim == 3:
            alpha_f = alpha_f[..., 0]
        weight = weight * alpha_f
    weight = weight[..., None]

    radius = max(1, round(min(light_map.shape[:2]) * _SMOOTHING_RADIUS_FRACTION))
    coverage = np.maximum(box_mean(weight, radius), _SMOOTHING_COVERAGE_EPSILON)
    local_mean = box_mean(light_map * weight, radius) / coverage
    return (1.0 - weight) * light_map + weight * local_mean


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


def render_many(
    linear_photo: np.ndarray,
    plane_targets: list[tuple[np.ndarray, np.ndarray]],
    light_tint: np.ndarray,
) -> np.ndarray:
    """Recolour several Wall Planes, each with its own Shade, in one image.

    ``plane_targets`` is a list of ``(alpha, target_shade)`` where
    ``target_shade`` is the Shade's linear RGB triple. Base Colour is
    estimated **per group of planes sharing the same existing paint**
    (``docs/design-decisions.md:416``), never per plane — otherwise two
    planes of the same white at different brightness would both divide to
    1.0 and the room would flatten. A pre-existing Accent Wall keeps its
    own Base Colour because its tint differs. Grouping is by the wall's
    chromatic tint (base / luma), so shading differences do not split a
    group. Each group's Light Map is derived from its shared base and the
    planes are composited in the photo's left-to-right order. Alphas are
    an exclusive partition, so the order does not matter and no pixel is
    composited twice (no dark seam). All maths — including every per-plane
    composite — runs in linear RGB; the single encode happens at the end
    (issue #3 criterion 2). This keeps the maths in :mod:`spectrapaint.render`
    (conventions.md §3) and the API thin.

    The Light Map is computed **once per photo per Base Colour group** (not per
    tap), so a Shade change is just multiply–composite–encode.
    """
    if not plane_targets:
        encoded = encode_srgb(np.ascontiguousarray(linear_photo))
        return (encoded * 255.0 + 0.5).astype(np.uint8)

    alphas = [alpha for alpha, _ in plane_targets]
    grouped_bases = _grouped_base_colours(linear_photo, alphas)

    # Compute Light Map once per unique Base Colour group, then reuse for all
    # planes in that group. This is the "once per photo" preparation the spec
    # describes; the per-tap work is only multiply–composite–encode.
    light_map_cache: dict[tuple[float, float, float], np.ndarray] = {}
    for base_colour in grouped_bases:
        # Use tuple of values as key for reliable caching (arrays with same
        # values should share Light Map computation)
        base_key = tuple(base_colour.flat)
        if base_key not in light_map_cache:
            # Use the first alpha that maps to this base_colour for the Light Map
            # Find index of first occurrence of this base colour
            idx = next(i for i, bc in enumerate(grouped_bases) if tuple(bc.flat) == base_key)
            light_map_cache[base_key] = light_map_of(linear_photo, base_colour, alphas[idx])

    result_linear = linear_photo.copy()
    for (alpha, target_shade), base_colour in zip(plane_targets, grouped_bases, strict=True):
        base_key = tuple(base_colour.flat)
        light_map = light_map_cache[base_key]
        new_wall = new_wall_of(light_map, target_shade, light_tint)
        result_linear = composite_linear(result_linear, alpha, new_wall)

    encoded = encode_srgb(np.ascontiguousarray(result_linear))
    return (encoded * 255.0 + 0.5).astype(np.uint8)


# ---------------------------------------------------------------------------
# Scene estimates. These turn a bare photo into the light-map inputs, so the
# render endpoint can serve a Realistic / True Colour repaint from nothing but
# the photo and its Wall Plane matte. Both are pure numpy -- no I/O, no models.
#
# The Base Colour is now measured from the matte (ticket #6), which is what the
# spec's derivation always asked for; the interior-median stub it replaces was
# recorded as such in docs/implementation-decisions.md §17. The light tint is
# still a whole-image estimate, and that is not a stub -- the spec asks for "a
# rough whole-image estimate" on purpose, because the illuminant cancels when
# dividing by the Base Colour and what is wanted back is the room's cast, not
# the wall's.
# ---------------------------------------------------------------------------
# A median channel at or below this is treated as "the room is too dark to
# recover a base colour", not as a zero divisor -- its floor keeps the later
# light_map_of() division safe (issue #3 criterion 4: never a NaN in outputs).
_BASE_COLOUR_FLOOR = 0.02
# A band around the frame edge is excluded from the light-tint estimate: lens
# vignette and door frames are not scene colour.
_EDGE_BAND_FRACTION = 0.05

# What counts as a fully-opaque matte pixel. Not 1.0 exactly: the matte's
# interior is written as 1.0 but passes through a float resize on the way here
# in some paths, and a pixel at 0.9999 is not a boundary pixel.
_OPAQUE_COVERAGE = 0.99

# How far inside the matte the Base Colour is measured, as a fraction of the
# photo's shorter side. The spec says "eroded inward"; this is how far.
_BASE_COLOUR_EROSION_FRACTION = 0.01

# The luminance percentile the Base Colour is taken from, and the width of the
# band around it. A single percentile would select a handful of pixels on a
# small matte, and a mean of five pixels is noise.
_BASE_PERCENTILE = 90.0
_BASE_PERCENTILE_BAND = 5.0
# Luma weights for linear light, ITU-R BT.709 — the same primaries the sRGB
# transfer function in render.colour is defined against.
_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722])

# Grouping threshold: two Wall Planes whose chromatic tints are closer than
# this Euclidean distance in tint space (base / luma) share one Base Colour.
# Tint carries only chroma, so shading differences (same paint, different
# brightness) do not split a group. Calibrated so empty-corner.jpg (two
# whites at different brightness → same tint) groups, while
# corner-with-clothesline.jpg (off-white vs pink) splits. See fixtures in
# data/fixtures/rooms/ and issue #8's table.
_GROUP_TINT_THRESHOLD = 0.08

# --- Robust Light Map (issue #9). All of these exist to be tuned against real
# --- photographs; none is a derived constant. The fixtures they are meant to
# --- be tuned against live in data/fixtures/rooms/ (see the issue's table).

# The Light Map is clamped to [0, this]. A pixel this many times brighter than
# the full-light level is noise or a specular glint, not scene shading.
_LIGHT_MAP_CEILING = 4.0

# As the Base Colour's saturation ((max - min) / max) rises from START to END,
# the Light Map blends from three-channel division to single-brightness
# division, because a saturated base has channels near zero whose division is
# pure amplified noise. Below START: never blend (a neutral wall keeps its cast
# exactly). Above END: always blend.
_SATURATION_BLEND_START = 0.20
_SATURATION_BLEND_END = 0.60

# Noise is measured as a robust high-pass sigma on the Light Map's luma, over a
# window of this fraction of the photo's shorter side. Small on purpose: a
# window wide enough to span shading gradients measures the room's lighting
# instead of its grain (a 1%-of-side window at preview resolution reads shadow
# falloff as noise and over-smooths clean wall).
_NOISE_PROBE_RADIUS_FRACTION = 0.004

# Fewer wall pixels than this cannot vote in the noise estimate — the MAD of a
# handful of pixels is a coin toss, and a sliver of matte should fall back to
# the whole frame rather than pretend it measured grain.
_NOISE_MINIMUM_PIXELS = 1000

# A matte pixel is considered "on wall" when its coverage exceeds this threshold.
# Not 1.0 exactly: the matte's interior is written as 1.0 but passes through a
# float resize on the way here in some paths, and a pixel at 0.9999 is not a
# boundary pixel.
_NOISE_MATTE_THRESHOLD = 0.5

# Window for local noise energy estimation, as a fraction of the photo's
# shorter side. Wide enough for stable variance (2% ~ 14 px at 720p), narrow
# enough to track spatial noise variation across the frame.
_LOCAL_ENERGY_WINDOW_FRACTION = 0.02

# Measured noise below this means a clean photograph: skip smoothing entirely,
# so a noise-free input keeps the exact division (and its texture untouched).
# Tuned against the real fixtures measured through light_map_of with the wall
# matte (see tests/render/test_light_map_fixtures.py, which pins this):
# empty-corner.jpg — the flat-daylight control — measures 0.0045 wall-wide and
# 0.0051 in its darkest quartile, so the floor sits ~40% above with margin;
# the grainy-looking windows-with-curtains.jpg in fact measures *cleaner*
# (0.0042 — phone night denoise), and only genuinely busy regions (the
# clothesline plane, 0.017) cross it.
_NOISE_FLOOR = 0.008

# Measured noise at which dark regions get their *full* local-mean blend;
# between the floor and this the strength rises linearly. In Light Map units:
# on a wall one quarter lit, sensor grain reaches roughly this magnitude.
_NOISE_SIGMA_FULL = 0.12

# The darkness ramp smoothing follows: full local-mean blending where the
# Light Map's luma is at or below DARK, none where it is at or above LIT, and
# linearly between. Full light sits at 1.0 by construction, and LIT is set
# above it with margin: grain rides on top of full light, so a lit pixel at
# 1.0 must still count as "lit" or an ordinary grainy daylight photo would
# start blending its brightest, best-textured band (review of this ticket).
_SMOOTHING_DARK_LUMA = 0.30
_SMOOTHING_LIT_LUMA = 1.15

# The radius of the local mean used for smoothing, as a fraction of the photo's
# shorter side. Wide enough to swallow grain, narrow enough to keep shadow
# gradients recognisably gradual rather than flattened.
_SMOOTHING_RADIUS_FRACTION = 0.02

# Floor for the normalised-convolution denominator, so a region with zero
# smoothing weight cannot divide by zero (its output is not used anyway).
_SMOOTHING_COVERAGE_EPSILON = 1e-6


def estimate_base_colour(linear_photo: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """The wall's surface colour, measured from the Wall Plane matte.

    The spec pins this derivation, and every step of it is load-bearing
    (docs/specs/v1-spectrapaint.md, "The render engine"):

    * **Fully-opaque matte pixels only, eroded inward.** A boundary pixel is a
      blend of wall and whatever is behind the wall's edge, so its colour is
      partly the ceiling's. Averaging those in tints the Base Colour toward
      everything the wall is next to.
    * **Ranked by luminance, and near the 90th percentile.** The Base Colour is
      the paint "as it appears under full light" (CONTEXT.md), so the estimate
      wants the brightest genuinely-wall pixels -- the ones in full light --
      rather than the average of a wall that is half in shadow. Not the very
      brightest, which are specular highlights and blown pixels.
    * **Their mean RGB, not a per-channel percentile.** Taking the 90th
      percentile of each channel independently would compose a colour from
      three different sets of pixels and neutralise the wall's cast, which is
      the one thing this estimate exists to capture.

    ``alpha`` is required rather than optional. A caller with no matte does not
    have a wall yet, and quietly falling back to a whole-photo statistic is how
    a render of the sofa's colour would look exactly like a working one.
    """

    coverage = np.asarray(alpha, dtype=np.float32).reshape(alpha.shape[0], alpha.shape[1])
    radius = max(1, round(min(coverage.shape) * _BASE_COLOUR_EROSION_FRACTION))
    interior = erode(coverage >= _OPAQUE_COVERAGE, radius)

    if not interior.any():
        # A matte with no fully-opaque interior at all -- a wall visible only in
        # slivers between furniture. Rather than dead-end, fall back to whatever
        # is opaque before erosion, and only then to the matte's most-covered
        # pixels, so a thin wall still gets a colour measured from *itself*.
        interior = coverage >= _OPAQUE_COVERAGE
    if not interior.any():
        interior = coverage >= max(coverage.max() * 0.9, np.finfo(np.float32).tiny)

    pixels = linear_photo[interior]
    luminance = pixels @ _LUMA_WEIGHTS.astype(pixels.dtype)

    low, high = np.percentile(
        luminance, [_BASE_PERCENTILE - _BASE_PERCENTILE_BAND, _BASE_PERCENTILE]
    )
    in_band = (luminance >= low) & (luminance <= high)
    # A band can come back empty when the wall is a single flat value and every
    # percentile lands on the same number; the equality check below is what
    # keeps that case from producing a NaN mean.
    selected = pixels[in_band] if in_band.any() else pixels

    return np.maximum(selected.mean(axis=0), _BASE_COLOUR_FLOOR).astype(linear_photo.dtype)


def estimate_light_tint(linear_photo: np.ndarray) -> np.ndarray:
    """The room's light colour, as the photo's dominant chroma.

    Realistic mode tints the shade by the colour of the light actually in the
    room (CONTEXT.md). Without the segmentation mattes the true light sources
    cannot be masked, so the approximation is the interior median — the same
    statistic the base colour uses, for the same reason a lamp must not drag it.

    Dividing that median by its **luma** leaves a factor that carries only the
    cast, not the brightness: neutral light comes back as exactly (1, 1, 1), so
    a grey room's Shade is rendered as the chip. Luma is the BT.709 sum, the
    weighting the sRGB primaries define; a plain channel average would call a
    saturated blue as bright as a saturated green and tint away from the cast it
    was measuring. True Colour mode does not apply the tint at all.
    """
    interior = _interior(linear_photo)
    median = np.median(interior, axis=(0, 1))
    luma = float(np.dot(_LUMA_WEIGHTS, median))
    if luma <= 0.0:
        return np.ones(3, dtype=linear_photo.dtype)
    return (median / luma).astype(linear_photo.dtype)


def _tint_of(base_colour: np.ndarray) -> np.ndarray:
    """Chromatic tint of a Base Colour: base / luma, brightness removed.

    Two planes of the same paint at different brightness have the same tint,
    so grouping by tint distance keeps them together while an Accent Wall
    with a different chroma splits. Luma uses the same BT.709 weights as
    the estimate itself.
    """
    luma = float(np.dot(_LUMA_WEIGHTS, base_colour))
    if luma <= 0.0:
        return base_colour
    return base_colour / luma


def _grouped_base_colours(linear_photo: np.ndarray, alphas: list[np.ndarray]) -> list[np.ndarray]:
    """One Base Colour per plane, grouped by existing paint.

    Steps per the spec's grouping rule:

    1. Estimate a per-plane Base Colour with :func:`estimate_base_colour`
       (fully-opaque, eroded, 90th-percentile mean RGB).
    2. Cluster by tint distance (``_GROUP_TINT_THRESHOLD``). Same paint →
       same tint → same group, so relative brightness survives.
    3. For each group, re-estimate one Base Colour from the **union** of
       its planes' interior pixels. A group of one reuses its single
       estimate to avoid a second percentile pass; a group of several
       merges alphas (partition → sum ≤ 1) and estimates once.

    Returns a list aligned with ``alphas``: each entry is the shared
    Base Colour its plane belongs to.
    """
    if len(alphas) <= 1:
        return [estimate_base_colour(linear_photo, alphas[0])] if alphas else []

    individual = [estimate_base_colour(linear_photo, a) for a in alphas]
    tints = [_tint_of(b) for b in individual]

    groups: list[list[int]] = []
    assignment: list[int] = [-1] * len(alphas)
    for idx, tint in enumerate(tints):
        found = -1
        for g_idx, members in enumerate(groups):
            rep = members[0]
            if float(np.linalg.norm(tint - tints[rep])) < _GROUP_TINT_THRESHOLD:
                found = g_idx
                break
        if found == -1:
            groups.append([idx])
            assignment[idx] = len(groups) - 1
        else:
            groups[found].append(idx)
            assignment[idx] = found

    group_bases: list[np.ndarray] = []
    for members in groups:
        if len(members) == 1:
            group_bases.append(individual[members[0]])
        else:
            # Union of the group's wall pixels — partition guarantees no double
            # counting beyond 1.0, clip keeps the matte in [0,1].
            # alphas are HxWx1; sum over members stays HxWx1.
            stacked = np.stack([np.asarray(alphas[i], dtype=np.float32) for i in members], axis=0)
            union = np.clip(np.sum(stacked, axis=0), 0.0, 1.0)
            group_bases.append(estimate_base_colour(linear_photo, union))

    return [group_bases[assignment[i]] for i in range(len(alphas))]


def _interior(linear_photo: np.ndarray) -> np.ndarray:
    """The photo minus a border band, so frame edges and vignette are excluded."""
    height, width = linear_photo.shape[:2]
    band = max(1, round(min(height, width) * _EDGE_BAND_FRACTION))
    return linear_photo[band : height - band, band : width - band]
