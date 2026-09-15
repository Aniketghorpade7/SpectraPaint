"""Building the soft Alpha Matte: SAM 2's boundary, corrected and then sharpened.

Three things happen here, in this order, and the order is the point.

1. **SAM 2's mask becomes a soft matte.** Its logits are upsampled to the photo and passed through a
   sigmoid, so boundary pixels come out partially covered. Never thresholded to a binary mask: real
   photographic edges carry lens blur and antialiasing, and a razor edge is the clearest visual sign
   an image has been altered (CONTEXT.md, "Alpha Matte").

2. **The semantic pass gets the last word on what is wall.** SAM 2 is appearance-driven, so a strong
   shadow boundary looks to it exactly like an object boundary, and it will happily cut the dark
   strip near the ceiling out of the mask. That strip *is* the wall, and losing it leaves a ghost of
   the old paint after recolouring — the failure mode design-decisions.md §5 names as the most
   damaging one. So wherever the semantic pass is confident the pixel is wall, it is restored; and
   wherever the semantic pass named an exclusion, it is removed, because a repainted window is
   instantly and obviously wrong.

3. **The boundary band is refined at full resolution.** Both networks saw a downscaled square; the
   matte they produce is therefore soft in the wrong places by a few pixels. A guided filter, with
   the photo's own luminance as the guide, pulls the matte's edge onto the photo's edge. This is the
   cheap edge-aware pass that decouples perceived quality from network resolution
   (design-decisions.md §5) — and it is why a floor-tier machine can produce a presentable edge.

Only the *band* is refined, not the interior. Inside the wall the matte is 1 and there is nothing to
sharpen; running a guided filter there would let the photo's texture modulate the alpha, painting
faint shadows of the furniture into the coverage itself.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from spectrapaint.imaging import dilate, erode, guided_filter
from spectrapaint.runtime.graphs import Graphs
from spectrapaint.segmentation.prompts import PromptSet
from spectrapaint.segmentation.semantic import SemanticRegions, pixel_values

# Above this the semantic pass is treated as certain enough to overrule SAM 2 and restore a pixel to
# the wall. Chosen high on purpose: this rule exists for shadowed wall, where the semantic model is
# confident and SAM 2 is wrong, not to paper over genuine disagreement.
SEMANTIC_OVERRULE_CONFIDENCE = 0.75

# Below this the semantic pass is not trusted to vouch for a pixel SAM 2 claims is wall, even where
# nothing named it an exclusion. Named exclusions (matte.py's second step) are semantic and absolute
# by design (design-decisions.md §5) — this is not a fifth exclusion class, it is a floor under
# SAM 2's own appearance-driven guess, for the case that motivated #31. It is a partial improvement
# and not a fix: a checkpoint that is confidently wrong about a door leaves no gap between "sure
# this is wall" and "sure this isn't" for a floor to sit in, so this helps two fixtures and does
# nothing for that one. See `_unvouched` for what it does and does not remove.
WALL_CONFIDENCE_FLOOR = 0.9

# The boundary band, as a fraction of the photo's shorter side. Wide enough to contain the error a
# quarter-resolution network makes once upsampled, narrow enough that the interior is left alone.
_BAND_FRACTION = 0.02

# Where the matte's own edge is taken to be, for the purpose of finding that band.
_EDGE_LEVEL = 0.5

# Guided filter regularisation. Larger keeps the matte smoother and less willing to follow an edge;
# smaller follows the photo more closely and starts following its noise too.
_GUIDE_EPSILON = 1e-4


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    """Logits to probabilities, without overflowing on large negative values."""
    return np.where(
        logits >= 0.0,
        1.0 / (1.0 + np.exp(-np.clip(logits, 0.0, None))),
        np.exp(np.clip(logits, None, 0.0)) / (1.0 + np.exp(np.clip(logits, None, 0.0))),
    )


def _resize(array: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Bilinear resize of one 2-D float array to (height, width)."""
    height, width = shape
    if array.shape == (height, width):
        return array.astype(np.float32)
    image = Image.fromarray(array.astype(np.float32), mode="F")
    return np.asarray(
        image.resize((width, height), resample=Image.Resampling.BILINEAR), dtype=np.float32
    )


@dataclass(frozen=True)
class RefinerFeatures:
    """SAM 2's encoder output for one photo: expensive to produce, cheap to decode against
    repeatedly.

    Kept as its own type, rather than the encoder's raw list, so a caller that holds one across a
    request boundary — preparation, then any correction that follows (ticket #10) — is holding
    something with a name, not three anonymous arrays.
    """

    feature_0: np.ndarray
    feature_1: np.ndarray
    feature_2: np.ndarray


