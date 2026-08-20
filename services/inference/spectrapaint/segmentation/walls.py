"""Finding the wall in a Room Photo: the pipeline, composed.

    semantic pass  ->  prompts  ->  SAM 2  ->  matte

Each step is a module of its own; this one puts them in order and decides what happens when there
is nothing to find. It is the only part of the segmentation package the rest of the service talks
to, so the pipeline's shape can change without the API knowing.

**One region, deliberately.** Ticket #6 finds *the wall*; splitting it into separate Wall Planes is
ticket #7. The return type is already a Wall Plane with an id rather than a bare array, because the
render contract has always spoken in planes and assignments — so #7 widens a list that already
exists instead of changing this surface.

**No wall found is an answer, not a crash.** A photo of a garden, or of a wall so occluded that
nothing is left of it, gets a plain-language failure the Dealer can act on. The alternative — a
fabricated rectangle, which is what the stub did — would answer a question nobody asked and paint
the middle of whatever the photo happens to show (conventions.md §5).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from spectrapaint.runtime.graphs import Graphs
from spectrapaint.segmentation.matte import refiner_alpha, wall_alpha
from spectrapaint.segmentation.prompts import prompts_for
from spectrapaint.segmentation.semantic import semantic_regions

# Shown to the Dealer as-is when a photo has no wall worth painting.
MESSAGE_NO_WALL_FOUND = (
    "No wall could be found in that photo. Please try a photo taken further back, with more of the "
    "wall in view."
)

# Below this fraction of the frame there is no wall worth offering to repaint. A wall glimpsed
# between furniture in two percent of the pixels is not something a Customer can judge a colour
# from, and recolouring it would look like a rendering fault rather than a paint choice.
MINIMUM_WALL_FRACTION = 0.02

# The Wall Plane id for the single region this ticket produces. Ticket #7 replaces this with one id
# per plane; the render contract's `assignments` map already accommodates that without changing.
FIRST_WALL_PLANE_ID = "wall_plane_1"


class NoWallFound(Exception):
    """This photo has no wall to paint.

    Carries a plain-language ``message`` the UI may show as-is, and the usual ``detail`` for the
    log — a Dealer cannot act on a coverage fraction, and whoever reads the log cannot act without
    one (conventions.md §5).
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.message = MESSAGE_NO_WALL_FOUND
        self.detail = detail


@dataclass(frozen=True)
class WallPlane:
    """One Wall Plane: its id, and the soft Alpha Matte saying which pixels it covers."""

    plane_id: str
    alpha: np.ndarray  # HxWx1 float32 in [0, 1]

    @property
    def coverage(self) -> float:
        """The share of the photo this plane covers, weighted by how covered each pixel is."""
        return float(self.alpha.mean())


def find_wall_planes(graphs: Graphs, photo_u8: np.ndarray) -> list[WallPlane]:
    """Every Wall Plane in the photo — one, for this ticket.

    Raises ``NoWallFound`` when the photo has no wall worth painting, which is checked twice for
    different reasons: the semantic pass may find too little wall to bother with, and the prompt
    step may find no point that sits safely inside what it did find. The second is the stricter
    test — a wall too thin to hold a point away from its own boundary cannot be prompted for
    without risking a mask of the ceiling.
    """

    regions = semantic_regions(graphs.semantic, photo_u8)
    if regions.wall_fraction < MINIMUM_WALL_FRACTION:
        raise NoWallFound(
            f"the semantic pass labelled {regions.wall_fraction:.1%} of the photo as wall, "
            f"below the {MINIMUM_WALL_FRACTION:.0%} needed"
        )

    prompts = prompts_for(regions, graphs.refiner_decoder.config)
    if prompts.positive_count == 0:
        raise NoWallFound(
            "no point sits far enough inside the wall region to prompt the refiner with"
        )

    refined = refiner_alpha(graphs, photo_u8, prompts)
    alpha = wall_alpha(photo_u8, regions, refined)

    plane = WallPlane(plane_id=FIRST_WALL_PLANE_ID, alpha=alpha)
    if plane.coverage < MINIMUM_WALL_FRACTION:
        raise NoWallFound(
            f"the refined matte covers {plane.coverage:.1%} of the photo, "
            f"below the {MINIMUM_WALL_FRACTION:.0%} needed"
        )
    return [plane]
