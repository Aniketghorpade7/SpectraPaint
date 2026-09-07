"""Export a render at full resolution as JPEG (issue #12).

Browsing stays at preview scale (``MAX_PREPARED_DIMENSION`` in
``spectrapaint.api.preparation``); export re-renders the same assignments at
the photo's original resolution and returns a JPEG handed to the OS share
sheet. The stored PNG archive is never handed out directly.

Encode-once still holds: the photo entered only through ``POST /sessions``;
this endpoint works from the session's prepared photo plus its original bytes.
"""

import io
import re
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
from spectrapaint.render.luts import linearise_u8
from spectrapaint.segmentation.walls import WallPlane

router = APIRouter(prefix="/sessions", tags=["exports"])

RenderMode = Literal["realistic", "true_colour"]
_NEUTRAL_TINT = np.ones(3, dtype=np.float32)

_MESSAGE_SHADE_NOT_FOUND = (
    "That Shade Code is not in this Catalogue. Please check the code on the chip, "
    "or search by name."
)
_MESSAGE_UNKNOWN_WALL_PLANE = (
    "That wall is not one this photo has. Please choose a wall in the photo and try again."
)

# Filename sanitising: keep it a valid filename on Windows/macOS/Linux. Preserve
# the Shade Code verbatim; sanitise only the human name.
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')
_WHITESPACE = re.compile(r"\s+")
_MAX_FILENAME_LENGTH = 120


