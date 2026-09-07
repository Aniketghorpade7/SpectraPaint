"""The Wall Planes a photo has, and correcting them by tapping (tickets #6, #10).

Five routes. The first two answer "what is there":

``GET /sessions/{id}/planes``
    JSON. What planes exist, their ids, and where each one is. Small, cacheable by the caller, and
    the thing ``assignments`` keys are read from.

``GET /sessions/{id}/planes/{plane_id}/matte``
    PNG. The Alpha Matte itself, as an 8-bit greyscale image, which is what the UI overlays on the
    photo to show the Dealer what was found.

**Why the matte is a second route rather than a field.** A matte is a megapixel of data. Inlined as
base64 it would inflate the JSON by roughly a third of a megabyte per plane, force the UI to hold
the whole thing as a string before it could draw anything, and make the cheap question ("what planes
are there?") pay for the expensive answer. Serving it as an image also means the renderer can hand
it straight to the browser, which decodes PNGs far faster than JavaScript can unpack base64 — the
same reasoning that made the repaint a PNG response rather than a JSON blob
(docs/implementation-decisions.md §18).

Waiting is the same deal the render endpoint makes: a request that arrives while preparation is
still running is served when it finishes, not refused. The Dealer's UI asks for the planes as soon
as the photo is uploaded, and "not ready" would only mean it had to ask again.

The other three are ticket #10's corrections, one per tool the Dealer can arm — Add, Split, Merge —
each taking the one tap point that tool needs and nothing else (implementation-decisions.md #40).
All three answer with the same shape ``GET /sessions/{id}/planes`` does, so the Dealer's UI treats a
correction's result exactly like a fresh load: replace the plane list, done. None of them touch the
photo or re-run preparation — the segmentation work lives in ``segmentation/corrections.py``; this
module is only the HTTP translation, same division as everywhere else in ``api/``.
"""

import io

import numpy as np
from fastapi import APIRouter, Request, Response, status
from PIL import Image
from pydantic import BaseModel, Field

from spectrapaint.api.errors import MALFORMED_REQUEST, ServiceError
from spectrapaint.api.preparation import PreparedPhoto
from spectrapaint.api.sessions import require_job, require_photo
from spectrapaint.runtime.graphs import load as load_graphs
from spectrapaint.segmentation.corrections import (
    CorrectionRefused,
    add_plane,
    check_addable,
    merge_planes,
    order_left_to_right,
    split_plane,
)
from spectrapaint.segmentation.matte import encode_photo
from spectrapaint.segmentation.walls import WallPlane

router = APIRouter(prefix="/sessions", tags=["planes"])

_MESSAGE_UNKNOWN_WALL_PLANE = (
    "That wall is not one this photo has. Please choose a wall in the photo and try again."
)

_MESSAGE_TAP_OUTSIDE_THE_PHOTO = "That tap landed outside the photo. Please try again."

# Below this coverage a matte's row or column is not treated as part of the plane when working out
# its bounds. A handful of faintly-covered pixels at the edge of a soft matte would otherwise
# stretch the box to the whole photo and make it useless for cropping.
_BOUNDS_COVERAGE = 0.5


@router.get("/{session_id}/planes")
async def list_planes(request: Request, session_id: str) -> dict[str, object]:
    """Every Wall Plane found in this photo, once preparation has finished.

    The list can be empty. Automatic detection finding nothing is not a preparation failure since
    ticket #10 — ``note`` carries why in plain language, so the UI can show it beside the correction
    surface's Add tool rather than treat an empty list as broken. ``note`` is ``null`` the rest of
    the time. The planes themselves may also reflect a correction made since preparation finished —
    ``require_photo`` is what keeps that transparent to this route.
    """

    prepared = await require_photo(request, session_id)
    return _planes_response(prepared, prepared.planes, prepared.note)


