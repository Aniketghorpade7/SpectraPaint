"""Render requests: ``POST /sessions/{session_id}/renders`` (issue #3).

Takes ``assignments`` — a Shade Code per Wall Plane, exactly the shape the spec
pins — and returns the repainted photo as PNG bytes. The photo itself never
appears in the request: it entered at upload (encode-once,
docs/specs/v1-spectrapaint.md), and this endpoint works from the session's
prepared photo — structure enforces the rule, not a comment.

The Shade is looked up in the live Catalogue (issue #5), so a render can only
ask for a Shade the Dealer can actually sell. Everything else here is a
deliberate stub pending the later tickets:

  * the wall is the stub rectangle matte (preparation._stub_wall_alpha)
  * the base colour and light tint are estimated from the photo's interior
    (engine), because the real wall-only estimate needs the segmentation mattes

There is one Wall Plane today, so ``assignments`` carries one entry, keyed by
the stub's id. The map is the contract rather than a bare ``shade_code`` because
an Accent Wall — two planes, two Shades, in one request — is what the shape
exists for (docs/specs/v1-spectrapaint.md), and a caller written against a
single-Shade body would have to be rewritten to gain it.

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
from spectrapaint.api.sessions import require_photo
from spectrapaint.catalogue import Catalogue
from spectrapaint.render.colour import lab_to_linear_rgb
from spectrapaint.render.engine import (
    estimate_base_colour,
    estimate_light_tint,
    light_map_of,
    render,
)

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

# The stub Wall Plane's id — the one key ``assignments`` accepts until the
# segmentation tickets produce real planes with real ids (preparation builds the
# matte it refers to). Named here so the tickets that replace it have one place
# to look, and so a caller assigning an unknown plane is refused rather than
# silently rendering something it did not ask for.
STUB_WALL_PLANE_ID = "wall_plane_1"

# True Colour mode shows the shade as the colour chip: the room's light colour
# is not applied, so the tint factor is neutral (1, 1, 1).
_NEUTRAL_TINT = np.ones(3, dtype=np.float32)


class RenderRequest(BaseModel):
    """A Shade Code per Wall Plane, and how to show the result.

    ``assignments`` maps a Wall Plane id to a Shade Code, which is the spec's
    shape and the reason an Accent Wall is expressible without changing this
    surface. Today the only key the service accepts is
    :data:`STUB_WALL_PLANE_ID`; the segmentation tickets widen the set of valid
    ids without touching the body.
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

    shade_code = _assigned_shade_code(body.assignments)

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

    base_colour = estimate_base_colour(prepared.linear)
    light_tint = estimate_light_tint(prepared.linear) if body.mode == "realistic" else _NEUTRAL_TINT

    light_map = light_map_of(prepared.linear, base_colour)
    rendered = render(
        prepared.linear,
        prepared.wall_alpha,
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


def _assigned_shade_code(assignments: dict[str, str]) -> str:
    """The Shade Code assigned to the stub Wall Plane.

    An empty map, or one naming a plane this photo does not have, is a malformed request rather
    than a render of whatever was to hand — a Dealer who assigned a Shade to the wrong plane must
    be told, not shown a picture that answers a different question (conventions.md §5).
    """

    if list(assignments) != [STUB_WALL_PLANE_ID]:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=MALFORMED_REQUEST,
            message=_MESSAGE_UNKNOWN_WALL_PLANE,
        )

    return assignments[STUB_WALL_PLANE_ID]


def _encode_png(rendered: np.ndarray) -> bytes:
    """The uint8 RGB array as PNG bytes, sized for the Dealer's thumbnails.

    Saved without metadata (no EXIF): the photo's camera data is meaningless on
    a repaint, and stripping it keeps the payload small on the localhost pipe.
    """

    buffer = io.BytesIO()
    Image.fromarray(rendered, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()