def encode_photo(graphs: Graphs, photo_u8: np.ndarray) -> RefinerFeatures:
    """Run SAM 2's encoder once. The expensive half — ~2.0s measured
    (implementation-decisions.md #23) — and independent of any prompt, so it is paid once per
    photo and never again for that photo, however many prompt sets follow.
    """

    encoder_config = graphs.refiner_encoder.config
    features = graphs.refiner_encoder.run({"pixel_values": pixel_values(photo_u8, encoder_config)})
    return RefinerFeatures(feature_0=features[0], feature_1=features[1], feature_2=features[2])


def decode_alpha(
    graphs: Graphs,
    features: RefinerFeatures,
    prompts: PromptSet,
    photo_shape: tuple[int, int],
) -> np.ndarray:
    """SAM 2's answer for this prompt set, as a soft map at photo resolution, decoded against
    already-encoded features.

    Cheap — ~120ms measured (implementation-decisions.md #23) — which is what makes a correction
    tap (ticket #10) affordable without re-preparing the photo: preparation encodes once via
    :func:`encode_photo`, and every add/split correction calls only this.
    """

    mask_logits, _iou = graphs.refiner_decoder.run(
        {
            "feature_0": features.feature_0,
            "feature_1": features.feature_1,
            "feature_2": features.feature_2,
            "point_coords": prompts.coords,
            "point_labels": prompts.labels,
        }
    )

    # (batch, object, mask, height, width) -> the one mask that was asked for.
    logits = np.asarray(mask_logits, dtype=np.float32).reshape(-1, *mask_logits.shape[-2:])[0]
    return np.clip(_sigmoid(_resize(logits, photo_shape)), 0.0, 1.0).astype(np.float32)


def refiner_alpha(graphs: Graphs, photo_u8: np.ndarray, prompts: PromptSet) -> np.ndarray:
    """SAM 2's answer for this prompt set, encoding and decoding in one call.

    Kept for a caller with no reason to hold the features past one prompt set. The pipeline
    (segmentation/walls.py) calls :func:`encode_photo` and :func:`decode_alpha` separately instead,
    precisely so the features survive past this one call.
    """

    features = encode_photo(graphs, photo_u8)
    return decode_alpha(graphs, features, prompts, photo_u8.shape[:2])


def luminance_of(photo_u8: np.ndarray) -> np.ndarray:
    """The photo's brightness in [0, 1], as the guide for the edge-aware pass.

    BT.709 weights, the primaries the project's sRGB transfer function is defined against
    (spec, "Colour management"). Gamma-encoded values are used deliberately: the guide's job is to
    mark where a human sees an edge, and gamma-encoded brightness is closer to that than linear
    light is.
    """

    weights = np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)
    return (photo_u8.astype(np.float32) @ weights) / 255.0


def _unvouched(regions: SemanticRegions, confident_wall: np.ndarray) -> np.ndarray:
    """Where the semantic pass will not vouch for a pixel SAM 2 claims is wall (#31).

    Two things exempt a pixel, and both were settled by measuring on the three room fixtures rather
    than argued:

    * the restore step already forced it to 1.0. The floor is a check on what SAM 2 *alone*
      believes, not a second vote against a restoration that already happened.
    * SegFormer's own argmax called it ``wall``, however unsure it was. A wall in shadow is
      labelled wall and doubted, so a floor without this clause deletes it: measured at 77%
      shadowed-wall recall on ``windows-with-curtains`` against a floor of 80%, where exempting it
      scores 80.1%. Doubted-but-labelled wall is the case the semantic pass exists to win (module
      docstring, step 2), so doubt alone must not remove it.

    Two variants were measured and rejected. Reading the confidence through a box mean first, to
    ride across the quarter-resolution blockiness, changes no metric on any fixture to three
    decimal places — the band-and-core step below already resolves the matte spatially, so a
    stipple of holes never reaches the output. Holding argmax-wall pixels to a lower floor instead
    of exempting them outright costs the shadow immediately: at 0.35 the same recall is back to
    77%, because that shadowed wall is labelled wall at only 0.2 to 0.35 confidence.
    """

    return (regions.wall_confidence < WALL_CONFIDENCE_FLOOR) & ~confident_wall & ~regions.wall


