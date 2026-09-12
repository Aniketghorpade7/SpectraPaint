"""Turning the semantic wall region into prompts SAM 2 can be asked with.

This module is what "the wall region **constrains** SAM 2" means in code (spec, "Segmentation
pipeline"). SAM 2 is class-agnostic — it has no concept of a wall, and asked to segment freely it
returns dozens of unlabelled blobs. What it does have is precise boundaries. So the semantic pass
supplies the meaning, in the only vocabulary SAM 2 accepts: points that are on the thing, and
points that are not.

Three decisions, each of which changes the matte:

**Positive points come from the *eroded* wall, never the raw wall.** A point sampled near the
semantic boundary may well be sitting on ceiling, because that boundary is a quarter-resolution
staircase. One positive point in the wrong region is enough to make SAM 2 grow the mask into it,
and it is a mistake nothing downstream can undo.

**Negative points come from the named exclusions only** — floor, ceiling, windowpane, door — and not
from "everywhere that is not wall". Most of a photo is neither: a sofa is unlabelled, and marking it
negative would teach SAM 2 that the wall stops at the sofa's *top edge* rather than continuing
behind it.

**Sampling is a deterministic grid, not random.** Spread matters more than count — points clustered
in one corner describe one corner — and a fixed rule means the same photo yields the same matte
every time, which is what makes a regression test possible at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from spectrapaint.imaging import erode
from spectrapaint.segmentation.semantic import SemanticRegions

# How far inside a region a sampled point must sit, as a fraction of the photo's shorter side.
# Enough to clear the semantic pass's own coarseness — its labels are a quarter-resolution map
# upsampled, so its boundary is uncertain by several pixels at photo scale.
_EROSION_FRACTION = 0.015

# How the prompt budget is divided. Positives carry the meaning, so they get the larger share;
# negatives exist to stop the mask leaking into the floor and ceiling, which takes fewer.
_POSITIVE_SHARE = 0.625

# SAM's own convention, and the exporter writes it into runtime.json: 1 is on the object, 0 is off
# it, -1 is padding that contributes nothing.
LABEL_POSITIVE = 1
LABEL_NEGATIVE = 0


@dataclass(frozen=True)
class PromptSet:
    """Point prompts in the refiner graph's own input space, padded to its fixed width.

    ``coords`` is (1, 1, max_points, 2) as x, y — SAM's ordering, not numpy's — and ``labels`` is
    (1, 1, max_points). ``positive_count`` is kept for the caller to check: no positive points
    means nothing was found to prompt with, and asking SAM 2 anyway would return a mask of
    whatever happened to be in the middle of the frame.
    """

    coords: np.ndarray
    labels: np.ndarray
    positive_count: int
    negative_count: int


def erosion_radius(shape: tuple[int, int]) -> int:
    """How far inside a region prompts must sit, in pixels, for a photo of this size."""
    return max(1, round(min(shape) * _EROSION_FRACTION))


def sample_grid(mask: np.ndarray, budget: int) -> np.ndarray:
    """Up to ``budget`` points spread across ``mask``, as an (n, 2) array of x, y.

    The photo is divided into a grid with about as many cells as the budget, and each cell
    contributes the eligible pixel nearest its centre. Cells with nothing eligible contribute
    nothing, so a wall occupying a third of the frame yields points across that third rather than
    a third of the points.
    """

    if budget <= 0 or not mask.any():
        return np.zeros((0, 2), dtype=np.float32)

    height, width = mask.shape
    # A grid roughly square in cell count, biased to the photo's aspect so cells stay square-ish.
    columns = max(1, round(np.sqrt(budget * width / height)))
    rows = max(1, int(np.ceil(budget / columns)))

    points: list[tuple[float, float]] = []
    for row in range(rows):
        top, bottom = height * row // rows, height * (row + 1) // rows
        for column in range(columns):
            left, right = width * column // columns, width * (column + 1) // columns
            cell = mask[top:bottom, left:right]
            if not cell.any():
                continue
            ys, xs = np.nonzero(cell)
            # The eligible pixel closest to the cell's centre, so a point is representative of its
            # cell rather than being wherever the scan happened to start.
            centre_y, centre_x = (bottom - top - 1) / 2.0, (right - left - 1) / 2.0
            best = np.argmin((ys - centre_y) ** 2 + (xs - centre_x) ** 2)
            points.append((float(left + xs[best]), float(top + ys[best])))

    if len(points) > budget:
        # Evenly spaced through the list, which is in raster order, so dropping points thins the
        # set uniformly instead of removing one side of the room.
        keep = np.linspace(0, len(points) - 1, budget).round().astype(int)
        points = [points[index] for index in keep]

    return np.asarray(points, dtype=np.float32).reshape(-1, 2)


def _photo_to_graph_scale(refiner_config: dict, shape: tuple[int, int]) -> np.ndarray:
    """Photo space to graph space, as an (x, y) scale.

    Both axes scale independently: the photo was squashed into the graph's square input, so a
    single scale factor would put every prompt in the wrong place on any photo that is not itself
    square. Shared by every prompt builder in this module, so a coordinate bug cannot be fixed in
    one and left in another.
    """

    height, width = shape
    return np.asarray(
        [refiner_config["input_width"] / width, refiner_config["input_height"] / height],
        dtype=np.float32,
    )


def prompts_for(regions: SemanticRegions, refiner_config: dict) -> PromptSet:
    """Point prompts describing the wall region, in the refiner graph's input space.

    Coordinates are scaled from photo space into the graph's square input, because that is the
    space SAM 2's positional encoding is defined in and the photo was squashed into it by the same
    ratio.
    """

    max_points = int(refiner_config["max_prompt_points"])
    padding_label = int(refiner_config["padding_point_label"])
    shape = regions.wall.shape
    radius = erosion_radius(shape)

    positive_budget = int(round(max_points * _POSITIVE_SHARE))
    positive = sample_grid(erode(regions.wall, radius), positive_budget)
    negative = sample_grid(erode(regions.excluded, radius), max_points - len(positive))

    scale = _photo_to_graph_scale(refiner_config, shape)

    coords = np.zeros((1, 1, max_points, 2), dtype=np.float32)
    labels = np.full((1, 1, max_points), padding_label, dtype=np.int32)

    for index, point in enumerate(positive):
        coords[0, 0, index] = point * scale
        labels[0, 0, index] = LABEL_POSITIVE
    for offset, point in enumerate(negative):
        index = len(positive) + offset
        coords[0, 0, index] = point * scale
        labels[0, 0, index] = LABEL_NEGATIVE

    return PromptSet(
        coords=coords,
        labels=labels,
        positive_count=len(positive),
        negative_count=len(negative),
    )


def prompts_for_ceiling(regions: SemanticRegions, refiner_config: dict) -> PromptSet:
    """Point prompts describing the ceiling region — same treatment as :func:`prompts_for` but for
    the ceiling class. No plane splitting is needed for a ceiling (it is essentially always one
    region), so one decode suffices. The ceiling decode costs the cheap ~120 ms (encoder already
    cached per photo) rather than a second ~2 s encode.
    """

    max_points = int(refiner_config["max_prompt_points"])
    padding_label = int(refiner_config["padding_point_label"])
    shape = regions.ceiling.shape
    radius = erosion_radius(shape)

    positive_budget = int(round(max_points * _POSITIVE_SHARE))
    positive = sample_grid(erode(regions.ceiling, radius), positive_budget)
    # Negatives for ceiling: wall is the main thing not to leak into, plus the other exclusions
    # except ceiling itself. Build it without ceiling so a ceiling prompt's negatives do not contain
    # the very region it is trying to describe.
    other_excluded = regions.excluded & ~regions.ceiling
    ceiling_excluded = regions.wall | other_excluded
    negative = sample_grid(erode(ceiling_excluded, radius), max_points - len(positive))

    scale = _photo_to_graph_scale(refiner_config, shape)

    coords = np.zeros((1, 1, max_points, 2), dtype=np.float32)
    labels = np.full((1, 1, max_points), padding_label, dtype=np.int32)

    for index, point in enumerate(positive):
        coords[0, 0, index] = point * scale
        labels[0, 0, index] = LABEL_POSITIVE
    for offset, point in enumerate(negative):
        index = len(positive) + offset
        coords[0, 0, index] = point * scale
        labels[0, 0, index] = LABEL_NEGATIVE

    return PromptSet(
        coords=coords,
        labels=labels,
        positive_count=len(positive),
        negative_count=len(negative),
    )


def single_point_prompt(
    refiner_config: dict,
    photo_shape: tuple[int, int],
    x: float,
    y: float,
) -> PromptSet:
    """One positive point, in the refiner graph's own input space — the Dealer's own tap
    (ticket #10's Add tool), padded to the graph's fixed prompt width the same way
    :func:`prompts_for` pads its whole grid.

    No negatives: unlike the automatic pass, there is no ``SemanticRegions`` here to sample
    exclusions from — the correction surface works from the tapped point alone, and the Dealer's
    tap is the intent signal this prompt exists to carry.
    """

    max_points = int(refiner_config["max_prompt_points"])
    padding_label = int(refiner_config["padding_point_label"])
    scale = _photo_to_graph_scale(refiner_config, photo_shape)

    coords = np.zeros((1, 1, max_points, 2), dtype=np.float32)
    labels = np.full((1, 1, max_points), padding_label, dtype=np.int32)
    coords[0, 0, 0] = np.asarray([x, y], dtype=np.float32) * scale
    labels[0, 0, 0] = LABEL_POSITIVE

    return PromptSet(coords=coords, labels=labels, positive_count=1, negative_count=0)
