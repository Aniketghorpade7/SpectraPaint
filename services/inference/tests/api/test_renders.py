"""Seam 1 — the render request over the REST contract (issue #3).

Behaviour, never implementation (docs/conventions.md §6): statuses, content type,
mode semantics and the error shape are contract; how the render is produced is
not. A solid-colour room stands in for the photo, and preparation comes from
tests/api/conftest.py rather than from the models: the matte then has a
fully-interior region where the repaint must actually show up, which is what
lets the mode tests assert *rendered* behaviour rather than structure. The same
contract against the real pipeline is the slow lane's job — see
tests/api/test_walls.py.
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from spectrapaint.api.app import create_app
from spectrapaint.segmentation.walls import FIRST_WALL_PLANE_ID
from tests.api.conftest import stub_preparation_stages

SECRET = "test-secret-not-a-real-one"

# A solid sRGB room. Neutral grey (188, 188, 188) makes the "wall was repainted"
# assertion exact: a painted pixel must no longer be that grey. Warm white
# (255, 222, 193) gives the mode test a room whose light is visibly warm.
NEUTRAL_ROOM_SRGB = (188, 188, 188)
WARM_ROOM_SRGB = (255, 222, 193)
ROOM_SIZE = (64, 64)


def png_of(rgb: tuple[int, int, int], size: tuple[int, int] = ROOM_SIZE) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, rgb).save(buffer, format="PNG")
    return buffer.getvalue()


def to_png(contents: bytes) -> Image.Image:
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
    assert response.status_code == 201
    return response.json()["session_id"]


def render(
    client: TestClient,
    session_id: str,
    shade_code: str = "PS-1001",
    mode: str = "realistic",
) -> object:
    return client.post(
        f"/sessions/{session_id}/renders",
        headers=auth(),
        json={"assignments": {FIRST_WALL_PLANE_ID: shade_code}, "mode": mode},
    )


def test_render_returns_a_png_the_size_of_the_photo(client: TestClient) -> None:
    session_id = upload(client, png_of(NEUTRAL_ROOM_SRGB))

    response = render(client, session_id)

    assert response.status_code == 201
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    image = to_png(response.content)
    assert image.mode == "RGB"
    assert image.size == ROOM_SIZE


def test_the_wall_pixels_are_repainted(client: TestClient) -> None:
    """The stub end-to-end: the photo in, a repaint out, the wall visibly changed."""

    session_id = upload(client, png_of(NEUTRAL_ROOM_SRGB))

    response = render(client, session_id, shade_code="PS-1001")

    assert response.status_code == 201
    centre = to_png(response.content).getpixel((ROOM_SIZE[0] // 2, ROOM_SIZE[1] // 2))
    # The wall region (alpha=1 interior) must no longer be the original neutral grey.
    assert centre != NEUTRAL_ROOM_SRGB


def test_realistic_tints_the_shade_by_the_room_light(
    client: TestClient,
) -> None:
    """The mode semantics: realistic applies the room's light colour, true_colour does not.

    On a warm-lit room the same shade renders differently in the two modes --
    not by accident but because the realistic composite multiplies the shade by
    the light tint (CONTEXT.md). The two PNGs must differ.
    """

    session_id = upload(client, png_of(WARM_ROOM_SRGB))

    realistic = render(client, session_id, mode="realistic").content
    true_colour = render(client, session_id, mode="true_colour").content

    assert realistic != true_colour


def test_unknown_shade_is_a_clean_404(client: TestClient) -> None:
    """The same status the Catalogue's own lookup gives for the same code.

    One machine-readable code meaning 422 here and 404 there would leave a caller unable to treat
    ``shade_not_found`` as one thing.
    """
    session_id = upload(client, png_of(NEUTRAL_ROOM_SRGB))

    response = render(client, session_id, shade_code="PS-9999")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "shade_not_found"
    assert body["message"]

    direct = client.get("/catalogue/shades/PS-9999", headers=auth())
    assert direct.status_code == response.status_code
    assert direct.json()["code"] == body["code"]


def test_a_shade_assigned_to_a_wall_the_photo_does_not_have_is_refused(
    client: TestClient,
) -> None:
    """A render of the wrong wall answers a question the Dealer did not ask.

    Refused rather than rendered, because nothing in a returned PNG would reveal that the
    assignment was ignored (conventions.md §5).
    """
    session_id = upload(client, png_of(NEUTRAL_ROOM_SRGB))

    response = client.post(
        f"/sessions/{session_id}/renders",
        headers=auth(),
        json={"assignments": {"wall_plane_47": "PS-1001"}, "mode": "realistic"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "malformed_request"
    assert response.json()["message"]


def test_an_empty_assignment_is_refused(client: TestClient) -> None:
    session_id = upload(client, png_of(NEUTRAL_ROOM_SRGB))

    response = client.post(
        f"/sessions/{session_id}/renders",
        headers=auth(),
        json={"assignments": {}, "mode": "realistic"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "malformed_request"


def test_a_photo_that_failed_preparation_cannot_be_rendered(client: TestClient) -> None:
    """A JPEG whose end-of-image marker is stripped passes the upload gate but not the decode.

    The render must say so in the contract's error shape rather than raising — before this was
    pinned, the uncaught decode error surfaced as a bare 500 with nothing the Dealer could act on.
    """
    buffer = io.BytesIO()
    Image.new("RGB", ROOM_SIZE, NEUTRAL_ROOM_SRGB).save(buffer, "JPEG")
    truncated = buffer.getvalue()[:-2]

    upload_response = client.post(
        "/sessions",
        headers=auth(),
        files={"photo": ("room.jpg", truncated, "image/jpeg")},
    )
    assert upload_response.status_code == 201

    response = render(client, upload_response.json()["session_id"])

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "unsupported_image"
    assert body["message"]


def test_an_unknown_mode_is_a_malformed_request(client: TestClient) -> None:
    session_id = upload(client, png_of(NEUTRAL_ROOM_SRGB))

    response = client.post(
        f"/sessions/{session_id}/renders",
        headers=auth(),
        json={"assignments": {FIRST_WALL_PLANE_ID: "PS-1001"}, "mode": "photorealistic"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "malformed_request"


def test_render_for_an_unknown_session_fails_cleanly(client: TestClient) -> None:
    response = render(client, "does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"


def test_render_requires_the_secret(client: TestClient) -> None:
    session_id = upload(client, png_of(NEUTRAL_ROOM_SRGB))

    response = client.post(
        f"/sessions/{session_id}/renders",
        json={"assignments": {FIRST_WALL_PLANE_ID: "PS-1001"}, "mode": "realistic"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorised"
