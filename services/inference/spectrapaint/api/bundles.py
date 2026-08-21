"""The library over HTTP: Bundles, saved Consultations, and their Renders (issue #11).

    GET    /bundles                                          (the Dealer's jobs)
    POST   /bundles                       { name }
    PATCH  /bundles/{id}                  { name }           (rename)
    DELETE /bundles/{id}                                     (consultations move to the default)
    GET    /bundles/{id}/consultations                       (what is in the job)
    GET    /consultations/{id}/renders                       (every shade already tried)
    GET    /consultations/{id}/photo/png                     (the photo as prepared)
    GET    /consultations/{id}/renders/{render_id}/png       (the stored render, byte-for-byte)
    POST   /consultations/{id}/reopen                        (a live session, no preparation)

Two rules shape everything here:

* **Reopening replays, never regenerates.** The ``png`` endpoints serve exactly the bytes that were
  written when the work happened; nothing in this router calls the render engine.
* **Reopening skips preparation.** ``reopen`` rebuilds a live session from the photo and Alpha
  Mattes stored when preparation first ran, so trying another Shade starts immediately — the
  seconds-long pipeline does not run twice for one photo.
"""

import io

import numpy as np
from fastapi import APIRouter, Request, Response, status
from PIL import Image
from pydantic import BaseModel

from spectrapaint.api.errors import (
    BUNDLE_NOT_FOUND,
    CONSULTATION_NOT_FOUND,
    MALFORMED_REQUEST,
    PREPARATION_UNAVAILABLE,
    RENDER_NOT_FOUND,
    ServiceError,
)
from spectrapaint.api.preparation import PreparedPhoto
from spectrapaint.render.luts import linearise_u8
from spectrapaint.segmentation.walls import WallPlane

router = APIRouter(tags=["library"])

# A Bundle name is dealer-typed text at a counter. Bounded so a slip of the paste buffer cannot
# make a listing unusable; long enough that no real job name hits the cap.
MAX_BUNDLE_NAME_LENGTH = 80

_MESSAGE_BUNDLE_NOT_FOUND = "That bundle is not in your library."
_MESSAGE_CONSULTATION_NOT_FOUND = "That consultation is not in your library."
_MESSAGE_RENDER_NOT_FOUND = "That repaint is not in this consultation's history."
_MESSAGE_PREPARATION_UNAVAILABLE = (
    "This consultation was closed before its photo was ready, so it cannot be reopened. "
    "Its renders are still here."
)


class BundleCreate(BaseModel):
    name: str


def _store(request: Request):
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise ServiceError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="storage_unavailable",
            message="Saved consultations are unavailable in this service.",
        )
    return store


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > MAX_BUNDLE_NAME_LENGTH:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=MALFORMED_REQUEST,
            message="Please give the bundle a name of 1 to 80 characters.",
        )
    return cleaned


# -- bundles -------------------------------------------------------------------------------------


@router.get("/bundles")
async def list_bundles(request: Request) -> dict:
    return {"bundles": _store(request).list_bundles()}


@router.post("/bundles", status_code=status.HTTP_201_CREATED)
async def create_bundle(request: Request, body: BundleCreate) -> dict:
    return _store(request).create_bundle(_clean_name(body.name))


@router.patch("/bundles/{bundle_id}")
async def rename_bundle(request: Request, bundle_id: str, body: BundleCreate) -> dict:
    renamed = _store(request).rename_bundle(bundle_id, _clean_name(body.name))
    if not renamed:
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=BUNDLE_NOT_FOUND,
            message=_MESSAGE_BUNDLE_NOT_FOUND,
        )
    return {"bundle_id": bundle_id, "name": body.name.strip()}


@router.delete("/bundles/{bundle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bundle(request: Request, bundle_id: str) -> None:
    deleted = _store(request).delete_bundle(bundle_id)
    if not deleted:
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=BUNDLE_NOT_FOUND,
            message=_MESSAGE_BUNDLE_NOT_FOUND,
        )


@router.get("/bundles/{bundle_id}/consultations")
async def list_consultations(request: Request, bundle_id: str) -> dict:
    store = _store(request)
    if not store.require_bundle(bundle_id):
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=BUNDLE_NOT_FOUND,
            message=_MESSAGE_BUNDLE_NOT_FOUND,
        )
    return {"consultations": store.list_consultations(bundle_id)}


class ConsultationPlacement(BaseModel):
    consultation_id: str


