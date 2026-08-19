"""Session lifecycle: ``POST /sessions`` and ``DELETE /sessions/{id}``.

A photo enters the system only here, and the lifecycle is what every later endpoint hangs off.
Since issue #3, the upload also does the once-per-photo preparation the render path needs: the
photo is decoded, linearised through the 256-entry LUT (encode-once, per the
spec in docs/specs/v1-spectrapaint.md),
and the stub Wall Plane matte is built for it. A render request therefore never re-encodes -- the
structure of the contract enforces it, not a rule in the code.

The registry is deliberately in-memory: persistence to disk is ticket #11's concern, and an
in-memory session dies with the process, which is correct for a single counter-side consultation.
"""

import io
from dataclasses import dataclass
from typing import Annotated
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, File, Request, UploadFile, status
from PIL import Image, UnidentifiedImageError

from spectrapaint.api.errors import (
    PHOTO_TOO_LARGE,
    SESSION_NOT_FOUND,
    UNSUPPORTED_IMAGE,
    ServiceError,
)
from spectrapaint.render.luts import linearise_u8

router = APIRouter()

# A deliberate bound, decided in docs/design-decisions.md S9 ("Upload size limit"): a phone photo
# of a room is a few MB, so 25 MB accommodates burst mode while capping the memory a single request
# can make the service hold. Revisit against real photos if the camera keeps surprising us.
MAX_UPLOAD_MB = 25
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# The prepared photo is capped on its long side so the in-memory working image stays at preview
# scale (~1.3 MP) -- docs/specs/v1-spectrapaint.md Performance: full-resolution renders are a later
# ticket; the ~1 MP preview is the per-tap path while browsing. 1280 px at 16:9 is ~0.9 MP.
MAX_PREPARED_DIMENSION = 1280

_MESSAGE_UNSUPPORTED_IMAGE = (
    "That file could not be read as a photo. Please choose a JPEG, PNG or WebP image."
)
# Derived from the limit itself, so retuning the cap cannot leave the message saying otherwise.
_MESSAGE_PHOTO_TOO_LARGE = f"That photo is too large. Please choose one under {MAX_UPLOAD_MB} MB."
# Public: the render endpoint shares this message with the session endpoints.
MESSAGE_SESSION_NOT_FOUND = "This consultation is no longer available. Please start a new one."

# Stub Wall Plane geometry, decided in docs/design-decisions.md S14: a centred rectangle covering
# 60% x 55% of the photo, with a soft edge band. The segmentation tickets replace the rectangle;
# the shape of the alpha map (HxWx1 float [0, 1]) is the contract that stays.
_STUB_WIDTH_FRACTION = 0.60
_STUB_HEIGHT_FRACTION = 0.55
_STUB_SOFT_BAND_FRACTION = 0.03


@dataclass(frozen=True)
class PreparedPhoto:
    """The once-per-photo work the render path consumes (issue #3's encode-once rule)."""

    linear: np.ndarray  # HxWx3 float32, linear RGB at preview scale
    wall_alpha: np.ndarray  # HxWx1 float32, the stub Wall Plane matte in [0, 1]


