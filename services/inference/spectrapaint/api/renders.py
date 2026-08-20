"""Render requests: ``POST /sessions/{session_id}/renders`` (issue #3).

Takes ``assignments`` — a Shade Code per Wall Plane, exactly the shape the spec
pins — and returns the repainted photo as PNG bytes. The photo itself never
appears in the request: it entered at upload (encode-once,
docs/specs/v1-spectrapaint.md), and this endpoint works from the session's
prepared photo — structure enforces the rule, not a comment.

The Shade is looked up in the live Catalogue (issue #5), so a render can only
ask for a Shade the Dealer can actually sell.

The wall is now the real thing (ticket #6): the Wall Plane matte the
segmentation pipeline found while the photo was being prepared, and a Base
Colour measured from inside that matte rather than from the whole frame. The
stub rectangle and the interior-median estimate are both gone.

There is still one Wall Plane per photo, so ``assignments`` carries one entry —
but it is keyed by the id of a plane this photo actually has, and an id the
photo does not have is refused. The map is the contract rather than a bare
``shade_code`` because an Accent Wall — two planes, two Shades, in one request —
is what the shape exists for (docs/specs/v1-spectrapaint.md), and a caller
written against a single-Shade body would have to be rewritten to gain it.
Ticket #7 fills the map with more keys without touching this surface.

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
from spectrapaint.render.engine import (
    estimate_base_colour,
    estimate_light_tint,
    light_map_of,
    render,
)
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
    """Recolour the session's Wall Plane with its assigned Shade and return the PNG.

    Realistic mode tints the shade by the colour of the light actually in the
    room (CONTEXT.md); True Colour shows the shade as the colour chip, so the
    room's light colour is not applied. The composite and the scene estimates
    all run in linear RGB; the single encode happens at the end (issue #3
    criterion 2).
    """

    prepared = await require_photo(request, session_id)

    plane, shade_code = _assignment(prepared, body.assignments)

    shade = _catalogue(request).find_by_code(shade_code)
    if shade is None:
        # 404, the same status the Catalogue's own lookup returns for the same code: one
        # machine-readable code must not mean two different things to a caller.
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=SHADE_NOT_FOUND,
            message=_MESSAGE_SHADE_NOT_FOUND,
        )

    target_shade = lab_to_linear_rgb(
        np.asarray([shade.lab.l, shade.lab.a, shade.lab.b], dtype=np.float64)
    )

    # Measured inside this plane's matte, not across the photo: the Base Colour
    # is the paint currently on *this wall*, and the frame is mostly other
    # things (ticket #6).
    base_colour = estimate_base_colour(prepared.linear, plane.alpha)
    light_tint = estimate_light_tint(prepared.linear) if body.mode == "realistic" else _NEUTRAL_TINT

    light_map = light_map_of(prepared.linear, base_colour)
    rendered = render(
        prepared.linear,
        plane.alpha,
        light_map,
        target_shade,
        light_tint,
    )

    png_bytes = _encode_png(rendered)
    return Response(
        content=png_bytes,
        status_code=status.HTTP_201_CREATED,
        media_type="image/png",
        headers={"Content-Length": str(len(png_bytes))},
    )


def _assignment(prepared: PreparedPhoto, assignments: dict[str, str]) -> tuple[WallPlane, str]:
    """The Wall Plane to repaint and the Shade Code to repaint it in.

    An empty map, or one naming a plane this photo does not have, is a malformed request rather
    than a render of whatever was to hand — a Dealer who assigned a Shade to the wrong plane must
    be told, not shown a picture that answers a different question (conventions.md §5).

    One plane per photo today, so one entry. The check is against the plane ids *this photo* has,
    not against a constant, which is what makes it keep working when #7 finds three of them.
    """

    if len(assignments) != 1:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=MALFORMED_REQUEST,
            message=_MESSAGE_UNKNOWN_WALL_PLANE,
        )

    ((plane_id, shade_code),) = assignments.items()
    plane = prepared.plane(plane_id)
    if plane is None:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=MALFORMED_REQUEST,
            message=_MESSAGE_UNKNOWN_WALL_PLANE,
        )
    return plane, shade_code


def _encode_png(rendered: np.ndarray) -> bytes:
    """The uint8 RGB array as PNG bytes, sized for the Dealer's thumbnails.

    Saved without metadata (no EXIF): the photo's camera data is meaningless on
    a repaint, and stripping it keeps the payload small on the localhost pipe.
    """

    buffer = io.BytesIO()
    Image.fromarray(rendered, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()
