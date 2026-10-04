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
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from spectrapaint.runtime.graphs import Graph

# The classes that are never wall. `wall` itself is handled separately, and everything unnamed —
# furniture, curtains, people — is left unclaimed rather than guessed at.
EXCLUDED_CLASSES = ("floor", "ceiling", "windowpane", "door")


@dataclass(frozen=True)
class SemanticRegions:
    """Where the semantic pass thinks the wall and ceiling are, at the photo's own resolution.

    ``wall`` and ``excluded`` are boolean maps of the same height and width as the photo that was
    passed in. ``wall_confidence`` is the model's softmax probability for the wall class, kept
    because the refinement stage needs a soft answer to the question "how sure are we?" and a
    boolean map has thrown that away. ``ceiling`` and ``ceiling_confidence`` are the same for the
    ceiling class — kept separately so the ceiling plane can be built from its own region without
    re-deriving it from ``excluded`` (which for wall purposes still contains ceiling as an
    exclusion, and must keep doing so).

    ``floor_exempt`` is where the argmax is a class the matte's wall-confidence floor must not
    delete (#48): this checkpoint labels bright, washed-out wall ``mirror``. It is the opposite of
    an exclusion. It says nothing about whether a pixel is wall, only that low wall confidence
    there is not evidence against it. Read from ``runtime.json``'s ``floor_exempt_classes``; a
    ``runtime.json`` written before that key existed exempts nothing.
    """

    wall: np.ndarray  # HxW bool
    excluded: np.ndarray  # HxW bool
    wall_confidence: np.ndarray  # HxW float32 in [0, 1]
    ceiling: np.ndarray  # HxW bool
    ceiling_confidence: np.ndarray  # HxW float32 in [0, 1]
    floor_exempt: np.ndarray  # HxW bool

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


def semantic_regions(graph: Graph, photo_u8: np.ndarray) -> SemanticRegions:
    """Label the scene, and return the wall, the ceiling and
    the definitely-not-wall, at photo resolution.

    The logits come back at a quarter of the network's input side, which is coarse — a blocky
    staircase where the wall meets the ceiling. That is expected and is not corrected here: the
    boundary is SAM 2's job and the refinement pass's job, and this map only has to be right about
    *what* things are (design-decisions.md §5: "the network's job is correct region semantics, not
    crisp edges").
    """

    classes = graph.config["classes"]
    (logits,) = graph.run({"pixel_values": pixel_values(photo_u8, graph.config)})

    probabilities = _softmax(logits[0], axis=0)
    labels = np.argmax(probabilities, axis=0)
    shape = photo_u8.shape[:2]

    wall_index = classes["wall"]
    wall_small = labels == wall_index
    excluded_small = np.zeros_like(wall_small)
    for name in EXCLUDED_CLASSES:
        excluded_small |= labels == classes[name]

    # Kept apart from `classes` in runtime.json so nothing can mistake it for an exclusion. Absent
    # from a runtime.json exported before #48, which then exempts nothing: the floor behaves as it
    # did, rather than the service refusing to start.
    floor_exempt_small = np.zeros_like(wall_small)
    for index in graph.config.get("floor_exempt_classes", {}).values():
        floor_exempt_small |= labels == index

    # Ceiling kept separately — for wall, ceiling is an exclusion (a repainted ceiling window is
    # instantly wrong); for ceiling, wall is the exclusion. The label map itself is exclusive
    # (argmax), so wall and ceiling never overlap here.
    ceiling_index = classes.get("ceiling")
    if ceiling_index is not None:
        ceiling_small = labels == ceiling_index
    else:
        ceiling_small = np.zeros_like(wall_small)

    # Resized as floats and thresholded back, because Pillow has no boolean mode. Nearest
    # neighbour, so a resized label map contains only labels that were actually predicted.
    wall = _resize_to(wall_small.astype(np.float32), shape, nearest=True) > 0.5
    excluded = _resize_to(excluded_small.astype(np.float32), shape, nearest=True) > 0.5
    confidence = _resize_to(probabilities[wall_index], shape, nearest=False)
    ceiling = _resize_to(ceiling_small.astype(np.float32), shape, nearest=True) > 0.5
    floor_exempt = _resize_to(floor_exempt_small.astype(np.float32), shape, nearest=True) > 0.5
    if ceiling_index is not None and ceiling_index < probabilities.shape[0]:
        ceiling_conf = _resize_to(probabilities[ceiling_index], shape, nearest=False)
    else:
        ceiling_conf = np.zeros(shape, dtype=np.float32)

    return SemanticRegions(
        wall=wall,
        excluded=excluded,
        wall_confidence=np.clip(confidence, 0.0, 1.0).astype(np.float32),
        ceiling=ceiling,
        ceiling_confidence=np.clip(ceiling_conf, 0.0, 1.0).astype(np.float32),
        floor_exempt=floor_exempt,
    )