@router.post("/bundles/{bundle_id}/consultations", status_code=status.HTTP_204_NO_CONTENT)
async def place_consultation(request: Request, bundle_id: str, body: ConsultationPlacement) -> None:
    """Put a Consultation into a Bundle — how a job's photos stay together."""

    store = _store(request)
    if not store.require_bundle(bundle_id):
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=BUNDLE_NOT_FOUND,
            message=_MESSAGE_BUNDLE_NOT_FOUND,
        )
    if not store.consultation_exists(body.consultation_id):
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=CONSULTATION_NOT_FOUND,
            message=_MESSAGE_CONSULTATION_NOT_FOUND,
        )
    store.place_consultation_in_bundle(body.consultation_id, bundle_id)


# -- consultations -------------------------------------------------------------------------------


@router.get("/consultations/{consultation_id}/renders")
async def list_renders(request: Request, consultation_id: str) -> dict:
    store = _store(request)
    if not store.consultation_exists(consultation_id):
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=CONSULTATION_NOT_FOUND,
            message=_MESSAGE_CONSULTATION_NOT_FOUND,
        )
    # Newest last, oldest first: the history reads in the order it was made.
    return {"renders": store.list_renders(consultation_id)}


@router.get("/consultations/{consultation_id}/photo/png")
async def consultation_photo(request: Request, consultation_id: str) -> Response:
    """The Consultation's photo exactly as preparation left it — the image a reopened
    Consultation puts on screen."""
    png = _require_preparation(_store(request), consultation_id)[0]
    return _png_response(png)


@router.get("/consultations/{consultation_id}/renders/{render_id}/png")
async def stored_render(request: Request, consultation_id: str, render_id: str) -> Response:
    """A stored render, byte-for-byte what the Dealer saw when it was made."""
    store = _store(request)
    if not store.consultation_exists(consultation_id):
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=CONSULTATION_NOT_FOUND,
            message=_MESSAGE_CONSULTATION_NOT_FOUND,
        )
    if store.render_consultation(render_id) != consultation_id:
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=RENDER_NOT_FOUND,
            message=_MESSAGE_RENDER_NOT_FOUND,
        )

    png = store.render_png(render_id)
    if png is None:
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=RENDER_NOT_FOUND,
            message=_MESSAGE_RENDER_NOT_FOUND,
        )
    return _png_response(png)


@router.post("/consultations/{consultation_id}/reopen", status_code=status.HTTP_201_CREATED)
async def reopen_consultation(request: Request, consultation_id: str) -> dict[str, str]:
    """Put a saved Consultation back on screen: a live session built from stored work.

    The photo and Alpha Mattes come off disk and straight into a completed session — no stage runs,
    no model loads, no waiting. A new Shade can be tapped immediately.
    """

    store = _store(request)
    stored = store.preparation_of(consultation_id)
    if stored is None:
        raise ServiceError(
            status_code=status.HTTP_409_CONFLICT,
            code=PREPARATION_UNAVAILABLE,
            message=_MESSAGE_PREPARATION_UNAVAILABLE,
        )

    photo_png, mattes = stored
    photo = _prepared_photo_from(photo_png, mattes)
    session_id = request.app.state.session_registry.restore(consultation_id, photo)
    return {"session_id": session_id}


# -- helpers -------------------------------------------------------------------------------------


def _require_preparation(store, consultation_id: str) -> tuple[bytes, list[tuple[str, bytes]]]:
    stored = store.preparation_of(consultation_id)
    if stored is None:
        if not store.consultation_exists(consultation_id):
            raise ServiceError(
                status_code=status.HTTP_404_NOT_FOUND,
                code=CONSULTATION_NOT_FOUND,
                message=_MESSAGE_CONSULTATION_NOT_FOUND,
            )
        raise ServiceError(
            status_code=status.HTTP_409_CONFLICT,
            code=PREPARATION_UNAVAILABLE,
            message=_MESSAGE_PREPARATION_UNAVAILABLE,
        )
    return stored


def _prepared_photo_from(photo_png: bytes, mattes: list[tuple[str, bytes]]) -> PreparedPhoto:
    """Rebuild the prepared photo from its stored images.

    This is the inverse of what sessions.py encodes: the photo decodes to the same sRGB array
    preparation produced, the linear form follows from it through the same LUT the decode stage
    uses, and each matte decodes back to its float Alpha. No model runs — which is the point.
    """

    with Image.open(io.BytesIO(photo_png)) as image:
        srgb = np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))

    planes = []
    for plane_id, matte_png in mattes:
        with Image.open(io.BytesIO(matte_png)) as image:
            channel = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
        planes.append(WallPlane(plane_id=plane_id, alpha=channel.reshape((*channel.shape, 1))))

    return PreparedPhoto(
        linear=np.ascontiguousarray(linearise_u8(srgb), dtype=np.float32),
        srgb=srgb,
        planes=tuple(planes),
    )


def _png_response(png: bytes) -> Response:
    return Response(content=png, media_type="image/png", headers={"Content-Length": str(len(png))})
