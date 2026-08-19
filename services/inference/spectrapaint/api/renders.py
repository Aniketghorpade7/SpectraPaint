"""Render requests: ``POST /sessions/{session_id}/renders`` (issue #3).

Takes an assignment of one shade to one plane (the stub Wall Plane) and returns
the repainted photo as PNG bytes. The photo itself never appears in the request:
it entered at upload (encode-once, docs/specs/v1-spectrapaint.md), and this
endpoint works from the session's prepared photo -- structure enforces the rule,
not a comment.

Everything here is a deliberate stub pending the later tickets:
  * the wall is the stub rectangle matte (sessions._stub_wall_alpha)
  * the base colour and light tint are whole-photo interior medians (engine)
  * the shade catalogue is a three-entry stand-in (the Catalogue service is a
    later ticket; the ST- prefix is the trade deck id space, and Lab is the
    stored colour space per the spec's colour-management table)

What is not a stub is the contract: assignments, mode semantics
(realistic = tinted by the room's light, true_colour = as the chip), the error
shape, and PNG output. The segmentation and catalogue tickets swap internals;
they must not change this surface.
"""

import io
from typing import Literal

import numpy as np
from fastapi import APIRouter, Request, Response, status
from PIL import Image
from pydantic import BaseModel

from spectrapaint.api.errors import SHADE_NOT_FOUND, ServiceError
from spectrapaint.api.sessions import require_photo
from spectrapaint.render.colour import lab_to_linear_rgb
from spectrapaint.render.engine import (
    estimate_base_colour,
    estimate_light_tint,
    light_map_of,
    render,
)

router = APIRouter(prefix="/sessions", tags=["renders"])

_MESSAGE_SHADE_NOT_FOUND = (
    "That shade is not in the current colour range. Please choose another from the range."
)

# The stand-in shade catalogue: ``shade id -> CIELAB (L*, a*, b*)`` under D65, 2
# degree observer, exactly the stored colour space the spec pins. Three entries
# are enough to exercise the contract; the Catalogue service replaces this dict.
STAND_IN_SHADES: dict[str, tuple[float, float, float]] = {
    "ST-101": (92.9, 0.4, 2.5),  # Gentle White
    "ST-204": (81.2, 2.8, 9.6),  # Soft Fawn
    "ST-318": (72.4, -6.1, 8.3),  # Sage
}

# The one rendering mode vocabulary. Literal keeps a misspelled mode a clear
# client error (422 malformed_request) instead of a silent default.
RenderMode = Literal["realistic", "true_colour"]


class RenderRequest(BaseModel):
    """The assignment of one shade to the Wall Plane, and how to show it.

    One plane per request for now -- there is exactly one plane (the stub). The
    multi-plane assignments shape arrives with the segmentation tickets, which
    is when this body gains a map of plane -> shade.
    """

    shade_id: str
    mode: RenderMode = "realistic"


@router.post("/{session_id}/renders", status_code=status.HTTP_201_CREATED)
async def create_render(
    request: Request,
    session_id: str,
    body: RenderRequest,
) -> Response:
    """Recolour the session's wall with the shade and return the PNG.

    Realistic mode tints the shade by the colour of the light actually in the
    room (CONTEXT.md); True Colour shows the shade as the colour chip, so the
    room's light colour is not applied. The composite and the scene estimates
    all run in linear RGB; the single encode happens at the end (issue #3
    criterion 2).
    """

    prepared = require_photo(request, session_id)

    shade_lab = _shade_lab(body.shade_id)
    if shade_lab is None:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=SHADE_NOT_FOUND,
            message=_MESSAGE_SHADE_NOT_FOUND,
        )

    base_colour = estimate_base_colour(prepared.linear)
    light_tint = (
        estimate_light_tint(prepared.linear) if body.mode == "realistic" else _NEUTRAL_TINT
    )
    target_shade = lab_to_linear_rgb(np.asarray(shade_lab, dtype=np.float64))

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


_NEUTRAL_TINT = np.ones(3, dtype=np.float32)


def _shade_lab(shade_id: str) -> tuple[float, float, float] | None:
    """The Lab values for a shade id, or None if it is not in the range.

    Accepts the bare code or the ``ST-`` prefixed form the UI is expected to
    send -- normalising here keeps the wire contract forgiving without naming
    the Catalogue's own lookup conventions.
    """

    lookup = shade_id if shade_id.startswith("ST-") else f"ST-{shade_id}"
    return STAND_IN_SHADES.get(lookup)


def _encode_png(rendered: np.ndarray) -> bytes:
    """The uint8 RGB array as PNG bytes, sized for the Dealer's thumbnails.

    Saved without metadata (no EXIF): the photo's camera data is meaningless on
    a repaint, and stripping it keeps the payload small on the localhost pipe.
    """

    buffer = io.BytesIO()
    Image.fromarray(rendered, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()