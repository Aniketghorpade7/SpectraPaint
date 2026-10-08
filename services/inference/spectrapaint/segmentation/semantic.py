"""The semantic pass: what kind of thing is each pixel?

SegFormer answers that for 150 ADE20K classes; five of them matter here — ``wall``, ``floor``,
``ceiling``, ``windowpane``, ``door`` (design-decisions.md §5). This module turns a photo into two
boolean maps: where the wall is, and where things that are definitely *not* wall are. The second is
not the complement of the first: most of a photo is neither wall nor one of the four named
exclusions, and a pixel of sofa is a pixel we know nothing useful about rather than one we know is
floor.

Two decisions worth naming.

**The photo is squashed to a square, not cropped.** The checkpoint's own preprocessor resizes to
512x512 without preserving aspect ratio, so that is what it saw in training and what it should see
now. Cropping to a square would be kinder to the aspect ratio and would throw away the sides of the
room, which is where the corner between two Wall Planes usually is.

**Exclusion is semantic, never photometric** (design-decisions.md §5). A pixel leaves the wall
because the model called it a window, never because it looks different from its neighbours. Shadows,
sheen and texture look different and are still wall — which is the whole reason the Light Map works.

**Probability first, decision at photo resolution.** The checkpoint sees a 512×512 squash of the
photo and returns logits at stride 4 — a 128×128 grid. Argmaxing that grid and upsampling the
resulting labels with nearest neighbour turns every boundary into a staircase of 10-px steps on a
1280×960 photo, and 75–84% of razor edges on the photographs in the bug report sit exactly on grid
lines (docs/bugs/root-causes.md §A). So the boundary between the classes that matter is decided at
the photo's own resolution, from bilinearly-upsampled probability planes — an average of two
probabilities is still a probability, whereas an average of two class indices is a class that does
not exist. See :func:`argmax_at_photo_resolution` for the two stages, and for why stage one has to
stay on the grid.

The old docstring's claim that a blocky staircase is "SAM 2's job and the refinement pass's job"
does not hold on real photos: SAM 2's single-mask logits on the checked photos are within ±2 on
77–100% of pixels and its ``iou_scores`` are 0.00–0.04 on the bug report's photographs (0.043–0.841
across the six fixtures, see ``matte.REFINER_TRUST_FLOOR``), so the semantic grid — not the
refiner — is what actually shapes the matte's edge. Fixing the shape at its source is this module's
job, not a downstream pass's.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from spectrapaint.runtime.graphs import Graph

# The five classes this pipeline makes a decision about, in the order the decision stack uses. Wall
# first, because index 0 is the label that means "wall"; the other four are the exclusions.
RELEVANT_CLASSES = ("wall", "floor", "ceiling", "windowpane", "door")

# The classes that are never wall. `wall` itself is handled separately, and everything unnamed —
# furniture, curtains, people — is left unclaimed rather than guessed at.
EXCLUDED_CLASSES = ("floor", "ceiling", "windowpane", "door")

# Slices into RELEVANT_CLASSES. Named rather than written out so adding a class to RELEVANT_CLASSES
# cannot silently leave a slice pointing at the wrong class.
_WALL_SLICE = 0
_CEILING_SLICE = RELEVANT_CLASSES.index("ceiling")
_EXCLUDED_SLICES = tuple(RELEVANT_CLASSES.index(name) for name in EXCLUDED_CLASSES)

# The label for a pixel where no relevant class won its grid cell — a sofa, a curtain, a person.
# Distinct from "excluded": an unclaimed pixel is not evidence against the wall, it is the absence
# of evidence for it, and the two are treated differently everywhere downstream.
UNCLAIMED = len(RELEVANT_CLASSES)


@dataclass(frozen=True)
class SemanticRegions:
    """Where the semantic pass thinks the wall and ceiling are, at the photo's own resolution.

    ``wall`` and ``excluded`` are boolean maps of the same height and width as the photo that was
    passed in. ``excluded`` is not the complement of ``wall``: the third state, *unclaimed*, is
    pixels no relevant class won at all (sofa, curtain, a person), and both maps are false there.
    ``wall_confidence`` is the model's softmax probability for the wall class, kept
    because the refinement stage needs a soft answer to the question "how sure are we?" and a
    boolean map has thrown that away. ``ceiling`` and ``ceiling_confidence`` are the same for the
    ceiling class — kept separately so the ceiling plane can be built from its own region without
    re-deriving it from ``excluded`` (which for wall purposes still contains ceiling as an
    exclusion, and must keep doing so).
    """

    wall: np.ndarray  # HxW bool
    excluded: np.ndarray  # HxW bool
    wall_confidence: np.ndarray  # HxW float32 in [0, 1]
    ceiling: np.ndarray  # HxW bool
    ceiling_confidence: np.ndarray  # HxW float32 in [0, 1]
    floor_exempt: np.ndarray  # HxW bool — mirror (and any future floor-exempt class from #48);
    # all-False until #48 lands, so _unvouched keeps its current behaviour unchanged.

    @property
    def wall_fraction(self) -> float:
        """How much of the photo is wall. Used to decide there is no wall worth painting."""
        return float(self.wall.mean())

    @property
    def ceiling_fraction(self) -> float:
        """How much of the photo is ceiling. Used to decide whether a ceiling is worth offering."""
        return float(self.ceiling.mean())


def pixel_values(photo_u8: np.ndarray, config: dict) -> np.ndarray:
    """A photo as the tensor the graph expects: NCHW float32, resized and normalised.

    The constants come from the checkpoint's own preprocessor config by way of
    ``tools/export_onnx.py``, so this function has no opinion about what they should be.
    """

    height, width = config["input_height"], config["input_width"]
    resized = Image.fromarray(photo_u8, mode="RGB").resize(
        (width, height), resample=Image.Resampling.BILINEAR
    )
    pixels = np.asarray(resized, dtype=np.float32) * config["rescale_factor"]
    mean = np.asarray(config["image_mean"], dtype=np.float32)
    std = np.asarray(config["image_std"], dtype=np.float32)
    normalised = (pixels - mean) / std
    return np.ascontiguousarray(normalised.transpose(2, 0, 1)[None], dtype=np.float32)


def _softmax(logits: np.ndarray, axis: int) -> np.ndarray:
    """Stable softmax. Subtracting the max first keeps ``exp`` away from overflow."""
    shifted = logits - np.max(logits, axis=axis, keepdims=True)
    exponentiated = np.exp(shifted)
    return exponentiated / np.sum(exponentiated, axis=axis, keepdims=True)


def _resize_to(array: np.ndarray, shape: tuple[int, int], *, nearest: bool) -> np.ndarray:
    """Resize one 2-D array to ``shape``, through Pillow.

    Labels are resized with nearest-neighbour — interpolating a class index would invent classes
    that are the average of wall and floor, which is not a thing. Probabilities are resized
    bilinearly, because an average of two probabilities is a probability.
    """

    height, width = shape
    if array.shape == (height, width):
        return array

    resample = Image.Resampling.NEAREST if nearest else Image.Resampling.BILINEAR
    image = Image.fromarray(array.astype(np.float32), mode="F")
    return np.asarray(image.resize((width, height), resample=resample), dtype=np.float32)


def argmax_at_photo_resolution(
    probabilities: np.ndarray,
    relevant_indices: tuple[int, ...],
    shape: tuple[int, int],
) -> np.ndarray:
    """Label every photo-resolution pixel with the most likely of ``relevant_indices``, or
    :data:`UNCLAIMED`.

    ``probabilities`` is the softmax at the network's own resolution — ``(classes, h, w)``, which is
    a 128×128 grid for the 512×512 input the checkpoint expects. Returns ``(height, width)`` int16
    holding an index into ``relevant_indices``, so a caller reads ``labels == 0`` for wall rather
    than ``labels == classes["wall"]`` and a change to the graph's class list cannot move it.

    **The claim is decided on the grid; the winner between claimed classes is not.**

    * **Which classes are in the running at all** — the full argmax over every class the network
      knows, on its own 128×128 grid. A cell won by a class outside ``relevant_indices`` is
      :data:`UNCLAIMED`. This is left exactly where it was, and see below for why moving it costs
      more than it buys.
    * **Which of them wins *this* pixel** — ``argmax`` over the upsampled planes of
      ``relevant_indices``, at photo resolution.

    So the boundary *between* the classes this pipeline decides about follows a smooth probability
    contour, because an average of two probabilities is still a probability whereas an average of
    two class indices is a class that does not exist (docs/bugs/root-causes.md §A, 75–84% of razor
    edges sitting exactly on 128-grid lines).

    The boundary between *claimed* and *unclaimed* stays on the grid, deliberately. Smoothing it
    too — by comparing against the best of the other classes at photo resolution — was measured, and
    costs more than it buys: 0.002 of `windows-with-curtains`' shadowed-wall recall, and the Add
    tool's ability to grow a plane at a missed wall pixel on `patterned-wallpaper-with-curtain`. It
    buys smoothness on a boundary where the matte is soft anyway, because an unclaimed pixel is
    neither restored to 1.0 nor zeroed by exclusion nor deleted by the confidence floor: it keeps
    SAM 2's own soft value, so a staircase there is a staircase in a region nothing quantises.
    Meanwhile the fine winner flips a few wall→exclusion pixels that the grid decision had called
    wall, and exclusion is absolute ("never paint a window"), so those pixels become unpaintable by
    a correction tap. Don't buy a cosmetic improvement with a functional one.

    The old docstring's claim that a blocky staircase is "SAM 2's job and the refinement pass's job"
    does not hold on real photos: SAM 2's single-mask logits on the checked photos are within ±2 on
    77–100% of pixels and its ``iou_scores`` are 0.00–0.04 on the bug report's photographs
    (0.043–0.841 across the six fixtures, see ``matte.REFINER_TRUST_FLOOR``), so the semantic grid —
    not the refiner — is what actually shapes the matte's edge.
    """

    # One resize per relevant class; the winner comes off the same stack. Worth reusing rather than
    # resizing twice: at 1280x960 these are five float planes, about 25 MB and 30 ms, and a second
    # pass would be 25 MB more for no new information.
    planes = np.stack(
        [
            _resize_to(probabilities[index].astype(np.float32), shape, nearest=False)
            for index in relevant_indices
        ],
        axis=0,
    )

    # Which grid cells this pipeline has an opinion about at all: the coarse argmax, taken over
    # every class the network knows, exactly as the old label map took it. Nearest neighbour carries
    # the answer to photo resolution, which keeps this stage bit-for-bit the decision it was before.
    is_relevant = np.zeros(probabilities.shape[0], dtype=bool)
    is_relevant[list(relevant_indices)] = True
    if is_relevant.all():
        # A class list that is nothing but the relevant ones — the synthetic cases in the tests.
        # Nothing can out-vote them, so every cell is claimed.
        coarse_claimed = np.ones(probabilities.shape[1:], dtype=bool)
    else:
        coarse_claimed = np.isin(np.argmax(probabilities, axis=0), np.nonzero(is_relevant)[0])
    claimed = _resize_to(coarse_claimed.astype(np.float32), shape, nearest=True) > 0.5

    winner = np.argmax(planes, axis=0)
    return np.where(claimed, winner, UNCLAIMED).astype(np.int16)


def semantic_regions(graph: Graph, photo_u8: np.ndarray) -> SemanticRegions:
    """Label the scene, and return the wall, the ceiling and
    the definitely-not-wall, at photo resolution.

    The logits come back at a quarter of the network's input side — a 128×128 grid for the
    512×512 input the checkpoint expects. The boundary between the classes this pipeline cares about
    is therefore decided at the photo's own resolution from bilinearly-upsampled probability planes,
    so it follows a probability contour rather than a staircase of 10-px steps. See
    :func:`argmax_at_photo_resolution` for the two stages and why the gate is not optional.
    """

    classes = graph.config["classes"]
    (logits,) = graph.run({"pixel_values": pixel_values(photo_u8, graph.config)})

    probabilities = _softmax(logits[0], axis=0)
    shape = photo_u8.shape[:2]
    indices = tuple(classes[name] for name in RELEVANT_CLASSES)
    labels = argmax_at_photo_resolution(probabilities, indices, shape)

    # The probability planes the refiner and the trust floor want: a soft answer to "how sure are we
    # about this pixel?", upsampled rather than re-decided.
    wall_prob = _resize_to(probabilities[classes["wall"]].astype(np.float32), shape, nearest=False)

    # Ceiling kept separately — for wall, ceiling is an exclusion (a repainted ceiling window is
    # instantly wrong); for ceiling, wall is the exclusion.
    ceiling_index = classes.get("ceiling")
    ceiling_is_available = ceiling_index is not None and ceiling_index < probabilities.shape[0]
    if ceiling_is_available:
        ceiling_prob = _resize_to(
            probabilities[ceiling_index].astype(np.float32), shape, nearest=False
        )
    else:
        ceiling_prob = np.zeros(shape, dtype=np.float32)

    # floor_exempt from #48 (mirror): the capability is here, the behaviour is not. #48 adds mirror
    # to the exported class set and a FLOOR_EXEMPT_CLASSES tuple beside RELEVANT_CLASSES, and this
    # becomes the upsampled mirror probability thresholded — an all-False plane today, so every
    # consumer reads exactly the behaviour it read before #48.
    floor_exempt = np.zeros(shape, dtype=bool)

    return SemanticRegions(
        wall=labels == _WALL_SLICE,
        excluded=np.isin(labels, _EXCLUDED_SLICES),
        wall_confidence=np.clip(wall_prob, 0.0, 1.0).astype(np.float32),
        ceiling=labels == _CEILING_SLICE if ceiling_is_available else np.zeros(shape, dtype=bool),
        ceiling_confidence=np.clip(ceiling_prob, 0.0, 1.0).astype(np.float32),
        floor_exempt=floor_exempt,
    )