class SessionRegistry:
    """The live sessions, each with its prepared photo.

    No automatic deletion: a session leaves only when the Dealer ends the consultation, and only
    then do requests against it fail.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, PreparedPhoto] = {}

    def create(self, photo: PreparedPhoto) -> str:
        session_id = uuid4().hex
        self._sessions[session_id] = photo
        return session_id

    def delete(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        return True

    def photo(self, session_id: str) -> PreparedPhoto | None:
        return self._sessions.get(session_id)


def _registry(request: Request) -> SessionRegistry:
    return request.app.state.session_registry


def require_photo(request: Request, session_id: str) -> PreparedPhoto:
    """The prepared photo for a session, or the one not-found error.

    Public so the render endpoint shares the same message and response shape as every other
    session-scoped route.
    """

    photo = _registry(request).photo(session_id)
    if photo is None:
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=SESSION_NOT_FOUND,
            message=MESSAGE_SESSION_NOT_FOUND,
        )
    return photo


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    request: Request,
    photo: Annotated[UploadFile, File(description="A Room Photo as a JPEG, PNG or WebP image.")],
) -> dict[str, str]:
    """Accept a photo and return the session that now refers to it.

    The only way a photo enters the system. There is deliberately no endpoint that accepts an image
    alongside a Shade, so encode-once is enforced by omission -- see docs/specs/v1-spectrapaint.md.
    """

    contents = await photo.read()
    if not contents:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=UNSUPPORTED_IMAGE,
            message=_MESSAGE_UNSUPPORTED_IMAGE,
        )
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ServiceError(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            code=PHOTO_TOO_LARGE,
            message=_MESSAGE_PHOTO_TOO_LARGE,
        )

    _verify_is_an_image(contents)

    session_id = _registry(request).create(_prepare(contents))
    return {"session_id": session_id}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(request: Request, session_id: str) -> None:
    """End a consultation. After this, every request against the session fails cleanly."""

    if not _registry(request).delete(session_id):
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=SESSION_NOT_FOUND,
            message=MESSAGE_SESSION_NOT_FOUND,
        )


def _prepare(contents: bytes) -> PreparedPhoto:
    """Decode, downscale to preview scale, linearise, and build the stub wall matte.

    This is the once-per-photo preparation; the render path never repeats it. Downscaling happens
    before linearisation so the LUT input is the actual working pixel data, exactly as the
    preview-sized render will consume it.
    """

    with Image.open(io.BytesIO(contents)) as image:
        rgb = image.convert("RGB")
        if max(rgb.size) > MAX_PREPARED_DIMENSION:
            scale = MAX_PREPARED_DIMENSION / max(rgb.size)
            rgb = rgb.resize(
                (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))),
                resample=Image.Resampling.LANCZOS,
            )
        photo_u8 = np.asarray(rgb, dtype=np.uint8)

    linear = np.ascontiguousarray(linearise_u8(photo_u8), dtype=np.float32)
    return PreparedPhoto(linear=linear, wall_alpha=_stub_wall_alpha(linear.shape[:2]))


def _stub_wall_alpha(shape: tuple[int, int]) -> np.ndarray:
    """The stub Wall Plane matte: a centred, soft-edged rectangle in [0, 1].

    Replaced by the real segmentation mattes; its shape is the contract that stays. Edge band is
    a linear ramp so the alpha composite stays clean in linear space (issue #3 criterion 2).
    """

    height, width = shape
    rect_w = max(1, round(width * _STUB_WIDTH_FRACTION))
    rect_h = max(1, round(height * _STUB_HEIGHT_FRACTION))
    band = max(1, round(min(width, height) * _STUB_SOFT_BAND_FRACTION))

    left = (width - rect_w) // 2
    right = left + rect_w
    top = (height - rect_h) // 2
    bottom = top + rect_h

    x = np.arange(width, dtype=np.float32)
    y = np.arange(height, dtype=np.float32)

    # Distance to the rectangle edge, in pixels, positive inside. Then alpha ramps from 0 at
    # ``edge - band`` to 1 at ``edge``, and is fully 1 in the interior.
    from_left = np.minimum(np.minimum(x[None, :] - left, right - x[None, :]), band) / band
    from_top = np.minimum(np.minimum(y[:, None] - top, bottom - y[:, None]), band) / band
    return np.clip(np.minimum(from_left, from_top), 0.0, 1.0)[..., None].astype(np.float32)


def _verify_is_an_image(contents: bytes) -> None:
    """Refuse anything that is not a photo we can work with, before it reaches a decoding stage.

    Pillow's ``verify()`` checks structure without decoding pixels. It reliably rejects a file that
    is not an image at all, and it catches a truncated PNG. It is weaker than it looks for JPEG:
    a JPEG with its EOI marker stripped passes ``verify()`` silently.

    So this is a gate, not a guarantee. ``_prepare`` decodes the pixels right after it, so a file
    that slips past the gate is caught before anything downstream touches it.
    """

    try:
        image = Image.open(io.BytesIO(contents))
        image.verify()
    except Image.DecompressionBombError:
        # A small file that decodes to enormous dimensions (Pillow's bomb guard). Refuse it here,
        # or a later stage would try to hold that much memory.
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=UNSUPPORTED_IMAGE,
            message=("That photo is too large to be processed. Please choose a smaller one."),
        ) from None
    except (UnidentifiedImageError, OSError):
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=UNSUPPORTED_IMAGE,
            message=_MESSAGE_UNSUPPORTED_IMAGE,
        ) from None