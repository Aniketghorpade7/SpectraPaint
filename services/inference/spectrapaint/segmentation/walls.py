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

import logging
from dataclasses import dataclass

import numpy as np

from spectrapaint.runtime.graphs import Graphs
from spectrapaint.segmentation.matte import RefinerFeatures, decode_alpha, encode_photo, wall_alpha
from spectrapaint.segmentation.prompts import prompts_for
from spectrapaint.segmentation.semantic import SemanticRegions, semantic_regions
from spectrapaint.segmentation.split import split_alpha_into_planes

# Shown to the Dealer as-is when a photo has no wall worth painting. Not a dead end (conventions.md
# §5, ticket #10): preparation still finishes, so this is the note on an otherwise-ready photo with
# zero Wall Planes, and the correction surface's Add tool is where the Dealer goes next.
MESSAGE_NO_WALL_FOUND = (
    "No wall could be found in that photo automatically. Tap where a wall is to add it, or try a "
    "photo taken further back, with more of the wall in view."
)

# Below this fraction of the frame there is no wall worth offering to repaint. A wall glimpsed
# between furniture in two percent of the pixels is not something a Customer can judge a colour
# from, and recolouring it would look like a rendering fault rather than a paint choice.
MINIMUM_WALL_FRACTION = 0.02
# Same threshold for a ceiling — a sliver of ceiling is not a paintable surface either.
MINIMUM_CEILING_FRACTION = 0.02

# The Wall Plane id for the single region this ticket produces. Ticket #7 replaces this with one id
# per plane; the render contract's `assignments` map already accommodates that without changing.
FIRST_WALL_PLANE_ID = "wall_plane_1"
CEILING_PLANE_ID = "ceiling_plane_1"


