"""Seam 1 — export at full resolution as JPEG (issue #12).

Every acceptance criterion here, in the order the issue lists it:
- Export triggers a full-resolution render (browsing stays at preview resolution)
- The exported file is a JPEG
- The filename carries the Shade Code and name
- The file is handed to the system share sheet, so WhatsApp/email/print all work
- The stored PNG archive is not handed out directly
- Export does not block the Dealer from continuing to browse
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from spectrapaint.api.app import create_app
from spectrapaint.api.preparation import MAX_PREPARED_DIMENSION
from spectrapaint.segmentation.walls import FIRST_WALL_PLANE_ID
from tests.api.conftest import stub_preparation_stages

SECRET = "test-secret-not-a-real-one"
ROOM_SIZE = (64, 64)
# Above MAX_PREPARED_DIMENSION (1280), so the browsing render is capped while the export —
# re-rendered from the original upload bytes — comes back at the photo's own size.
LARGE_ROOM_SIZE = (1600, 1200)


def png_of(rgb: tuple[int, int, int], size: tuple[int, int] = ROOM_SIZE) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, rgb).save(buffer, format="PNG")
    return buffer.getvalue()


def to_image(contents: bytes) -> Image.Image:
    return Image.open(io.BytesIO(contents))


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(SECRET, preparation_stages=stub_preparation_stages))


def auth(secret: str = SECRET) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def upload(client: TestClient, contents: bytes) -> str:
    response = client.post(
        "/sessions",
        headers=auth(),
        files={"photo": ("room.png", contents, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def export_jpeg(
    client: TestClient,
    session_id: str,
    shade_code: str = "PS-1001",
    mode: str = "realistic",
) -> object:
    return client.post(
        f"/sessions/{session_id}/exports",
        headers=auth(),
        json={"assignments": {FIRST_WALL_PLANE_ID: shade_code}, "mode": mode},
    )


def test_export_returns_a_jpeg(client: TestClient) -> None:
    session_id = upload(client, png_of((188, 188, 188)))

    response = export_jpeg(client, session_id)

    assert response.status_code == 201, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content[:2] == b"\xff\xd8"
    image = to_image(response.content)
    assert image.format == "JPEG"
    assert image.mode == "RGB"


def test_export_filename_carries_shade_code_and_name(client: TestClient) -> None:
    session_id = upload(client, png_of((188, 188, 188)))

    response = export_jpeg(client, session_id, shade_code="PS-1001")

    assert response.status_code == 201
    disposition = response.headers.get("content-disposition", "")
    exported_name = response.headers.get("x-spectrapaint-export-filename", "")
    combined = disposition + exported_name
    assert "PS-1001" in combined
    # Shade PS-1001 is "Morning Linen" in the stand-in catalogue.
    assert "Morning" in combined or "Linen" in combined


def test_export_does_not_return_the_png_archive(client: TestClient) -> None:
    """The stored PNG archive is not handed out directly — export re-renders as JPEG."""
    session_id = upload(client, png_of((188, 188, 188)))

    # Browsing render is PNG.
    render = client.post(
        f"/sessions/{session_id}/renders",
        headers=auth(),
        json={"assignments": {FIRST_WALL_PLANE_ID: "PS-1001"}, "mode": "realistic"},
    )
    assert render.status_code == 201
    assert render.headers["content-type"] == "image/png"

    exported = export_jpeg(client, session_id, shade_code="PS-1001")
    assert exported.status_code == 201
    assert exported.headers["content-type"] == "image/jpeg"
    assert exported.content != render.content
    assert not exported.content.startswith(b"\x89PNG")


def test_export_is_full_res_while_browsing_stays_preview(client: TestClient) -> None:
    """Export re-renders at the original resolution; the browsing render stays at preview.

    The fixture sits above MAX_PREPARED_DIMENSION, so this is direct evidence of the criterion:
    the browsing render comes back capped at the preview scale, while the export — re-rendered
    from the original upload bytes — comes back at the photo's own size.
    """

    session_id = upload(client, png_of((188, 188, 188), size=LARGE_ROOM_SIZE))

    render = client.post(
        f"/sessions/{session_id}/renders",
        headers=auth(),
        json={"assignments": {FIRST_WALL_PLANE_ID: "PS-1001"}, "mode": "realistic"},
    )
    exported = export_jpeg(client, session_id, shade_code="PS-1001")

    assert render.status_code == 201
    assert exported.status_code == 201
    # Export must be JPEG; browsing must stay PNG.
    assert render.headers["content-type"] == "image/png"
    assert exported.headers["content-type"] == "image/jpeg"

    render_image = to_image(render.content)
    export_image = to_image(exported.content)
    # Browsing is capped at the preview dimension; export is the photo's own resolution.
    assert max(render_image.size) == MAX_PREPARED_DIMENSION
    assert export_image.size == LARGE_ROOM_SIZE
    # Export carries the render mode and a filename, which the preview render does not.
    assert "x-spectrapaint-export-filename" in exported.headers
    assert exported.headers.get("x-spectrapaint-render-mode") == "realistic"


def test_export_is_non_blocking_for_browsing(client: TestClient) -> None:
    """Export does not block browsing — a render after an export still succeeds."""

    session_id = upload(client, png_of((188, 188, 188)))

    first_export = export_jpeg(client, session_id, shade_code="PS-1001")
    assert first_export.status_code == 201

    # Immediately browse with a different Shade — must succeed without waiting for export cleanup.
    second = client.post(
        f"/sessions/{session_id}/renders",
        headers=auth(),
        json={"assignments": {FIRST_WALL_PLANE_ID: "PS-1002"}, "mode": "realistic"},
    )
    assert second.status_code == 201
    assert second.headers["content-type"] == "image/png"

    third_export = export_jpeg(client, session_id, shade_code="PS-1002")
    assert third_export.status_code == 201
    assert third_export.headers["content-type"] == "image/jpeg"


def test_export_unknown_shade_is_404(client: TestClient) -> None:
    session_id = upload(client, png_of((188, 188, 188)))
    response = export_jpeg(client, session_id, shade_code="PS-9999")
    assert response.status_code == 404
    assert response.json()["code"] == "shade_not_found"


def test_export_requires_the_secret(client: TestClient) -> None:
    session_id = upload(client, png_of((188, 188, 188)))
    response = client.post(
        f"/sessions/{session_id}/exports",
        json={"assignments": {FIRST_WALL_PLANE_ID: "PS-1001"}, "mode": "realistic"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorised"


def test_export_for_unknown_session_fails_cleanly(client: TestClient) -> None:
    response = export_jpeg(client, "does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"