def _planes_response(
    prepared: PreparedPhoto, planes: tuple[WallPlane, ...], note: str | None
) -> dict[str, object]:
    """The shape every planes-listing and every correction answers with.

    ``note`` is an explicit argument rather than always ``prepared.note``: a correction's own
    result must not carry forward a stale "no wall found automatically" note from before it ran —
    every successful correction leaves at least one plane, so its own answer is always ``None``,
    regardless of what preparation originally said. Only ``list_planes`` ever passes
    ``prepared.note`` through.

    ``photo_width``/``photo_height`` are top-level, not just repeated on each plane
    (:func:`_describe` already carries them there too, for a caller reading one plane in
    isolation) — a photo can legitimately have zero planes (no wall found at all), and the
    correction surface's Add tool needs the photo's own dimensions to turn a tap into a point in
    this space precisely in that case (implementation-decisions.md §40,
    apps/ui/src/consultation/corrections.ts).
    """

    height, width = prepared.srgb.shape[:2]
    return {
        "planes": [_describe(plane) for plane in planes],
        "note": note,
        "photo_width": int(width),
        "photo_height": int(height),
    }


class TapPoint(BaseModel):
    """Where the Dealer tapped, in the prepared photo's own pixel space.

    The same coordinate system ``GET /sessions/{id}/planes`` already describes via
    ``photo_width``/``photo_height`` — no new space for a client to learn
    (implementation-decisions.md #40).
    """

    x: int = Field(ge=0)
    y: int = Field(ge=0)


def _point_in_bounds(point: TapPoint, prepared: PreparedPhoto) -> tuple[int, int]:
    height, width = prepared.srgb.shape[:2]
    if point.x >= width or point.y >= height:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=MALFORMED_REQUEST,
            message=_MESSAGE_TAP_OUTSIDE_THE_PHOTO,
        )
    return point.x, point.y


def _refused(failure: CorrectionRefused) -> ServiceError:
    return ServiceError(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code=MALFORMED_REQUEST,
        message=failure.message,
    )


@router.post("/{session_id}/planes", status_code=status.HTTP_201_CREATED)
async def add_wall(request: Request, session_id: str, body: TapPoint) -> dict[str, object]:
    """Add a missed Wall Plane from one tapped point — the Add tool, and the surface reachable
    when automatic detection found nothing at all (``note`` on ``GET .../planes``) as much as
    when it simply missed a sliver at the frame edge.

    SAM 2 decodes against the photo's already-encoded features (``prepared.features``); a
    session whose semantic pass found no wall region to encode against in the first place
    (difficulty 21) encodes here instead, once, and the result is cached on the job so a second
    Add on the same session never pays for it twice.

    ``check_addable`` runs before either model call, not just before the decode: a tap that is
    already covered is refused for free, the same way Split's and Merge's own preconditions
    already are, rather than paying for an encoder it was never going to need.
    """

    prepared = await require_photo(request, session_id)
    point = _point_in_bounds(body, prepared)
    job = require_job(request, session_id)

    try:
        check_addable(prepared.planes, point)
    except CorrectionRefused as failure:
        raise _refused(failure) from None

    graphs = load_graphs()
    features = prepared.features
    if features is None:
        features = encode_photo(graphs, prepared.srgb)
        job.cache_features(features)

    try:
        new_plane, adjusted_existing = add_plane(
            graphs, prepared.srgb, features, point, prepared.planes
        )
    except CorrectionRefused as failure:
        raise _refused(failure) from None

    updated = order_left_to_right((new_plane, *adjusted_existing))
    job.replace_planes(updated)
    return _planes_response(prepared, updated, None)


@router.post("/{session_id}/planes/split", status_code=status.HTTP_201_CREATED)
async def split_wall(request: Request, session_id: str, body: TapPoint) -> dict[str, object]:
    """Split the Wall Plane under the tapped point into two — the Split tool, for a corner the
    automatic splitter merged into one wall.

    No model call: the cut is the same hard vertical partition the automatic splitter makes
    (segmentation/split.py), at the Dealer's own column instead of a detected one, so this never
    re-runs preparation.
    """

    prepared = await require_photo(request, session_id)
    point = _point_in_bounds(body, prepared)

    try:
        first, second, target = split_plane(prepared.srgb, prepared.planes, point)
    except CorrectionRefused as failure:
        raise _refused(failure) from None

    remaining = [plane for plane in prepared.planes if plane.plane_id != target.plane_id]
    updated = order_left_to_right((first, second, *remaining))
    require_job(request, session_id).replace_planes(updated)
    return _planes_response(prepared, updated, None)