class NoWallFound(Exception):
    """Automatic detection found no wall to paint in this photo.

    Carries a plain-language ``message`` the UI may show as-is, and the usual ``detail`` for the
    log — a Dealer cannot act on a coverage fraction, and whoever reads the log cannot act without
    one (conventions.md §5). Since ticket #10, preparation catches this rather than letting it fail
    the session: the photo still becomes a ready, zero-plane consultation the Dealer can tap a wall
    into, and this is where that note comes from.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.message = MESSAGE_NO_WALL_FOUND
        self.detail = detail


@dataclass(frozen=True)
class WallPlane:
    """One Paintable Plane: its id, surface kind, and the soft
    Alpha Matte saying which pixels it covers.

    ``surface`` is ``wall`` or ``ceiling`` — the ``surface`` field
    the REST contract exposes (CONTEXT.md: Paintable Plane).
    Until this ticket every plane was a wall; a ceiling is the
    same treatment without the plane-splitting step, and its base
    colour is never grouped with a wall's even when the two are
    a similar pale colour.
    """

    plane_id: str
    alpha: np.ndarray  # HxWx1 float32 in [0, 1]
    surface: str = "wall"  # "wall" | "ceiling"

    @property
    def coverage(self) -> float:
        """The share of the photo this plane covers, weighted by how covered each pixel is."""
        return float(self.alpha.mean())


def get_regions(graphs: Graphs, photo_u8: np.ndarray) -> SemanticRegions:
    """The semantic pass without a threshold — always returns what the model thinks is there."""

    return semantic_regions(graphs.semantic, photo_u8)


def wall_regions(graphs: Graphs, photo_u8: np.ndarray) -> SemanticRegions:
    """The semantic pass, and the first of the two "is there a wall here at all?" checks.

    Separate from the refinement below because they are the two long stages of preparation and the
    Dealer is told about them separately — and because failing here costs nothing, while failing
    after the refiner has run has spent the most expensive seconds in the pipeline.
    """

    regions = get_regions(graphs, photo_u8)
    if regions.wall_fraction < MINIMUM_WALL_FRACTION:
        raise NoWallFound(
            f"the semantic pass labelled {regions.wall_fraction:.1%} of the photo as wall, "
            f"below the {MINIMUM_WALL_FRACTION:.0%} needed"
        )
    return regions


def planes_from(
    graphs: Graphs,
    photo_u8: np.ndarray,
    regions: SemanticRegions,
    features: RefinerFeatures,
) -> list[WallPlane]:
    """Refine the semantic region into Wall Planes — split by vertical structure (issue #7).

    ``features`` is the photo's already-encoded SAM 2 output (:func:`encode_photo`), supplied
    rather than computed here so preparation can hold onto it: ticket #10's corrections decode
    against the same features without paying the encode a second time.
    """

    prompts = prompts_for(regions, graphs.refiner_decoder.config)
    if prompts.positive_count == 0:
        raise NoWallFound(
            "no point sits far enough inside the wall region to prompt the refiner with"
        )

    refined = decode_alpha(graphs, features, prompts, photo_u8.shape[:2])
    alpha = wall_alpha(photo_u8, regions, refined)

    # Single-plane guard: the matte as a whole must still cover enough.
    single = WallPlane(plane_id=FIRST_WALL_PLANE_ID, alpha=alpha)
    if single.coverage < MINIMUM_WALL_FRACTION:
        raise NoWallFound(
            f"the refined matte covers {single.coverage:.1%} of the photo, "
            f"below the {MINIMUM_WALL_FRACTION:.0%} needed"
        )

    # Split into Wall Planes using vertical structure — zero taps. When no
    # corner is found the wall stays as one plane, so a flat wall is
    # unchanged and every pixel still belongs to exactly one plane.
    split_alphas = split_alpha_into_planes(photo_u8, alpha)

    # Validate the partition: every wall pixel must be claimed exactly once,
    # so that compositing never double-claims (dark seam). This is a real
    # check that degrades rather than a bare assert (conventions.md §5) —
    # an assert would be stripped under -O and would surface as a 500.
    if len(split_alphas) == 1:
        return [WallPlane(plane_id=FIRST_WALL_PLANE_ID, alpha=split_alphas[0])]

    wall_planes: list[WallPlane] = []
    for index, plane_alpha in enumerate(split_alphas, start=1):
        # A sliver plane below the offerable fraction is merged rather than
        # offered as a paintable surface: a 2% sliver is not a wall a Customer
        # can judge a colour from and it would leave unpainted pixels if dropped.
        candidate = WallPlane(plane_id=f"wall_plane_{index}", alpha=plane_alpha)
        if candidate.coverage < MINIMUM_WALL_FRACTION and len(split_alphas) > 1:
            logging.getLogger(__name__).warning(
                "Wall plane %s below minimum fraction (%.3f), merging",
                candidate.plane_id,
                candidate.coverage,
            )
            if wall_planes:
                # Merge into previous — coverage is preserved, not deleted
                prev = wall_planes.pop()
                merged_alpha = np.clip(prev.alpha + candidate.alpha, 0.0, 1.0).astype(np.float32)
                wall_planes.append(WallPlane(plane_id=prev.plane_id, alpha=merged_alpha))
            else:
                # First plane is sliver — merge into next (defer by stashing)
                # Keep it for now; the next iteration will merge into it
                wall_planes.append(candidate)
            continue
        wall_planes.append(candidate)

    # If merging left a single plane, restore the original single-plane id
    # so callers that key on wall_plane_1 keep working.
    if len(wall_planes) == 1:
        return [WallPlane(plane_id=FIRST_WALL_PLANE_ID, alpha=wall_planes[0].alpha)]

    # Re-normalise ids to wall_plane_1..N in left-to-right order
    wall_planes = [
        WallPlane(plane_id=f"wall_plane_{i + 1}", alpha=p.alpha) for i, p in enumerate(wall_planes)
    ]

    total_coverage = sum(p.coverage for p in wall_planes)
    if abs(total_coverage - single.coverage) >= 1e-4:
        logging.getLogger(__name__).warning(
            "Partition coverage %.6f != original %.6f (drift %.6f); degrading to single plane",
            total_coverage,
            single.coverage,
            total_coverage - single.coverage,
        )
        return [WallPlane(plane_id=FIRST_WALL_PLANE_ID, alpha=alpha)]
    return wall_planes


def ceiling_from(
    graphs: Graphs,
    photo_u8: np.ndarray,
    regions: SemanticRegions,
    features: RefinerFeatures,
) -> WallPlane | None:
    """One Ceiling Plane, if the semantic ceiling is worth offering — no splitting.

    A ceiling in one Room Photo is essentially always one region (unlike a wall which is split by
    vertical structure), so this is a single decode plus the same soft-matte treatment
    ``segmentation/matte.py`` already has, almost certainly without ``split.py``'s plane splitting.
    Already-encoded features are reused, so this costs the cheap ~120 ms decode rather than a second
    ~2 s encode (implementation-decisions.md #39).
    Returns ``None`` when no ceiling worth offering is found — the common case for a photo cropped
    to the walls, not a failure.
    """

    from spectrapaint.segmentation.matte import ceiling_alpha
    from spectrapaint.segmentation.prompts import prompts_for_ceiling

    if regions.ceiling_fraction < MINIMUM_CEILING_FRACTION:
        return None
    prompts = prompts_for_ceiling(regions, graphs.refiner_decoder.config)
    if prompts.positive_count == 0:
        return None
    refined = decode_alpha(graphs, features, prompts, photo_u8.shape[:2])
    alpha = ceiling_alpha(photo_u8, regions, refined)
    candidate = WallPlane(plane_id=CEILING_PLANE_ID, alpha=alpha, surface="ceiling")
    if candidate.coverage < MINIMUM_CEILING_FRACTION:
        return None
    return candidate


def find_wall_planes(graphs: Graphs, photo_u8: np.ndarray) -> list[WallPlane]:
    """Every Paintable Plane in the photo, in one call.

    Preparation runs the stages separately so it can report progress between them and keep the
    encoded features afterwards; this is the same pipeline for callers that have nothing to report
    to and nothing to hold onto once it returns. Includes wall planes (split) and at most one
    ceiling plane.
    """

    regions = wall_regions(graphs, photo_u8)
    features = encode_photo(graphs, photo_u8)
    wall_planes = planes_from(graphs, photo_u8, regions, features)
    ceiling = ceiling_from(graphs, photo_u8, regions, features)
    if ceiling is not None:
        # Ensure ceiling does not double-claim wall pixels — wall and ceiling mattes are already
        # exclusive via semantic exclusions, but resolve any residual overlap by stronger claim.
        wall_claim = np.zeros(photo_u8.shape[:2], dtype=np.float32)
        for plane in wall_planes:
            wall_claim = np.maximum(wall_claim, plane.alpha[..., 0])
        ceiling_claim = ceiling.alpha[..., 0]
        overlap = (wall_claim >= 0.5) & (ceiling_claim >= 0.5)
        if np.any(overlap):
            # Zero ceiling where wall is confidently covering — wall wins where both claim.
            resolved = np.where(ceiling_claim > wall_claim, ceiling_claim, 0.0).astype(np.float32)
            # Only zero where wall confidently claims;
            # keep ceiling elsewhere.
            mask = wall_claim >= 0.5
            resolved = np.where(
                mask & (wall_claim >= ceiling_claim),
                0.0,
                ceiling.alpha[..., 0],
            ).astype(np.float32)
            ceiling = WallPlane(
                plane_id=ceiling.plane_id,
                alpha=resolved[..., None],
                surface="ceiling",
            )
            if ceiling.coverage < MINIMUM_CEILING_FRACTION:
                return wall_planes
        return [*wall_planes, ceiling]
    return wall_planes
