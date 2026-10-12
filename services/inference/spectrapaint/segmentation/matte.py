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

**Every edge here is continuous, and that took work.** The three steps above are each a place a hard
edge can reappear, and before issue #51 each of them had one. Step 2 writes the semantic pass's
decisions in as hard 0/1, and step 3 quantises the matte into three zones with a nested `np.where`,
putting a full 1.0 step where the band met the core and a full 0.0 where it met the exterior.
Step 1's labels were themselves a staircase, being decided on SegFormer's 128×128 grid and upsampled
nearest-neighbour — which is what made 75–84% of razor edges land on grid lines
(docs/bugs/root-causes.md §A, and technical difficulty 29 for what it took to establish that the
refiner was not, in the end, the thing shaping the edge).

So the boundary is decided at photo resolution from upsampled probabilities
(:mod:`segmentation.semantic`), the exclusion fades out across its own edge rather than being
re-imposed over the softening (:func:`exclusion_ramp`), the zones are joined by ramps rather than
switched (:func:`_ramp`), and where two planes meet the winner takes the union rather than the
higher claim (`segmentation.corrections.resolve_exclusive`). The two constants that keep this
honest are :data:`EXCLUSION_FEATHER_FRACTION` and :data:`REFINER_TRUST_FLOOR`; both were measured,
and both were wrong before they were right.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image

from spectrapaint.imaging import blur, dilate, erode_round, guided_filter
from spectrapaint.runtime.graphs import Graphs
from spectrapaint.segmentation.prompts import PromptSet
from spectrapaint.segmentation.semantic import SemanticRegions, pixel_values

logger = logging.getLogger(__name__)

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
#
# Classes named in runtime.json's `floor_exempt_classes` (today only `mirror`) are exempt from it
# and held to FLOOR_EXEMPT_CONFIDENCE_FLOOR instead (#48). See that constant.
WALL_CONFIDENCE_FLOOR = 0.9

# Below this, SAM 2 is not trusted with the *shape* of the matte, and the shape is taken from the
# semantic pass's own probability for that surface instead (issue #51, step 5). A different floor
# from the one above, and deliberately: that one asks "is this pixel wall", which the semantic
# pass answers far better than an appearance-driven refiner. This one asks "did the refiner find
# anything at all", which is a question about the refiner, and only the refiner can answer it.
#
# The issue proposed 0.3. It was tried, and it is wrong, and how it is wrong is worth recording
# because the reason is not obvious. `iou_scores` are spread widely rather than uniformly low —
# 0.043 to 0.841 across the six fixtures — so 0.3 is not "mostly below the floor". It is a line
# drawn through the middle of the range, and it happens to fall on one fixture where the fallback
# is *worse*.
#
# Measured both ways on every labelled fixture, as shadowed-wall recall with the refiner trusted
# against the refiner switched off. The fallback is better on four of five:
#
#     empty-corner                     0.9913 -> 0.9915
#     dim-room-with-mirror             0.7358 -> 0.7513
#     patterned-wallpaper-with-curtain 1.0000 -> 1.0000
#     corner-with-clothesline          0.9713 -> 0.9740
#     windows-with-curtains            0.8008 -> 0.7725   <- worse
#
# So the score does not predict which of the two mattes is better, and no threshold on it will
# separate them: windows-with-curtains scores 0.227, above both fixtures where the fallback wins,
# and 0.3 excludes it. What the score *can* do is catch a degenerate decode, and 0.1 is where that
# line falls. Below it the refiner has returned essentially nothing, and on both fixtures that low
# the switch is an improvement. Above it the refiner is kept, including on the fixture where it is
# the better answer. That is a weaker claim than the issue's, and it is the one the photographs
# support.
REFINER_TRUST_FLOOR = 0.1

