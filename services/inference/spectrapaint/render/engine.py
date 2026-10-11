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
from spectrapaint.render.colour import srgb_to_linear
from spectrapaint.render.luts import encode_srgb


def light_map_of(
    linear_photo: np.ndarray,
    base_colour: np.ndarray,
    alpha: np.ndarray | None = None,
) -> np.ndarray:
    """Divide the linear photo by the wall's base colour (once per photo).

    The spec's division is the spine, but an uncontrolled phone photograph makes refinements
    necessary (issues #9 and #52); all degrade toward the plain division as the photograph gets
    easier, so a clean synthetic input still comes back as exactly ``photo / base``:

    * **Saturation blend.** A saturated Base Colour has at least one channel near zero, and
      dividing that channel amplifies sensor noise into runaway values and speckle. As the base's
      saturation rises (between ``_SATURATION_BLEND_START`` and ``_SATURATION_BLEND_END``) the
      Light Map therefore blends toward a single-brightness division — luma over luma, broadcast
      across channels — which keeps the shading but throws away the poisoned channels.
    * **Stain suppression (issue #52, decision 1).** The Light Map is split into ``shading``
      (HxW brightness) and ``chroma`` (HxWx3, about 1 on a clean wall). Chroma deviations are
      pulled toward the room's large-scale chroma and mid-frequency luminance blotches are
      scaled back in log space, with contact shadows near the matte edge protected. Lighting,
      shadows and texture are kept; stains and patches are removed before repainting.
    * **Capped sun tint (issue #52, decision 2).** In highlights only
      (``_HIGHLIGHT_START``–``_HIGHLIGHT_FULL`` on shading) a bounded share ``_SUN_TINT_KEEP``
      of the chroma deviation is kept; the rest is brightness only. Sunlit patches read as the
      chosen Shade, brighter and at most slightly warm.
    * **Clipped photo pixels.** Where the photo is at or above ``_CLIPPED_LEVEL`` in any
      channel the Light Map carries no information; chroma there is the local room chroma
      while shading is kept.
    * **A ceiling.** Even away from saturation, pixels far brighter than the full-light level are
      noise, not scene; values above ``_LIGHT_MAP_CEILING`` are clamped.
    * **Noise-proportional smoothing, where the wall is dark.** Noise is measured locally from the
      photo itself (a robust high-pass estimate — see :func:`_local_noise_sigma`). Below
      ``_NOISE_FLOOR`` nothing is smoothed; above it, each region is blended toward its local mean
      in proportion to how much noise was measured in that neighbourhood and how dark the pixel is,
      so a well-lit wall keeps its texture while an underexposed one is quieted.

    ``alpha`` is the Wall Plane matte, and every blur here is the wall's, not the room's: the
    matte folds into each blur as a normalised convolution (as :func:`_smooth_where_dark` does),
    so a chair's colour or glare never leaks into the wall. With no matte given the whole frame
    is measured, which is the right fallback for a caller that genuinely means the whole frame —
    and what synthetic tests pass.

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
    luma_base = float(np.dot(_LUMA_WEIGHTS.astype(base_colour.dtype), base_colour))
    if weight > 0.0 and luma_base > 0.0:
        luma_photo = _luma_of(linear_photo)
        brightness_only = (luma_photo / luma_base)[..., None]
        light_map = (1.0 - weight) * light_map + weight * brightness_only

    if luma_base <= 0.0:
        luma_base = float(np.dot(_LUMA_WEIGHTS.astype(np.float64), np.maximum(base_colour, 1e-6)))

    # --- Split into shading (brightness) and chroma (colour) (issue #52 A). ---
    # shading × chroma reproduces the Light Map above exactly.
    luma_photo = _luma_of(linear_photo).astype(np.float64)
    shading = (luma_photo / max(luma_base, 1e-6)).astype(np.float64)
    shading_safe = np.maximum(shading, 1e-6)
    chroma = (light_map.astype(np.float64) / shading_safe[..., None]).astype(np.float64)

    short_side = min(linear_photo.shape[:2])
    illum_radius = max(1, round(short_side * _STAIN_ILLUMINATION_RADIUS_FRACTION))
    texture_radius = max(1, round(short_side * _STAIN_TEXTURE_RADIUS_FRACTION))
    alpha_f = _alpha_hw(alpha)

    # Large-scale room chroma: bounce light and window cast survive; a stain's hue does not.
    room_chroma = _matte_weighted_blur_3(chroma, alpha_f, illum_radius)
    chroma_out = (
        1.0 - _STAIN_CHROMA_SUPPRESSION
    ) * chroma + _STAIN_CHROMA_SUPPRESSION * room_chroma

    # --- Mid-frequency luminance blotch suppression in log space (issue #52 B). ---
    log_s = np.log(np.maximum(shading, 1e-6))
    illumination = _matte_weighted_blur_3(log_s, alpha_f, illum_radius)
    fine = log_s - _matte_weighted_blur_3(log_s, alpha_f, texture_radius)
    blotch = log_s - illumination - fine
    protect = _edge_protection(alpha_f, shading.shape)
    strength = _STAIN_SUPPRESSION * (1.0 - protect)
    shading_out = np.exp(illumination + fine + (1.0 - strength) * blotch)

    # --- Clipped photo pixels carry no chroma (issue #52 F): keep shading. ---
    clipped_thresh = float(srgb_to_linear(np.array([_CLIPPED_LEVEL / 255.0]))[0])
    clipped = (linear_photo >= clipped_thresh).any(axis=-1)
    if clipped.any():
        chroma_out[clipped] = room_chroma[clipped]

    # --- Capped sun tint in highlights (issue #52 D). ---
    highlight = _smoothstep(_HIGHLIGHT_START, _HIGHLIGHT_FULL, shading_out)
    keep = 1.0 + (_SUN_TINT_KEEP - 1.0) * highlight
    chroma_out = 1.0 + (chroma_out - 1.0) * keep[..., None]

    light_map = (shading_out[..., None] * chroma_out).astype(np.float64)
    light_map = np.clip(light_map, 0.0, _LIGHT_MAP_CEILING)

    # Use global sigma for the floor gate (robust decision whether to smooth at all)
    global_sigma = _measured_noise_sigma(light_map, alpha)
    # Use local sigma map for spatially-varying smoothing strength
    sigma_map = _local_noise_sigma(light_map, alpha)
    if global_sigma > _NOISE_FLOOR:
        light_map = _smooth_where_dark(light_map, sigma_map, alpha)

    return light_map.astype(linear_photo.dtype)


def _alpha_hw(alpha: np.ndarray | None) -> np.ndarray | None:
    """Wall Plane matte as HxW float32, or None when no matte was given."""
    if alpha is None:
        return None
    alpha_f = np.asarray(alpha, dtype=np.float32)
    if alpha_f.ndim == 3:
        alpha_f = alpha_f[..., 0]
    return alpha_f


def _blur_3(values: np.ndarray, radius: int) -> np.ndarray:
    """Three passes of :func:`box_mean`: a Gaussian approximation, O(1) per pixel."""
    out = values.astype(np.float64, copy=True)
    for _ in range(3):
        out = box_mean(out, radius).astype(np.float64)
    return out


def _matte_weighted_blur_3(
    values: np.ndarray, alpha_f: np.ndarray | None, radius: int
) -> np.ndarray:
    """Large blur as a normalised convolution weighted by the matte.

    Each of the three :func:`box_mean` passes divides the weighted sum by the
    blurred weight, exactly as :func:`_smooth_where_dark` does, so wall pixels
    never borrow a chair's values. Where the blurred weight has no coverage
    (outside the matte, e.g. the other plane sharing a grouped Base Colour),
    the original value is kept so a Light Map computed with one plane's matte
    stays valid for the whole group. With no matte the whole frame is blurred.
    Accepts HxW or HxWx3; the window always spans the two spatial axes.
    """
    values64 = values.astype(np.float64, copy=False)
    if alpha_f is None:
        return _blur_3(values64, radius)
    weight = np.asarray(alpha_f, dtype=np.float64)
    squeeze = values64.ndim == 2
    values_exp = values64 if not squeeze else values64[..., None]
    weight_exp = weight[..., None]
    out = values_exp.copy()
    for _ in range(3):
        num = box_mean(out * weight_exp, radius).astype(np.float64)
        den = box_mean(weight, radius).astype(np.float64)
        has = den > 1e-3
        # Where coverage exists use the normalized mean, else keep previous —
        # so pixels outside the matte keep their own values instead of 0.
        norm = num / np.maximum(den[..., None], _SMOOTHING_COVERAGE_EPSILON)
        out = np.where(has[..., None], norm, out)
    return out[..., 0] if squeeze else out


def _edge_protection(alpha_f: np.ndarray | None, shape: tuple[int, ...]) -> np.ndarray:
    """Ramp from 1 at the matte edge to 0 inside (issue #52 B).

    Contact shadows sit at occluders, which are matte boundaries, so they are
    mostly kept while open-wall stains are suppressed. Single box blur of the
    eroded interior gives a linear ramp over ``_STAIN_EDGE_PROTECT_RADIUS``.
    The photo border is also protected: box blurs pad by replication, which
    would otherwise flatten illumination gradients at the frame edge and read
    as a false blotch.
    """
    height, width = shape[:2]
    radius = max(1, round(min(height, width) * _STAIN_EDGE_PROTECT_RADIUS_FRACTION))
    rows = np.arange(height, dtype=np.float64)[:, None]
    cols = np.arange(width, dtype=np.float64)[None, :]
    dist_border = np.minimum(
        np.minimum(rows, cols), np.minimum(height - 1 - rows, width - 1 - cols)
    )
    border_protect = np.clip(1.0 - dist_border / float(radius), 0.0, 1.0)
    if alpha_f is None:
        return border_protect
    mask = np.asarray(alpha_f) > _NOISE_MATTE_THRESHOLD
    if not mask.any():
        return border_protect
    interior = erode(mask, radius)
    blurred = box_mean(interior.astype(np.float32), radius).astype(np.float64)
    matte_protect = np.clip(1.0 - blurred, 0.0, 1.0)
    return np.maximum(matte_protect, border_protect)


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    """0 below edge0, 1 above edge1, smooth Hermite ramp between."""
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


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
    its texture while an underexposed corner is quieted (issue #9). Stain suppression lives in
    :func:`light_map_of` (issue #52); this step only quiets measured sensor grain.
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


def _highlight_rolloff(composite: np.ndarray, matte: np.ndarray) -> np.ndarray:
    """Hue-preserving soft knee above ``_HIGHLIGHT_KNEE`` (issue #52 E).

    Where the peak channel exceeds the knee, all three channels scale by one
    factor along ``knee + (1-knee)*(1-exp(-(peak-knee)/(1-knee)))`` toward 1.0,
    so hue is kept and no channel hard-clips to 255. Only inside the matte
    (``matte > 0``); ``alpha == 0`` pixels are bit-identical to today.
    """
    matte_hw = np.asarray(matte, dtype=np.float32)
    if matte_hw.ndim == 3:
        matte_hw = matte_hw[..., 0]
    inside = matte_hw > 0.0
    if not inside.any():
        return composite
    peak = composite.max(axis=-1, keepdims=True)
    over = (peak > _HIGHLIGHT_KNEE) & inside[..., None]
    if not over.any():
        return composite
    knee = _HIGHLIGHT_KNEE
    scaled = knee + (1.0 - knee) * (1.0 - np.exp(-(peak - knee) / (1.0 - knee)))
    factor = np.where(over, scaled / np.maximum(peak, 1e-6), 1.0)
    return composite * factor


def render(
    linear_photo: np.ndarray,
    alpha: np.ndarray,
    light_map: np.ndarray,
    target_shade: np.ndarray,
    light_tint: np.ndarray,
) -> np.ndarray:
    """Recolour the wall and return sRGB uint8, ready to be saved as an image.

    The composite runs in linear space; a hue-preserving highlight roll-off
    runs inside the matte before the single encode at the end.
    """
    new_wall = new_wall_of(light_map, target_shade, light_tint)
    composite = composite_linear(linear_photo, alpha, new_wall)
    composite = _highlight_rolloff(composite, alpha)
    encoded = encode_srgb(np.ascontiguousarray(composite))
    return (encoded * 255.0 + 0.5).astype(np.uint8)


def render_many(
    linear_photo: np.ndarray,
    plane_targets: list[tuple[np.ndarray, np.ndarray]],
    light_tint: np.ndarray,
    surfaces: list[str] | None = None,
) -> np.ndarray:
    """Recolour several Paintable Planes (walls and ceilings), each with its own Shade.

    ``plane_targets`` is a list of ``(alpha, target_shade)`` where
    ``target_shade`` is the Shade's linear RGB triple. Base Colour is
    estimated **per group of planes sharing the same existing paint**
    (``docs/design-decisions.md:416``), never per plane — otherwise two
    planes of the same white at different brightness would both divide to
    1.0 and the room would flatten. A pre-existing Accent Wall keeps its
    own Base Colour because its tint differs. Grouping is by the wall's
    chromatic tint (base / luma), so shading differences do not split a
    group. **A ceiling is never grouped with a wall**, even when the two
    happen to be a similar pale colour, or the room's light modelling breaks
    silently (CONTEXT.md Ceiling Plane). Each group's Light Map is derived
    from its shared base and the planes are composited in the photo's
    left-to-right order. Alphas are an exclusive partition, so the order
    does not matter and no pixel is composited twice (no dark seam). All
    maths — including every per-plane composite — runs in linear RGB; the
    single encode happens at the end (issue #3 criterion 2). This keeps the
    maths in :mod:`spectrapaint.render` (conventions.md §3) and the API thin.

    The Light Map is computed **once per photo per Base Colour group** (not per
    tap), so a Shade change is just multiply–composite–encode. ``surfaces``
    carries ``wall``/``ceiling`` per plane; when omitted every plane is treated
    as ``wall`` for backward compat with existing tests.
    """
    if not plane_targets:
        encoded = encode_srgb(np.ascontiguousarray(linear_photo))
        return (encoded * 255.0 + 0.5).astype(np.uint8)

    alphas = [alpha for alpha, _ in plane_targets]
    if surfaces is None:
        surfaces = ["wall"] * len(alphas)
    grouped_bases = _grouped_base_colours(linear_photo, alphas, surfaces)

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

    if alphas:
        union = np.clip(
            np.sum(
                np.stack([np.asarray(a, dtype=np.float32)[..., 0] for a in alphas], axis=0),
                axis=0,
            ),
            0.0,
            1.0,
        )
        result_linear = _highlight_rolloff(result_linear, union)
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

# --- Stain suppression and sun handling (issue #52). All of these exist to
# --- be tuned against real photographs; none is a derived constant. The bug
# --- docs they were tuned against live in docs/bugs/ (02-stains, 07-sunlit).
# --- The repaint promises "your wall, freshly painted": stains are
# --- reflectance, not light, so they are suppressed by default (decision 1).

# Share of mid-frequency luminance blotch removed. 0 keeps today's behaviour;
# 1 removes it entirely. Trades stain darkness against soft contact shadows,
# which live in the same band and weaken somewhat. Tuned against the synthetic
# cream-wall brown-patch probe (ΔE00 20.6 → 2.6): 0.8 left ΔE00 13.2, so full
# removal with edge protection was needed. Soft shadows weaken; contact
# shadows at matte edges survive via _STAIN_EDGE_PROTECT_RADIUS_FRACTION.
_STAIN_SUPPRESSION = 1.0
# Share of local chroma deviation removed toward the room's large-scale
# chroma. 1 removes a stain's hue entirely, keeping only bounce light and
# window cast. Trades stain hue against large coloured bounce (e.g. red sofa).
_STAIN_CHROMA_SUPPRESSION = 1.0
# Of the shorter side: structure larger than this is "lighting" (gradients,
# corner falloff) and kept; smaller is a candidate blotch. Starting value 0.08
# left a 40×40 stain at ΔE00 13.2; tuned to 0.20 for ΔE00 2.6 on the same probe.
# Larger flattens illumination more, but photo-border protection keeps the frame
# ends exact and interior gradients stay within 2%.
_STAIN_ILLUMINATION_RADIUS_FRACTION = 0.20
# Of the shorter side: structure smaller than this is "texture" (roller grain)
# and kept. Smaller keeps finer grain but lets fine stains survive.
_STAIN_TEXTURE_RADIUS_FRACTION = 0.004
# Of the shorter side: contact shadows sit at occluders, which are matte
# boundaries, so suppression ramps from 0 at the edge to full this far inside.
# Wider keeps more shadow but lets edge-near stains survive.
_STAIN_EDGE_PROTECT_RADIUS_FRACTION = 0.03

# Tint-space Euclidean distance a pixel's tint (rgb/luma) may lie from the
# wall's median tint and still vote for the Base Colour. Tighter rejects more
# sun; looser keeps more wall on varied paint. Same space as
# _GROUP_TINT_THRESHOLD (0.08), just tighter. Tuned against the synthetic
# yellow-wall 20%-strip probe (ΔE00 8.6 → <3).
_BASE_TINT_TOLERANCE = 0.06
# Fewer agreeing pixels than this falls back to today's whole-interior band,
# so a tiny or wildly varied wall never dead-ends with an empty vote.
_BASE_MIN_AGREEING = 500

# Shading (luma(photo)/luma(base)) below START is normal light: the sun's full
# tint is kept. Above FULL it is sun: only _SUN_TINT_KEEP of the tint is kept,
# the rest is brightness only. Between, a smoothstep. Trades "brighter and a
# little warm" (decision 2) against neutral-but-flat sun.
_HIGHLIGHT_START = 1.15
_HIGHLIGHT_FULL = 1.5
# Share of the sun's chroma deviation kept in highlights. 0 is neutral
# brightness only; 1 is today's yellow blob. Tuned against the pale-blue 5%
# warm-patch probe (b* +14.7 → ≤0).
_SUN_TINT_KEEP = 0.30

# Linear-light peak (max channel) where the soft highlight knee starts. Above
# it all three channels scale by one factor toward 1.0, so hue is kept and no
# channel hard-clips to 255. Lower protects more highlights but dulls bright
# Shades; higher lets more clipped hue-shift through.
_HIGHLIGHT_KNEE = 0.90

# sRGB byte level at or above which a photo channel carries no information
# (blown sun, specular). There the Light Map's chroma is replaced by the local
# room chroma while shading is kept: the patch stays bright in the Shade's hue.
_CLIPPED_LEVEL = 250


def estimate_base_colour(linear_photo: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """The wall's surface colour, measured from the Wall Plane matte.

    The spec pins this derivation, and every step of it is load-bearing
    (docs/specs/v1-spectrapaint.md, "The render engine"):

    * **Fully-opaque matte pixels only, eroded inward.** A boundary pixel is a
      blend of wall and whatever is behind the wall's edge, so its colour is
      partly the ceiling's. Averaging those in tints the Base Colour toward
      everything the wall is next to.
    * **Hue-agreeing pixels only (issue #52 C).** Each interior pixel's tint
      (rgb/luma) is compared to the per-channel median tint; only pixels within
      ``_BASE_TINT_TOLERANCE`` vote, falling back to all interior pixels below
      ``_BASE_MIN_AGREEING``. Sun-coloured pixels cannot enter the percentile
      band while sun covers less than half the wall. The median is only a
      filter: the Base Colour is still the mean RGB of whole pixels.
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

    pixels = linear_photo[interior].astype(np.float64)
    luma = pixels @ _LUMA_WEIGHTS.astype(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        tints = pixels / np.maximum(luma[:, None], 1e-6)
    finite = np.isfinite(tints).all(axis=1) & (luma > 1e-6)
    if finite.sum() >= _BASE_MIN_AGREEING:
        typical = np.median(tints[finite], axis=0)
        dist = np.linalg.norm(tints - typical, axis=1)
        agrees = finite & (dist < _BASE_TINT_TOLERANCE)
        candidates = pixels[agrees] if agrees.sum() >= _BASE_MIN_AGREEING else pixels
    else:
        candidates = pixels
    luminance = candidates @ _LUMA_WEIGHTS.astype(np.float64)

    low, high = np.percentile(
        luminance, [_BASE_PERCENTILE - _BASE_PERCENTILE_BAND, _BASE_PERCENTILE]
    )
    in_band = (luminance >= low) & (luminance <= high)
    # A band can come back empty when the wall is a single flat value and every
    # percentile lands on the same number; the equality check below is what
    # keeps that case from producing a NaN mean.
    selected = candidates[in_band] if in_band.any() else candidates

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


def _grouped_base_colours(
    linear_photo: np.ndarray, alphas: list[np.ndarray], surfaces: list[str] | None = None
) -> list[np.ndarray]:
    """One Base Colour per plane, grouped by existing paint — never across surfaces.

    Steps per the spec's grouping rule:

    1. Estimate a per-plane Base Colour with :func:`estimate_base_colour`
       (fully-opaque, eroded, 90th-percentile mean RGB).
    2. Cluster by tint distance (``_GROUP_TINT_THRESHOLD``). Same paint →
       same tint → same group, so relative brightness survives. **A ceiling
       is never grouped with a wall**, even when tint distance would otherwise
       put them together — the two surfaces carry different lighting and grouping
       them breaks the room's light modelling silently.
    3. For each group, re-estimate one Base Colour from the **union** of
       its planes' interior pixels. A group of one reuses its single
       estimate to avoid a second percentile pass; a group of several
       merges alphas (partition → sum ≤ 1) and estimates once.

    Returns a list aligned with ``alphas``: each entry is the shared
     Base Colour its plane belongs to.
    """
    if len(alphas) <= 1:
        return [estimate_base_colour(linear_photo, alphas[0])] if alphas else []

    if surfaces is None:
        surfaces = ["wall"] * len(alphas)

    individual = [estimate_base_colour(linear_photo, a) for a in alphas]
    tints = [_tint_of(b) for b in individual]

    groups: list[list[int]] = []
    assignment: list[int] = [-1] * len(alphas)
    for idx, tint in enumerate(tints):
        found = -1
        for g_idx, members in enumerate(groups):
            rep = members[0]
            if surfaces[idx] != surfaces[rep]:
                continue
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
