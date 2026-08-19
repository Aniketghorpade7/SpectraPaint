"""Session lifecycle: ``POST /sessions``, ``GET /sessions/{id}/events`` and
``DELETE /sessions/{id}``.

A photo enters the system only here, and the lifecycle is what every later endpoint hangs off.
Uploading records the session and starts its preparation in the background — the bytes are
validated so a corrupt or unsupported file is caught at the door, and preparation is where the photo
is actually read (ticket #4). The render path (issue #3) consumes the prepared photo that same
preparation produces, so a render never touches the upload bytes.

The registry is deliberately in-memory: persistence to disk is ticket #11's concern, and an
in-memory session dies with the process, which is correct for a single counter-side consultation.
"""

import io
import json
from collections.abc import AsyncIterator, Callable
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from PIL import Image, UnidentifiedImageError

from spectrapaint.api.errors import (
    PHOTO_TOO_LARGE,
    SESSION_NOT_FOUND,
    UNSUPPORTED_IMAGE,
    ServiceError,
)
from spectrapaint.api.preparation import (
    MESSAGE_PREPARATION_FAILED,
    PreparationJob,
    PreparedPhoto,
    Stage,
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
    """The live set of sessions, each with its preparation running in the background.

    A session is its preparation job: upload creates both at once, and the photo's bytes live only
    inside that job's stages. No automatic deletion: a session leaves only when the Dealer ends the
    consultation, and only then do requests against it fail.
    """

    def __init__(self, preparation_stages: Callable[[bytes], list[Stage]]) -> None:
        self._preparation_stages = preparation_stages
        self._sessions: dict[str, PreparationJob] = {}

    def create(self, contents: bytes) -> str:
        session_id = uuid4().hex
        job = PreparationJob(self._preparation_stages(contents))
        self._sessions[session_id] = job
        # Started here so preparation genuinely begins on upload (docs/design-decisions.md §13) and
        # runs behind the Dealer's next move. The job's thread is daemonic and short-lived: a
        # session deleted mid-preparation abandons at most a few milliseconds of work.
        job.start()
        return session_id

    def job(self, session_id: str) -> PreparationJob | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        return True


def _registry(request: Request) -> SessionRegistry:
    return request.app.state.session_registry


async def require_photo(request: Request, session_id: str) -> PreparedPhoto:
    """The session's prepared photo, or a clean error.

    Waits for the session's background preparation to reach its terminal event, then returns the
    photo it produced. Public so the render endpoint shares the same message and response shape as
    every other session-scoped route.
    """

    job = _registry(request).job(session_id)
    if job is None:
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=SESSION_NOT_FOUND,
            message=_MESSAGE_SESSION_NOT_FOUND,
        )

    photo = await job.photo()
    if photo is None:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=UNSUPPORTED_IMAGE,
            message=MESSAGE_PREPARATION_FAILED,
        )
    return photo


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

    session_id = _registry(request).create(contents)
    return {"session_id": session_id}


@router.get("/sessions/{session_id}/events")
async def stream_events(request: Request, session_id: str) -> StreamingResponse:
    """The progress stream for one session's preparation.

    Server-sent events over plain HTTP: every progress event so far, then each new one as it lands,
    then exactly one terminal event (``done`` or ``failed``), after which the stream closes. A
    reader that connects after preparation finished still replays the whole log, so it never waits
    on an event already sent. Authenticated like everything else — by the secret header, never a
    query string, which is why this is a fetch-based stream rather than an ``EventSource``
    (docs/specs/v1-spectrapaint.md).
    """

    job = _registry(request).job(session_id)
    if job is None:
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=SESSION_NOT_FOUND,
            message=_MESSAGE_SESSION_NOT_FOUND,
        )

    return StreamingResponse(
        _sse_stream(job.stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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

    So this is a gate, not a guarantee. The preparation job's stage decodes the pixels right after
    it, so a file that slips past the gate is caught before anything downstream touches it.
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


async def _sse_stream(events: AsyncIterator[dict[str, str]]) -> AsyncIterator[str]:
    """Frame each event as a server-sent event. Data-only events; the payload is the JSON body."""

    async for event in events:
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
