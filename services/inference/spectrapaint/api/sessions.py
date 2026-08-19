"""Session lifecycle: ``POST /sessions`` and ``DELETE /sessions/{id}``.

A photo enters the system only here, and the lifecycle is what every later endpoint hangs off.
No processing happens yet — no models, no segmentation. The service records the session and moves
on; the bytes are validated so a corrupt or unsupported file is caught at the door, then discarded.
Storage of the photo itself arrives with the segmentation tickets.

The registry is deliberately in-memory: persistence to disk is ticket #11's concern, and an
in-memory session dies with the process, which is correct for a single counter-side consultation.
"""

import io
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Request, UploadFile, status
from PIL import Image, UnidentifiedImageError

from spectrapaint.api.errors import (
    PHOTO_TOO_LARGE,
    SESSION_NOT_FOUND,
    UNSUPPORTED_IMAGE,
    ServiceError,
)

router = APIRouter()

# A deliberate bound, decided in docs/design-decisions.md §9 ("Upload size limit"): a phone photo
# of a room is a few MB, so 25 MB accommodates burst mode while capping the memory a single request
# can make the service hold. Revisit against real photos if the camera keeps surprising us.
MAX_UPLOAD_MB = 25
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

_MESSAGE_UNSUPPORTED_IMAGE = (
    "That file could not be read as a photo. Please choose a JPEG, PNG or WebP image."
)
# Derived from the limit itself, so retuning the cap cannot leave the message saying otherwise.
_MESSAGE_PHOTO_TOO_LARGE = f"That photo is too large. Please choose one under {MAX_UPLOAD_MB} MB."
_MESSAGE_SESSION_NOT_FOUND = "This consultation is no longer available. Please start a new one."


class SessionRegistry:
    """The live set of session ids. Nothing more yet — no metadata is needed until a later stage
    has something to attach to a session. No automatic deletion: a session leaves only when the
    Dealer ends the consultation, and only then do requests against it fail."""

    def __init__(self) -> None:
        self._sessions: set[str] = set()

    def create(self) -> str:
        session_id = uuid4().hex
        self._sessions.add(session_id)
        return session_id

    def delete(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        self._sessions.remove(session_id)
        return True


def _registry(request: Request) -> SessionRegistry:
    return request.app.state.session_registry


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    request: Request,
    photo: Annotated[UploadFile, File(description="A Room Photo as a JPEG, PNG or WebP image.")],
) -> dict[str, str]:
    """Accept a photo and return the session that now refers to it.

    The only way a photo enters the system. There is deliberately no endpoint that accepts an image
    alongside a Shade, so encode-once is enforced by omission — see docs/specs/v1-spectrapaint.md.
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

    session_id = _registry(request).create()
    return {"session_id": session_id}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(request: Request, session_id: str) -> None:
    """End a consultation. After this, every request against the session fails cleanly."""

    if not _registry(request).delete(session_id):
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=SESSION_NOT_FOUND,
            message=_MESSAGE_SESSION_NOT_FOUND,
        )


def _verify_is_an_image(contents: bytes) -> None:
    """Refuse anything that is not a photo we can work with, before it reaches a decoding stage.

    Pillow's ``verify()`` checks structure without decoding pixels. It reliably rejects a file that
    is not an image at all, and it catches a truncated PNG. It is weaker than it looks for JPEG:
    a JPEG with its EOI marker stripped passes ``verify()`` silently.

    So this is a gate, not a guarantee. Whichever stage first decodes the pixels must still handle
    its own decode errors — do not read a session id as proof that the bytes behind it are sound.
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