# The floor for a floor-exempt pixel: argmax `mirror` with `wall` as the runner-up
# (SemanticRegions.floor_exempt). This checkpoint labels sunlit, washed-out wall `mirror`, and the
# 0.9 floor deleted it: on the page-6 photo in docs/bugs/ (fixture `blue-wall-sunlit`) the matte
# kept 0.271 of the wall's darkest quarter, which is mostly that sunlit recessed wall.
#
# It also labels night window glass and lit curtains `mirror`, so every way of letting the first
# back in lets some of the second in too. Measured on the fixtures after #51, as page-6 darker-
# quarter recall against windows-with-curtains non-wall leakage (0.191 under the plain floor):
#
#     every mirror pixel, no floor          0.927   0.264
#     every mirror pixel, floor 0.15        0.829   0.207
#     mirror within one grid cell of wall   0.354   0.198
#     mirror only where it is bright        0.380   0.205   (sunlit wall is mid-grey: median 0.30)
#     runner-up wall, floor 0.10            0.906   0.210   <- this
#
# No rule found keeps leakage at 0.20 and brings the wall back. The runner-up rule loses the least
# for the most, and it is semantic: the model's own second guess, not how the pixel looks. The
# 0.010 over the 0.20 target was accepted on 2026-10-09 and is recorded in measured.toml; see
# docs/implementation-decisions.md, decision 54.
FLOOR_EXEMPT_CONFIDENCE_FLOOR = 0.10

# The boundary band, as a fraction of the photo's shorter side. Wide enough to contain the error a
# quarter-resolution network makes once upsampled, narrow enough that the interior is left alone.
# Public because `corrections.seam_radius` is defined in terms of it — a seam is a pair of matte
# boundaries, and two constants for one idea is how they drift apart.
BAND_FRACTION = 0.02