def soften_boundary(photo_u8: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Sharpen a matte's own edge with a luminance-guided filter, confined to a band around
    where the matte crosses its own 0.5 level. Returns a 2-D array, same shape as ``alpha``.

    Split out of :func:`wall_alpha` so a caller with no ``SemanticRegions`` to restore shadow or
    remove exclusions from — ticket #10's Add tool, where the Dealer's own tap is the only signal
    — still gets the same soft-edge treatment as every other Wall Plane. A razor edge is the
    clearest visual sign an image has been altered (CONTEXT.md, "Alpha Matte"), and that has to
    hold for a manually-added plane exactly as much as an automatically-found one.

    The matte is resolved into three zones, found *spatially* from where it crosses its own edge
    level rather than by asking which alpha values happen to look intermediate. Those are not the
    same thing: a network that returned a uniformly unsure mask would otherwise make the whole
    photo "boundary", hand the guided filter the interior, and let the photo's texture modulate
    coverage — painting faint shadows of the furniture into the alpha itself.
    """

    radius = max(1, round(min(alpha.shape) * _BAND_FRACTION))
    guide = luminance_of(photo_u8)
    sharpened = guided_filter(guide, alpha, radius, _GUIDE_EPSILON)

    inside = alpha >= _EDGE_LEVEL
    core = erode(inside, radius)
    reach = dilate(inside, radius)
    band = reach & ~core

    # Softness belongs at the edges and nowhere else: "soft matte edges are used only where a wall
    # meets a non-wall" (spec, "Corners"). So the interior is fully covered and the exterior is not
    # covered at all, both by definition, and only the band carries a fractional value. This is also
    # what keeps the matte usable when the refiner returns a mask it is unsure of everywhere — the
    # uncertainty is confined to the boundary, instead of quietly becoming a wall the render can
    # only half paint.
    return np.where(core, 1.0, np.where(band, sharpened, 0.0)).astype(np.float32)


def wall_alpha(
    photo_u8: np.ndarray,
    regions: SemanticRegions,
    refined: np.ndarray,
) -> np.ndarray:
    """The finished matte: HxWx1 float32 in [0, 1].

    The shape is the contract the render path was written against — ``PreparedPhoto.wall_alpha``
    has always been HxWx1 — so this replaces the stub rectangle without the engine noticing.
    """

    alpha = refined.astype(np.float32).copy()

    # Shadowed wall, restored — the ghost-of-the-old-paint rule from the module docstring. Restored
    # to *fully* covered, not to the model's confidence: alpha means "how much of this pixel is
    # wall", and a pixel the semantic pass is sure about is all wall. Confidence answers a different
    # question, and spending it as coverage would leave a wall the render can only ever paint
    # nine-tenths of.
    confident_wall = regions.wall & (regions.wall_confidence >= SEMANTIC_OVERRULE_CONFIDENCE)
    alpha = np.where(confident_wall & ~regions.excluded, 1.0, alpha)

    # Named exclusions, removed. Semantic, not photometric: a window leaves because it was called a
    # window, and no amount of looking wall-like brings it back.
    alpha = np.where(regions.excluded, 0.0, alpha)

    # A floor under SAM 2's own guess (#31): below WALL_CONFIDENCE_FLOOR the semantic pass will not
    # vouch for a pixel, so SAM 2's appearance-driven coverage there is not trusted either. Before
    # the boundary is softened, not after: the floor is a statement about which pixels are wall at
    # all, and softening is what resolves the edge of whatever survives it.
    alpha = np.where(_unvouched(regions, confident_wall), 0.0, alpha)

    alpha = soften_boundary(photo_u8, alpha)

    # The filter's window straddles the boundary, so it can pull a little coverage onto an excluded
    # pixel. Re-imposed afterwards, because "never paint a window" is not a preference to be
    # averaged with its neighbours.
    alpha = np.where(regions.excluded, 0.0, alpha)

    return np.clip(alpha, 0.0, 1.0).astype(np.float32)[..., None]


def ceiling_alpha(
    photo_u8: np.ndarray,
    regions: SemanticRegions,
    refined: np.ndarray,
) -> np.ndarray:
    """The finished ceiling matte: HxWx1 float32 in [0, 1].

    Same treatment as :func:`wall_alpha` — SAM 2's mask
    refined by the semantic pass and then softened — but
    without plane splitting (a ceiling in one photo is
    essentially always one region). The ceiling's own coverage
    carries its own base colour and light map, and is never
    grouped with a wall's, even when the two happen to be a
    similar pale colour.
    """

    alpha = refined.astype(np.float32).copy()

    confident_ceiling = regions.ceiling & (
        regions.ceiling_confidence >= SEMANTIC_OVERRULE_CONFIDENCE
    )
    # Ceiling excluded set is wall plus the other non-ceiling exclusions; build without re-using the
    # wall's `excluded` which already contains ceiling.
    other_excluded = regions.excluded & ~regions.ceiling
    ceiling_excluded = regions.wall | other_excluded
    alpha = np.where(confident_ceiling & ~ceiling_excluded, 1.0, alpha)
    alpha = np.where(ceiling_excluded, 0.0, alpha)

    alpha = soften_boundary(photo_u8, alpha)
    alpha = np.where(ceiling_excluded, 0.0, alpha)

    return np.clip(alpha, 0.0, 1.0).astype(np.float32)[..., None]