@router.post("/{session_id}/planes/merge", status_code=status.HTTP_200_OK)
async def merge_walls(request: Request, session_id: str, body: TapPoint) -> dict[str, object]:
    """Merge the two Wall Planes meeting nearest the tapped point into one — the Merge tool, for
    a corner the automatic splitter split when it should not have.

    No model call: the two mattes are already disjoint (spec, "Corners"), so the union is a
    plain sum, and this never re-runs preparation either.
    """

    prepared = await require_photo(request, session_id)
    point = _point_in_bounds(body, prepared)

    try:
        merged, first, second = merge_planes(prepared.planes, point)
    except CorrectionRefused as failure:
        raise _refused(failure) from None

    remaining = [
        plane
        for plane in prepared.planes
        if plane.plane_id not in (first.plane_id, second.plane_id)
    ]
    updated = order_left_to_right((merged, *remaining))
    require_job(request, session_id).replace_planes(updated)
    return _planes_response(prepared, updated, None)


@router.get("/{session_id}/planes/{plane_id}/matte")
async def plane_matte(request: Request, session_id: str, plane_id: str) -> Response:
    """One plane's Alpha Matte, as an 8-bit greyscale PNG.

    Greyscale rather than an RGBA image with a transparent colour: the matte *is* one channel, and
    sending three more of them would triple the payload to say nothing. What colour to draw it in
    is the UI's decision, not the service's (ui-guidelines.md).
    """

    prepared = await require_photo(request, session_id)
    plane = prepared.plane(plane_id)
    if plane is None:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=MALFORMED_REQUEST,
            message=_MESSAGE_UNKNOWN_WALL_PLANE,
        )

    png_bytes = _encode_matte(plane)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Length": str(len(png_bytes))},
    )


def _describe(plane: WallPlane) -> dict[str, object]:
    """One plane as JSON: what it is called, how much it covers, and where it is.

    ``bounds`` is the box the plane occupies, in photo pixels. The render path crops to it before
    the per-tap maths (spec, "Performance"), and the UI uses it to place a label without having to
    fetch and scan the matte first.
    """

    coverage = plane.alpha[..., 0]
    covered = coverage >= _BOUNDS_COVERAGE
    rows = np.flatnonzero(covered.any(axis=1))
    columns = np.flatnonzero(covered.any(axis=0))

    if len(rows) == 0 or len(columns) == 0:
        # A matte with no confidently-covered pixel at all. The plane still exists — it passed the
        # coverage check on the way in — so it is described with an empty box rather than omitted,
        # because a plane missing from this list is a plane the UI cannot offer a Shade for.
        bounds = None
    else:
        bounds = {
            "left": int(columns[0]),
            "top": int(rows[0]),
            "right": int(columns[-1]) + 1,
            "bottom": int(rows[-1]) + 1,
        }

    height, width = coverage.shape
    return {
        "plane_id": plane.plane_id,
        "coverage": round(plane.coverage, 4),
        "bounds": bounds,
        "photo_width": int(width),
        "photo_height": int(height),
    }


def _encode_matte(plane: WallPlane) -> bytes:
    """The matte as PNG bytes: [0, 1] float coverage to 0-255 greyscale.

    Rounded rather than truncated, so a fully-covered pixel comes out as 255 rather than 254 — the
    UI compares against the ends of that range to decide what is fully inside the wall.
    """

    coverage = np.clip(plane.alpha[..., 0], 0.0, 1.0)
    grey = (coverage * 255.0 + 0.5).astype(np.uint8)

    buffer = io.BytesIO()
    Image.fromarray(grey, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()