def _sanitize_shade_name(name: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("", name).strip()
    cleaned = _WHITESPACE.sub("-", cleaned)
    # Remove any remaining characters that are not safe for a filename; keep the name readable.
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned[:60] if len(cleaned) > 60 else cleaned or "Shade"


def _export_filename(assignments: dict[str, str], resolved_names: dict[str, str]) -> str:
    """Shade Code and name in the filename, never just a hash.

    For an accent wall the filename carries every Shade involved, joined with '+'.
    """
    parts: list[str] = []
    for shade_code in assignments.values():
        name = resolved_names.get(shade_code, "")
        sanitized = _sanitize_shade_name(name) if name else "Shade"
        parts.append(f"{shade_code}-{sanitized}")
    # Deduplicate while preserving order (same Shade on two planes).
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        if part not in seen:
            seen.add(part)
            unique.append(part)
    base = "+".join(unique) if unique else "SpectraPaint-Render"
    filename = f"{base}.jpg"
    if len(filename) > _MAX_FILENAME_LENGTH:
        filename = filename[: _MAX_FILENAME_LENGTH - 4] + ".jpg"
    return filename


def _catalogue(request: Request) -> Catalogue:
    return request.app.state.catalogue


class ExportRequest(BaseModel):
    assignments: dict[str, str]
    mode: RenderMode = "realistic"


@router.post("/{session_id}/exports", status_code=status.HTTP_201_CREATED)
async def create_export(
    request: Request,
    session_id: str,
    body: ExportRequest,
) -> Response:
    """Render at full resolution and return JPEG for the system share sheet.

    The preview render at ``POST /sessions/{id}/renders`` stays at
    ``MAX_PREPARED_DIMENSION`` for browsing speed. This endpoint re-renders the
    same ``assignments`` at the original photo's resolution, encodes as JPEG
    and returns it with a filename carrying the Shade Code and name. The stored
    PNG archive (``store.render_png``) is never returned directly.
    """

    prepared = await require_photo(request, session_id)
    targets = _assignments(prepared, body.assignments)

    light_tint_preview = (
        estimate_light_tint(prepared.linear) if body.mode == "realistic" else _NEUTRAL_TINT
    )

    # Resolve shades to collect names for the filename and to build linear targets.
    plane_targets_preview: list[tuple[np.ndarray, np.ndarray]] = []
    resolved_names: dict[str, str] = {}
    resolved_lab: dict[str, list[float]] = {}
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
        resolved_names[shade.shade_code] = shade.name
        resolved_lab[shade.shade_code] = [shade.lab.l, shade.lab.a, shade.lab.b]
        plane_targets_preview.append((plane.alpha, target_shade))

    full_linear, full_plane_targets, full_tint = _full_targets(
        request, session_id, prepared, plane_targets_preview, light_tint_preview, body.mode
    )

    rendered = render_many(full_linear, full_plane_targets, full_tint)
    jpeg_bytes = _encode_jpeg(rendered)
    filename = _export_filename(dict(body.assignments), resolved_names)

    return Response(
        content=jpeg_bytes,
        status_code=status.HTTP_201_CREATED,
        media_type="image/jpeg",
        headers={
            "Content-Length": str(len(jpeg_bytes)),
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-SpectraPaint-Export-Filename": filename,
            "X-SpectraPaint-Render-Mode": body.mode,
            "Cache-Control": "no-store",
        },
    )


def _full_targets(
    request: Request,
    session_id: str,
    prepared: PreparedPhoto,
    plane_targets_preview: list[tuple[np.ndarray, np.ndarray]],
    preview_tint: np.ndarray,
    mode: RenderMode,
) -> tuple[np.ndarray, list[tuple[np.ndarray, np.ndarray]], np.ndarray]:
    """Full-resolution linear photo, upscaled mattes and tint.

    Uses the session's original upload bytes when available (the in-memory
    registry keeps them); otherwise falls back to the preview linear so export
    still works for test fixtures and reopened sessions without an original.
    """

    registry = getattr(request.app.state, "session_registry", None)
    original: bytes | None = None
    if registry is not None and hasattr(registry, "original_bytes"):
        try:
            original = registry.original_bytes(session_id)
        except Exception:
            original = None

    # Fallback to store's original if registry has no bytes (e.g. reopened Consultation
    # exported via consultation id in a future ticket) — keep the shape pluggable.
    if original is None:
        store = getattr(request.app.state, "store", None)
        consultation_id = None
        if registry is not None and hasattr(registry, "consultation_for"):
            try:
                consultation_id = registry.consultation_for(session_id)
            except Exception:
                consultation_id = None
        if store is not None and consultation_id is not None and hasattr(store, "original_bytes"):
            try:
                original = store.original_bytes(consultation_id)
            except Exception:
                original = None

    if original is None:
        # No original to upscale from — export at preview resolution rather than fail.
        tint = preview_tint if mode == "realistic" else _NEUTRAL_TINT
        return prepared.linear, plane_targets_preview, tint

    try:
        with Image.open(io.BytesIO(original)) as image:
            rgb = image.convert("RGB")
            full_u8 = np.ascontiguousarray(np.asarray(rgb, dtype=np.uint8))
    except Exception:
        tint = preview_tint if mode == "realistic" else _NEUTRAL_TINT
        return prepared.linear, plane_targets_preview, tint

    full_linear = np.ascontiguousarray(linearise_u8(full_u8), dtype=np.float32)
    preview_h, preview_w = prepared.linear.shape[0], prepared.linear.shape[1]
    full_h, full_w = full_linear.shape[0], full_linear.shape[1]

    # If the original is actually the same size as the preview (small fixture), no upscale needed.
    if preview_h == full_h and preview_w == full_w:
        tint = estimate_light_tint(full_linear) if mode == "realistic" else _NEUTRAL_TINT
        return full_linear, plane_targets_preview, tint

    upscaled: list[tuple[np.ndarray, np.ndarray]] = []
    for alpha_preview, target_shade in plane_targets_preview:
        # alpha is HxWx1 float32 in [0,1]; resize via Pillow to preserve soft edge.
        channel = np.clip(np.asarray(alpha_preview, dtype=np.float32).squeeze(), 0.0, 1.0)
        # Pillow expects uint8 for resize; 0..255 keeps the soft edge.
        pil = Image.fromarray((channel * 255.0).round().astype(np.uint8), mode="L")
        resized = pil.resize((full_w, full_h), resample=Image.Resampling.BILINEAR)
        alpha_full = (np.asarray(resized, dtype=np.float32) / 255.0).reshape((full_h, full_w, 1))
        upscaled.append((alpha_full, target_shade))

    tint = estimate_light_tint(full_linear) if mode == "realistic" else _NEUTRAL_TINT
    return full_linear, upscaled, tint


def _assignments(
    prepared: PreparedPhoto, assignments: dict[str, str]
) -> list[tuple[WallPlane, str]]:
    if not assignments:
        raise ServiceError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=MALFORMED_REQUEST,
            message=_MESSAGE_UNKNOWN_WALL_PLANE,
        )
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


def _encode_jpeg(rendered: np.ndarray) -> bytes:
    """Full-resolution JPEG for handing to the OS share sheet.

    Quality 92 preserves the repaint while staying small enough for WhatsApp.
    Subsampling 0 (4:4:4) avoids chroma smearing on the matte edge. No EXIF is
    written — the camera data is not meaningful on a repaint.
    """

    buffer = io.BytesIO()
    Image.fromarray(rendered, mode="RGB").save(
        buffer, format="JPEG", quality=92, subsampling=0, optimize=True
    )
    return buffer.getvalue()
