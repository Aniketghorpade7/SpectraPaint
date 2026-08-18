"""Session lifecycle: ``POST /sessions`` and ``DELETE /sessions/{id}``.

A photo enters the system only here, and the lifecycle is what every later endpoint hangs off.
No processing happens yet — no models, no segmentation. The service records the session and moves
on; the bytes are validated so a corrupt or unsupported file is caught at the door, then discarded.
Storage of the photo itself arrives with the segmentation tickets.

The registry is deliberately in-memory: persistence to disk is ticket #11's concern, and an
in-memory session dies with the process, which is correct for a single counter-side consultation.
"""

import io
from dataclasses import dataclass
from datetime import UTC, datetime
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

# Tuned in the same spirit as every other threshold in this project: a plausible starting value,
# revisit against real photographs (docs/design-decisions.md §12). Room photos from a phone camera
# rarely exceed a few MB; 25 MB allows even a burst-mode shot while capping the memory a single
# request can make the service hold.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_MESSAGE_UNSUPPORTED_IMAGE = (
    "That file could not be read as a photo. Please choose a JPEG, PNG or WebP image."
)
_MESSAGE_PHOTO_TOO_LARGE = "That photo is too large. Please choose one under 25 MB."
_MESSAGE_SESSION_NOT_FOUND = "This consultation is no longer available. Please start a new one."


@dataclass
class Session:
    """What the service knows about one loaded photo. Metadata only — the photo itself is handled
    by whichever stage needs its pixels."""

    id: str
    created_at: datetime
    original_name: str
    content_type: str
    size_bytes: int


class SessionRegistry:
    """The live set of sessions. No automatic deletion: a session leaves only when the Dealer ends
    the consultation, and only then do requests against it fail."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, *, original_name: str, content_type: str, size_bytes: int) -> str:
        session = Session(
            id=uuid4().hex,
            created_at=datetime.now(UTC),
            original_name=original_name,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        self._sessions[session.id] = session
        return session.id

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None


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

    session_id = _registry(request).create(
        original_name=photo.filename or "",
        content_type=photo.content_type or "",
        size_bytes=len(contents),
    )
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
    """Decode enough of the file to prove it is a real, non-corrupt photo.

    Pillow's ``verify()`` reads through the file and raises on truncated or malformed images, which
    is the "corrupt file produces a clear message rather than a crash" criterion — a magic-byte
    check alone would let a truncated JPEG with a valid header through to the first stage that
    decodes it.
    """

    try:
        image = Image.open(io.BytesIO(contents))
        image.verify()
    except (UnidentifiedImageError, OSError):
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=UNSUPPORTED_IMAGE,
            message=_MESSAGE_UNSUPPORTED_IMAGE,
        ) from None
