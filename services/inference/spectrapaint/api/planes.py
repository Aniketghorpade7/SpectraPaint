"""The Wall Planes a photo has: ``GET /sessions/{id}/planes`` (ticket #6).

Two routes, because the answer has two halves that want different treatment:

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
"""

import io

import numpy as np
from fastapi import APIRouter, Request, Response, status
from PIL import Image

from spectrapaint.api.errors import MALFORMED_REQUEST, ServiceError
from spectrapaint.api.sessions import require_photo
from spectrapaint.segmentation.walls import WallPlane

router = APIRouter(prefix="/sessions", tags=["planes"])

_MESSAGE_UNKNOWN_WALL_PLANE = (
    "That wall is not one this photo has. Please choose a wall in the photo and try again."
)

# Below this coverage a matte's row or column is not treated as part of the plane when working out
# its bounds. A handful of faintly-covered pixels at the edge of a soft matte would otherwise
# stretch the box to the whole photo and make it useless for cropping.
_BOUNDS_COVERAGE = 0.5


@router.get("/{session_id}/planes")
async def list_planes(request: Request, session_id: str) -> dict[str, list[dict[str, object]]]:
    """Every Wall Plane found in this photo, once preparation has finished.

    One plane today. The response is a list rather than an object so that #7's two or three planes
    are more of the same answer rather than a different one.
    """

    prepared = await require_photo(request, session_id)
    return {"planes": [_describe(plane) for plane in prepared.planes]}


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
