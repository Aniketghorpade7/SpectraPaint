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
from PIL import Image, ImageFilter

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


def erode(mask: np.ndarray, radius: int) -> np.ndarray:
    """Shrink a boolean region by ``radius`` pixels.

    Repeated 3x3 minimum filters rather than one large kernel: a single MinFilter of side 2r+1
    costs r squared work per pixel, and r passes of a 3x3 reach the same distance for far less.
    Pillow's filters are C, so this stays cheap at photo resolution — and it keeps the dependency
    list as it is, which matters more than elegance here (no scipy in the service).
    """

    if radius <= 0 or not mask.any():
        return mask

    image = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    for _ in range(radius):
        image = image.filter(ImageFilter.MinFilter(3))
    return np.asarray(image, dtype=np.uint8) > 127


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Grow a boolean region by ``radius`` pixels — :func:`erode`'s opposite, and the same trick.

    Together the two give a ring around a region's boundary (dilated minus eroded), which is how
    the matte's boundary band is found.
    """

    if radius <= 0 or not mask.any():
        return mask

    image = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    for _ in range(radius):
        image = image.filter(ImageFilter.MaxFilter(3))
    return np.asarray(image, dtype=np.uint8) > 127


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

    # Photo space to graph space. Both axes scale independently: the photo was squashed into a
    # square, so a single scale factor would put every prompt in the wrong place on any photo that
    # is not itself square.
    height, width = shape
    scale = np.asarray(
        [refiner_config["input_width"] / width, refiner_config["input_height"] / height],
        dtype=np.float32,
    )

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
