"""Render requests: ``POST /sessions/{session_id}/renders`` (issue #3 / #7).

Takes ``assignments`` — a Shade Code per Wall Plane, exactly the shape the spec
pins — and returns the repainted photo as PNG bytes. The photo itself never
appears in the request: it entered at upload (encode-once,
docs/specs/v1-spectrapaint.md), and this endpoint works from the session's
prepared photo — structure enforces the rule, not a comment.

The Shade is looked up in the live Catalogue (issue #5), so a render can only
ask for a Shade the Dealer can actually sell.

The wall is the real thing (ticket #6): the Wall Plane mattes the segmentation
pipeline found, and Base Colours measured inside each matte. Issue #7 splits
the wall into Wall Planes, so ``assignments`` now carries one entry per plane
the Dealer wants to repaint — an Accent Wall is two planes with two Shades in
one request (docs/specs/v1-spectrapaint.md).

What is not a stub is the contract: ``assignments``, mode semantics
(realistic = tinted by the room's light, true_colour = as the chip), the error
shape, and PNG output. The segmentation tickets swap internals; they must not
change this surface.
"""

import io
from typing import Literal

import numpy as np
from fastapi import APIRouter, Request, Response, status
from PIL import Image
from pydantic import BaseModel

from spectrapaint.api.errors import MALFORMED_REQUEST, SHADE_NOT_FOUND, ServiceError
from spectrapaint.api.preparation import PreparedPhoto
from spectrapaint.api.sessions import require_photo
from spectrapaint.catalogue import Catalogue
from spectrapaint.render.colour import lab_to_linear_rgb
from spectrapaint.render.engine import estimate_light_tint, render_many
from spectrapaint.segmentation.walls import WallPlane

router = APIRouter(prefix="/sessions", tags=["renders"])

_MESSAGE_SHADE_NOT_FOUND = (
    "That Shade Code is not in this Catalogue. Please check the code on the chip, "
    "or search by name."
)

_MESSAGE_UNKNOWN_WALL_PLANE = (
    "That wall is not one this photo has. Please choose a wall in the photo and try again."
)

# The one rendering mode vocabulary. Literal keeps a misspelled mode a clear
# client error (422 malformed_request) instead of a silent default.
RenderMode = Literal["realistic", "true_colour"]

# True Colour mode shows the shade as the colour chip: the room's light colour
# is not applied, so the tint factor is neutral (1, 1, 1).
_NEUTRAL_TINT = np.ones(3, dtype=np.float32)


class RenderRequest(BaseModel):
    """A Shade Code per Wall Plane, and how to show the result.

    ``assignments`` maps a Wall Plane id to a Shade Code, which is the spec's
    shape and the reason an Accent Wall is expressible without changing this
    surface. The ids a photo has come from ``GET /sessions/{id}/planes``; ticket
    #7 makes that list longer without changing the body.
    """

    assignments: dict[str, str]
    mode: RenderMode = "realistic"


def _catalogue(request: Request) -> Catalogue:
    return request.app.state.catalogue


@router.post("/{session_id}/renders", status_code=status.HTTP_201_CREATED)
async def create_render(
    request: Request,
    session_id: str,
    body: RenderRequest,
) -> Response:
    """Recolour the session's Wall Planes with their assigned Shades and return the PNG.

    Realistic mode tints each Shade by the colour of the light actually in the
    room (CONTEXT.md); True Colour shows the Shade as the colour chip. Every
    Wall Plane named in ``assignments`` is repainted independently — so two
    planes can carry two different Shades in one request (Accent Wall).
    All maths runs in linear RGB, including the per-plane alpha composites
    (issue #3 criterion 2), and the single encode happens at the end.
    """

    prepared = await require_photo(request, session_id)

    targets = _assignments(prepared, body.assignments)

    light_tint = estimate_light_tint(prepared.linear) if body.mode == "realistic" else _NEUTRAL_TINT

    # Build per-plane linear targets; the maths lives in render/ (conventions §3)
    plane_targets: list[tuple[np.ndarray, np.ndarray]] = []
    for plane, shade_code in targets:
        shade = _catalogue(request).find_by_code(shade_code)
        if shade is None:
            raise ServiceError(
                status_code=status.HTTP_404_NOT_FOUND,
                code=SHADE_NOT_FOUND,
                message=_MESSAGE_SHADE_NOT_FOUND,
            )
        target_shade = lab_to_linear_rgb(
            np.asarray([shade.lab.l, shade.lab.a, shade.lab.b], dtype=np.float64)
        )
        plane_targets.append((plane.alpha, target_shade))

    rendered = render_many(prepared.linear, plane_targets, light_tint)

    png_bytes = _encode_png(rendered)
    return Response(
        content=png_bytes,
        status_code=status.HTTP_201_CREATED,
        media_type="image/png",
        headers={
            "Content-Length": str(len(png_bytes)),
            # Recorded on every render per issue #8 — which mode produced
            # this PNG, so a reopened Consultation can show the same image
            # and the realism measurement (§10) can select true_colour.
            "X-SpectraPaint-Render-Mode": body.mode,
        },
    )


def _assignments(
    prepared: PreparedPhoto, assignments: dict[str, str]
) -> list[tuple[WallPlane, str]]:
    """Validate and resolve the per-plane assignments.

    Every key must name a Wall Plane this photo actually has, and at least one
    assignment must be present. A plane the photo does not have is a malformed
    request rather than a render of whatever was to hand (conventions.md §5).

    Returns the planes in the photo's stable order, paired with their Shade
    Codes, so an Accent Wall's two colours are applied deterministically.
    """

    if not assignments:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=MALFORMED_REQUEST,
            message=_MESSAGE_UNKNOWN_WALL_PLANE,
        )

    # Resolve, validating each plane id against this photo.
    # Preserve the photo's plane order for deterministic compositing.
    by_id: dict[str, WallPlane] = {p.plane_id: p for p in prepared.planes}
    for plane_id in assignments:
        if plane_id not in by_id:
            raise ServiceError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code=MALFORMED_REQUEST,
                message=_MESSAGE_UNKNOWN_WALL_PLANE,
            )

    ordered: list[tuple[WallPlane, str]] = []
    for plane in prepared.planes:
        if plane.plane_id in assignments:
            ordered.append((plane, assignments[plane.plane_id]))
    return ordered


def _encode_png(rendered: np.ndarray) -> bytes:
    """The uint8 RGB array as PNG bytes, sized for the Dealer's thumbnails.

    Saved without metadata (no EXIF): the photo's camera data is meaningless on
    a repaint, and stripping it keeps the payload small on the localhost pipe.
    """

    buffer = io.BytesIO()
    Image.fromarray(rendered, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()
