"""The #31 wall-confidence floor, and the classes exempt from it (#48).

Pure numpy on synthetic inputs, so it runs in the fast lane. This is the narrow exception
tests/README.md describes: the rule under test is arithmetic over boolean maps, which no photograph
can pin down more precisely than a two-by-two array can, and the slow lane's fixture tests already
cover whether the rule is the right one for real rooms.

The semantic graph here is a stand-in that returns fixed logits. It stands in for the ONNX session
only, so what is checked is how ``semantic_regions`` reads ``runtime.json``, never what the model
predicts.
"""

from __future__ import annotations

import numpy as np

from spectrapaint.runtime.graphs import Graph
from spectrapaint.segmentation.matte import _unvouched
from spectrapaint.segmentation.semantic import SemanticRegions, semantic_regions

# One pixel of each kind the floor has to decide about, in a 1x4 strip.
DOUBTED_MIRROR = 0  # argmax `mirror`, wall confidence 0.3 — sunlit wall, as this checkpoint sees it
DOUBTED_OTHER = 1  # argmax an unexempt class, wall confidence 0.3 — what the floor exists to remove
DOUBTED_WALL = 2  # argmax `wall`, wall confidence 0.3 — wall in shadow, exempt since #31
CONFIDENT = 3  # wall confidence 0.95 — above the floor, so never in question


def _regions(*, floor_exempt: list[bool]) -> SemanticRegions:
    shape = (1, 4)
    return SemanticRegions(
        wall=np.array([[False, False, True, True]]),
        excluded=np.zeros(shape, dtype=bool),
        wall_confidence=np.array([[0.3, 0.3, 0.3, 0.95]], dtype=np.float32),
        ceiling=np.zeros(shape, dtype=bool),
        ceiling_confidence=np.zeros(shape, dtype=np.float32),
        floor_exempt=np.array([floor_exempt]),
    )


def test_a_floor_exempt_pixel_is_not_removed_by_the_floor() -> None:
    regions = _regions(floor_exempt=[True, False, False, False])

    unvouched = _unvouched(regions, confident_wall=np.zeros((1, 4), dtype=bool))

    assert not unvouched[0, DOUBTED_MIRROR]


def test_the_same_pixel_without_the_exemption_is_still_removed() -> None:
    regions = _regions(floor_exempt=[False, False, False, False])

    unvouched = _unvouched(regions, confident_wall=np.zeros((1, 4), dtype=bool))

    assert unvouched[0, DOUBTED_MIRROR]
    assert unvouched[0, DOUBTED_OTHER]


def test_argmax_wall_and_confident_pixels_stay_exempt_as_before() -> None:
    regions = _regions(floor_exempt=[True, False, False, False])

    unvouched = _unvouched(regions, confident_wall=np.zeros((1, 4), dtype=bool))

    assert not unvouched[0, DOUBTED_WALL]
    assert not unvouched[0, CONFIDENT]
    assert unvouched[0, DOUBTED_OTHER]


class _FixedLogits:
    """An ONNX session's ``run``, returning logits decided in advance."""

    def __init__(self, logits: np.ndarray) -> None:
        self._logits = logits

    def run(self, _outputs: None, _inputs: dict[str, np.ndarray]) -> list[np.ndarray]:
        return [self._logits]


# Index 27 is `mirror` in the pinned checkpoint, but nothing here relies on that: the config below
# is the only place these indices exist, exactly as `runtime.json` is at runtime.
_CLASSES = {"wall": 0, "floor": 1, "ceiling": 2, "windowpane": 3, "door": 4}
_MIRROR = 5


def _graph(config_extra: dict) -> Graph:
    # A 2x2 logit map at the network's resolution: top row mirror, bottom row wall.
    logits = np.full((1, 6, 2, 2), -10.0, dtype=np.float32)
    logits[0, _MIRROR, 0, :] = 10.0
    logits[0, _CLASSES["wall"], 1, :] = 10.0
    config = {
        "classes": _CLASSES,
        "input_height": 8,
        "input_width": 8,
        "rescale_factor": 1 / 255,
        "image_mean": [0.5, 0.5, 0.5],
        "image_std": [0.5, 0.5, 0.5],
        **config_extra,
    }
    return Graph(session=_FixedLogits(logits), config=config)


def test_floor_exempt_classes_are_mapped_at_photo_resolution() -> None:
    photo = np.zeros((4, 6, 3), dtype=np.uint8)

    regions = semantic_regions(_graph({"floor_exempt_classes": {"mirror": _MIRROR}}), photo)

    assert regions.floor_exempt.shape == (4, 6)
    assert regions.floor_exempt.dtype == bool
    assert regions.floor_exempt[:2].all()
    assert not regions.floor_exempt[2:].any()
    # An exemption is not an exclusion: the mirror half is not marked definitely-not-wall.
    assert not regions.excluded.any()


def test_an_older_runtime_json_without_the_key_exempts_nothing() -> None:
    photo = np.zeros((4, 6, 3), dtype=np.uint8)

    regions = semantic_regions(_graph({}), photo)

    assert regions.floor_exempt.shape == (4, 6)
    assert not regions.floor_exempt.any()