# How wide the exclusion ramp is, as a fraction of the photo's shorter side — conventions §4's
# "explain a constant in terms of what it costs if it is wrong". Chosen so the feather is a few
# pixels: wide enough that the matte's own edge cannot step across it, narrow enough that the wall
# either side of a window keeps its coverage. Four times smaller than BAND_FRACTION, because this
# one is a ramp being *seen* at the exclusion rather than a band being *refined*, and a ramp you can
# see from across the room is a defect of its own.
#
# The width this buys is about *three* times the radius, not the radius: `exclusion_ramp` ramps
# between blurred 0.5 (on the exclusion's edge) and blurred 0 (three sigma out), and Pillow's
# GaussianBlur takes its radius as the sigma. So 0.004 of a 960px side is a 4px sigma and a feather
# roughly 12px across — which is the number to reason about when this constant is next argued about,
# and the reason it is a quarter of BAND_FRACTION rather than equal to it.
EXCLUSION_FEATHER_FRACTION = 0.004

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
) -> tuple[np.ndarray, float]:
    """SAM 2's answer for this prompt set, as a soft map at photo resolution, and how sure it is.

    Returns ``(alpha, iou_score)``. The score is SAM 2's own estimate of the mask's IoU — the
    graph's second output, which was named ``_iou`` and dropped here until #51. It is a scalar per
    decode, not a map, and it is the only self-assessment the refiner makes, so it is worth carrying
    rather than discarding: see :data:`REFINER_TRUST_FLOOR`.

    Cheap — ~120ms measured (implementation-decisions.md #23) — which is what makes a correction
    tap (ticket #10) affordable without re-preparing the photo: preparation encodes once via
    :func:`encode_photo`, and every add/split correction calls only this.
    """

    mask_logits, iou_scores = graphs.refiner_decoder.run(
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
    alpha = np.clip(_sigmoid(_resize(logits, photo_shape)), 0.0, 1.0).astype(np.float32)

    # (batch, object, mask) -> the one score that goes with it.
    scores = np.asarray(iou_scores, dtype=np.float32).reshape(-1)
    score = float(scores[0]) if scores.size else 0.0
    return alpha, score


def refiner_alpha(
    graphs: Graphs, photo_u8: np.ndarray, prompts: PromptSet
) -> tuple[np.ndarray, float]:
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


def exclusion_ramp(excluded: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """How much of the matte may survive just outside ``excluded``, in [0, 1].

    A named function rather than a line in both :func:`wall_alpha` and :func:`ceiling_alpha`,
    because "never paint a window" has to mean the same thing to a wall and to a ceiling and the
    two used to mean it twice, written down twice.

    ``1 - 2 * blur(excluded)`` reads as "how far outside the exclusion am I": 0 where the exclusion
    covers everything, 1 where it covers none, and 0.5 exactly on its edge — so the ramp is
    *already zero at the boundary and inside*, and the exclusion stays absolutely unpaintable while
    the wall beside it keeps a soft few-pixel falloff. The old code re-imposed the exclusion with a
    hard ``np.where`` after softening, which is what turned a soft edge back into a razor one
    (docs/bugs/root-causes.md §A): the guided filter had just spent its effort placing an edge, and
    the mask threw it away. A repainted window is still never painted; what changes is that the
    pixels just *outside* it now fade instead of stopping dead.
    """

    radius = max(1, round(min(shape) * EXCLUSION_FEATHER_FRACTION))
    blurred = blur(excluded.astype(np.float32), radius)
    ramp = np.clip(1.0 - 2.0 * blurred, 0.0, 1.0)
    # Zero on the excluded side by construction, not by arithmetic. `blur` makes a round trip
    # through 8-bit (imaging.py), so the profile on the exclusion's own edge comes back as 126/255
    # rather than 0.5 and the ramp as 3/255 rather than 0 — tiny, and harmless only because every
    # caller pairs this with a `np.where(excluded, 0.0, ...)`. "Never paint a window" is absolute,
    # and a constant that guarantees it is worth more than one that happens to hold at eight bits.
    return np.where(excluded, 0.0, ramp).astype(np.float32)


def _refiner_shape(
    refined: np.ndarray, semantic_probability: np.ndarray, iou_score: float
) -> np.ndarray:
    """Whose opinion sets the matte's shape, decided by SAM 2's own confidence in its answer.

    Above :data:`REFINER_TRUST_FLOOR`, the refiner's soft map is used unchanged — it has the finer
    detail, and it is only being distrusted about whether it found anything at all.

    Below it, the shape comes from the semantic pass's upsampled probability for *this* surface
    (:mod:`segmentation.semantic`, step 1 of issue #51) rather than from SAM 2's logits. That
    probability is the only *semantic* answer available at photo resolution, so a matte built
    from it at least has its boundary where the model thinks the surface is, instead of wherever a
    constant mask's edge happened to fall. It is a poor substitute for a real refiner — soft, and
    no finer than SegFormer's own resolution — and it beats the alternative only because that
    alternative is a shape the refiner says it does not believe.

    ``semantic_probability`` is passed in rather than read off ``regions`` because a ceiling falling
    back on the wall's probability would be a different bug wearing the same coat.

    Logged at ``debug`` and not silently: a photo where the refiner is switched off should be
    visible in the log next to one where it was not (conventions.md §5, no silent recovery). The
    level is ``debug`` because this is per-photo and the healthy case is the common one.
    """

    if iou_score >= REFINER_TRUST_FLOOR:
        return refined

    logger.debug(
        "refiner iou_score %.3f is below the trust floor %.3f; taking the matte's shape from "
        "the semantic probability instead",
        iou_score,
        REFINER_TRUST_FLOOR,
    )
    return np.clip(semantic_probability, 0.0, 1.0).astype(np.float32)


def _unvouched(regions: SemanticRegions, confident_wall: np.ndarray) -> np.ndarray:
    """Where the semantic pass will not vouch for a pixel SAM 2 claims is wall (#31).

    Two things exempt a pixel and a third lowers its floor, and all three were settled by measuring
    on the room fixtures rather than argued:

    * the restore step already forced it to 1.0. The floor is a check on what SAM 2 *alone*
      believes, not a second vote against a restoration that already happened.
    * SegFormer's own argmax called it ``wall``, however unsure it was. A wall in shadow is
      labelled wall and doubted, so a floor without this clause deletes it: measured at 77%
      shadowed-wall recall on ``windows-with-curtains`` against a floor of 80%, where exempting it
      scores 80.1%. Doubted-but-labelled wall is the case the semantic pass exists to win (module
      docstring, step 2), so doubt alone must not remove it.
    * SegFormer's argmax called it a floor-exempt class (today only ``mirror``) with ``wall`` as
      its runner-up (``SemanticRegions.floor_exempt``). Such a pixel is held to
      ``FLOOR_EXEMPT_CONFIDENCE_FLOOR`` instead of ``WALL_CONFIDENCE_FLOOR``. Sunlit wall is washed
      out and low in texture, and this checkpoint calls it ``mirror``, so the 0.9 floor was
      deleting exactly the wall the sun falls on (#48). The runner-up clause and the lower floor
      keep most night window glass and curtains out, which the checkpoint calls ``mirror`` too;
      what they let back in is measured at ``FLOOR_EXEMPT_CONFIDENCE_FLOOR``. A real mirror the
      checkpoint is unsure of is paintable again, as it was before #31; that cost was accepted
      (docs/bugs/README.md, decision 3).

    Two variants were measured and rejected. Reading the confidence through a box mean first, to
    ride across the quarter-resolution blockiness, changes no metric on any fixture to three
    decimal places — the band-and-core step below already resolves the matte spatially, so a
    stipple of holes never reaches the output. Holding argmax-wall pixels to a lower floor instead
    of exempting them outright costs the shadow immediately: at 0.35 the same recall is back to
    77%, because that shadowed wall is labelled wall at only 0.2 to 0.35 confidence.
    """

    floor = np.where(regions.floor_exempt, FLOOR_EXEMPT_CONFIDENCE_FLOOR, WALL_CONFIDENCE_FLOOR)
    return (regions.wall_confidence < floor) & ~confident_wall & ~regions.wall


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

    The three zones are joined by a distance-weighted blend rather than switched between, which is
    the whole difference between a soft edge and a soft edge with a step in it.
    ``np.where(core, 1.0, np.where(band, sharpened, 0.0))`` put a full jump at *both* boundaries of
    the band: the guided filter's fractional value at the inner edge was replaced by a hard 1.0 and
    at the outer edge by a hard 0.0, so a matte the filter had just placed on a door frame came out
    with a step there — the same artefact one zone further out and just as visible. Each transition
    is now a ramp over its own zone's blurred field, so alpha is continuous by construction, with
    no threshold left in the *output* to be wrong. The zones themselves are still thresholds, and
    have to be: they are what keeps the "uniformly unsure mask" invariant below honest.

    The zones are also found with the *round* morphology now. The square versions cut a region's
    corners off as fast as they cut the middle of a flat edge, so the band came out a constant width
    along an axis-aligned boundary and a much narrower one around a corner — and a room's wall
    planes meet at corners.
    """

    radius = max(1, round(min(alpha.shape) * BAND_FRACTION))
    guide = luminance_of(photo_u8)
    sharpened = guided_filter(guide, alpha, radius, _GUIDE_EPSILON)

    # Softness belongs at the edges and nowhere else: "soft matte edges are used only where a wall
    # meets a non-wall" (spec, "Corners"). So the interior is fully covered and the exterior is not
    # covered at all, both by definition, and only the band carries a fractional value. This is also
    # what keeps the matte usable when the refiner returns a mask it is unsure of everywhere — the
    # uncertainty is confined to the boundary, instead of quietly becoming a wall the render can
    # only half paint.
    inside = alpha >= _EDGE_LEVEL

    # The two zones are found with different morphology, on purpose, and it is worth being explicit
    # about why because the obvious move is to make them match.
    #
    # ``core`` is round. Square erosion cuts a region's corners off as fast as it cuts the middle of
    # a flat edge, so the core came out square and the band square with it — which is the reported
    # artefact, and it is worst at exactly the place a room's Wall Planes meet.
    core = erode_round(inside, radius)

    # ``reach`` is square, and deliberately so. It bounds the guided filter's support, and
    # ``guided_filter`` windows with a square ``box_mean``, so a square bound is the honest shape.
    # It also stays sensitive to small features, which a disc kernel is not: blurring with sigma 26
    # gives an isolated mask pixel 10px away a weight of about 1e-4, which rounds to zero in 8-bit
    # and vanishes, where square dilation still reaches it. That is not academic — it is what
    # ``patterned-wallpaper-with-curtain``'s Add tool depends on, and switching this one call cost
    # the correction entirely (measured below).
    #
    # The radius is *two* bands rather than one, so the fade that replaces the hard outer cut
    # sits entirely outside the filter's support instead of eating into it. At one radius the fade
    # sat on top of the outermost band and cut the Add tool's grown matte from 0.339 to 0.040 at the
    # tapped pixel — the tap lost its exclusivity contest against the plane already there and the
    # correction did nothing at all.
    reach = dilate(inside, 2 * radius)

    toward_inside = _ramp(core, radius)
    toward_outside = _ramp(~reach, radius)
    in_band = np.clip(1.0 - toward_inside - toward_outside, 0.0, 1.0)
    return np.clip(toward_inside + in_band * sharpened, 0.0, 1.0).astype(np.float32)


def _ramp(mask: np.ndarray, radius: int) -> np.ndarray:
    """A zone's weight, running 0 on its boundary to 1 well inside it.

    ``clip(2 * blur(mask) - 1, 0, 1)``, and the ``- 1`` is the whole point: a blurred mask is
    already 0.5 exactly on its own edge, so subtracting the half and doubling puts 0 on the edge
    and 1 about one sigma inside. Ramping on the *zone's own* field is what a first attempt got
    wrong — ramping on the blurred ``alpha >= 0.5`` region instead. For a region narrower than the
    band the profile never reaches 0.5 anywhere, so "0.5 means interior" is never true and the whole
    region reads as band-at-half-strength. That is not a hypothetical shape: it is every plane the
    Add tool grows from a single tap, and it halved the matte at the tapped pixel itself, which is
    the one pixel the test can see.

    The all-``False`` case is the invariant the three-zone construction was written for, and it
    holds by arithmetic rather than by a special case: nothing in the zone, nothing to ramp towards,
    and the caller's weights stay where they were put.
    """

    if not mask.any():
        return np.zeros(mask.shape, dtype=np.float32)
    return np.clip(2.0 * blur(mask.astype(np.float32), radius) - 1.0, 0.0, 1.0).astype(np.float32)


def wall_alpha(
    photo_u8: np.ndarray,
    regions: SemanticRegions,
    refined: np.ndarray,
    iou_score: float = 1.0,
) -> np.ndarray:
    """The finished matte: HxWx1 float32 in [0, 1].

    The shape is the contract the render path was written against — ``PreparedPhoto.wall_alpha``
    has always been HxWx1 — so this replaces the stub rectangle without the engine noticing.

    ``iou_score`` is SAM 2's own confidence (:func:`decode_alpha`). Below
    :data:`REFINER_TRUST_FLOOR` the refiner is not trusted with the matte's *shape*, and the shape
    comes from the semantic pass's wall probability instead. Everything below this point — the
    semantic overrule, the exclusions, the confidence floor — is unchanged either way, so what
    changes under a low score is where the edge sits and nothing about which pixels are wall.
    """

    alpha = _refiner_shape(refined, regions.wall_confidence, iou_score).astype(np.float32).copy()

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
    # pixel. Faded out across the exclusion's own edge rather than re-imposed on top of it: a hard
    # mask here undoes the softening one line above it, and a hard edge on a window frame is the
    # clearest possible sign the image has been altered.
    alpha = np.where(regions.excluded, 0.0, alpha * exclusion_ramp(regions.excluded, alpha.shape))

    return np.clip(alpha, 0.0, 1.0).astype(np.float32)[..., None]


def ceiling_alpha(
    photo_u8: np.ndarray,
    regions: SemanticRegions,
    refined: np.ndarray,
    iou_score: float = 1.0,
) -> np.ndarray:
    """The finished ceiling matte: HxWx1 float32 in [0, 1].

    Same treatment as :func:`wall_alpha` — SAM 2's mask
    refined by the semantic pass and then softened — but with
    without plane splitting (a ceiling in one photo is
    essentially always one region). The ceiling's own coverage
    carries its own base colour and light map, and is never
    grouped with a wall's, even when the two happen to be a
    similar pale colour.

    ``iou_score`` and :data:`REFINER_TRUST_FLOOR` apply here exactly as they do to a wall. Kept in
    step with :func:`wall_alpha` rather than only applied to it: a ceiling the refiner does not
    believe in is the same failure a wall would be, and a refiner that switches off for one surface
    but not the other is a thing nobody would discover from reading this.
    """

    alpha = _refiner_shape(refined, regions.ceiling_confidence, iou_score).astype(np.float32).copy()

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
    alpha = np.where(ceiling_excluded, 0.0, alpha * exclusion_ramp(ceiling_excluded, alpha.shape))

    return np.clip(alpha, 0.0, 1.0).astype(np.float32)[..., None]
