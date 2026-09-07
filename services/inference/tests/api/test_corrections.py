"""Seam 1 — correcting the detected Wall Planes by tapping (ticket #10).

Split and Merge need no model at all: a hard partition means every Wall Plane's matte is already
disjoint from every other's (segmentation/split.py), so both are plain array operations
(implementation-decisions.md #39, segmentation/corrections.py) — fully covered here, in the fast
lane, against the same stub planes tests/api/test_renders.py already uses.

Add's own decode genuinely needs SAM 2, so only what runs *before* any model call — a tap that is
already covered, a tap outside the photo — is covered here. The decode itself, against a real
fixture, is exercised in the slow lane by tests/api/test_walls.py, on the same model conventions.md
§6 draws for the automatic pipeline: do not mock the model adapters.
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from spectrapaint.api.app import create_app
from tests.api.conftest import (
    STUB_HEIGHT_FRACTION,
    STUB_SOFT_BAND_FRACTION,
    STUB_WIDTH_FRACTION,
    stub_preparation_stages,
    two_plane_preparation_stages,
)

SECRET = "test-secret-not-a-real-one"
ROOM_SIZE = (300, 200)  # width, height — big enough that MINIMUM_WALL_FRACTION splits meaningfully


def png_of(size: tuple[int, int] = ROOM_SIZE, rgb: tuple[int, int, int] = (188, 188, 188)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, rgb).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(SECRET, preparation_stages=stub_preparation_stages))


@pytest.fixture
def two_plane_client() -> TestClient:
    """A session whose photo already has two Wall Planes, for the Merge tests."""
    return TestClient(create_app(SECRET, preparation_stages=two_plane_preparation_stages))


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {SECRET}"}


def upload(client: TestClient) -> str:
    response = client.post(
        "/sessions", headers=auth(), files={"photo": ("room.png", png_of(), "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def planes_of(client: TestClient, session_id: str) -> list[dict]:
    return client.get(f"/sessions/{session_id}/planes", headers=auth()).json()["planes"]


# The stub rectangle's own geometry (tests/api/conftest.rectangular_matte), derived from the same
# constants the fixture is built from rather than guessed, so a retuned stub cannot silently make
# these expectations wrong.
_WIDTH, _HEIGHT = ROOM_SIZE
_RECT_W = round(_WIDTH * STUB_WIDTH_FRACTION)
_RECT_H = round(_HEIGHT * STUB_HEIGHT_FRACTION)
_RECT_LEFT = (_WIDTH - _RECT_W) // 2
_RECT_TOP = (_HEIGHT - _RECT_H) // 2
_RECT_BAND = max(1, round(min(_WIDTH, _HEIGHT) * STUB_SOFT_BAND_FRACTION))
_RECT_CENTRE_Y = _RECT_TOP + _RECT_H // 2
_RECT_CENTRE_X = _RECT_LEFT + _RECT_W // 2


# --- Add: what can be checked without a model --------------------------------------------------


def test_add_refuses_a_point_already_covered_by_an_existing_plane(client: TestClient) -> None:
    session_id = upload(client)

    response = client.post(
        f"/sessions/{session_id}/planes",
        headers=auth(),
        json={"x": _RECT_CENTRE_X, "y": _RECT_CENTRE_Y},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "malformed_request"
    assert "split" in body["message"].lower()


@pytest.mark.parametrize("path", ["/planes", "/planes/split", "/planes/merge"])
def test_a_tap_outside_the_photo_is_refused(client: TestClient, path: str) -> None:
    session_id = upload(client)

    response = client.post(
        f"/sessions/{session_id}{path}",
        headers=auth(),
        json={"x": _WIDTH, "y": 0},  # x == width is one past the last column
    )

    assert response.status_code == 422
    assert response.json()["code"] == "malformed_request"


# --- Split: pure geometry, no model needed -------------------------------------------------------


def test_split_cuts_the_plane_in_two_at_the_tapped_column(client: TestClient) -> None:
    session_id = upload(client)

    response = client.post(
        f"/sessions/{session_id}/planes/split",
        headers=auth(),
        json={"x": _RECT_CENTRE_X, "y": _RECT_CENTRE_Y},
    )

    assert response.status_code == 201, response.text
    planes = response.json()["planes"]
    assert len(planes) == 2
    # Left-to-right order (implementation-decisions.md #39), and a crisp cut: wall-to-wall never
    # carries a soft edge (spec, "Corners").
    assert planes[0]["bounds"]["right"] <= planes[1]["bounds"]["left"]
    # The listing route agrees with what the correction itself returned.
    assert planes_of(client, session_id) == planes


def test_split_refuses_a_point_not_on_any_plane(client: TestClient) -> None:
    session_id = upload(client)

    response = client.post(
        f"/sessions/{session_id}/planes/split",
        headers=auth(),
        json={"x": 2, "y": 2},  # the corner, well outside the centred stub rectangle
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "malformed_request"
    assert "add" in body["message"].lower()


def test_split_refuses_a_cut_too_close_to_the_plane_s_edge(client: TestClient) -> None:
    session_id = upload(client)
    # Confidently covered (past the rectangle's own soft band), but only a couple of pixels in
    # from its left edge — a cut there leaves almost nothing on that side.
    x, y = _RECT_LEFT + _RECT_BAND + 1, _RECT_CENTRE_Y

    response = client.post(
        f"/sessions/{session_id}/planes/split", headers=auth(), json={"x": x, "y": y}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "malformed_request"


# --- Merge: pure geometry, no model needed -------------------------------------------------------


def test_merge_unions_the_two_planes_meeting_at_the_tapped_seam(
    two_plane_client: TestClient,
) -> None:
    session_id = upload(two_plane_client)
    before = planes_of(two_plane_client, session_id)
    assert len(before) == 2

    response = two_plane_client.post(
        f"/sessions/{session_id}/planes/merge",
        headers=auth(),
        json={"x": _WIDTH // 2, "y": _RECT_CENTRE_Y},
    )

    assert response.status_code == 200, response.text
    after = response.json()["planes"]
    assert len(after) == 1
    # The union of two disjoint mattes covers at least as much as either alone.
    assert after[0]["coverage"] >= max(plane["coverage"] for plane in before) - 1e-6
    assert planes_of(two_plane_client, session_id) == after


def test_merge_refuses_a_point_not_near_a_seam(two_plane_client: TestClient) -> None:
    session_id = upload(two_plane_client)
    # Well inside the left plane's own interior, far from the seam at width // 2.
    x, y = _RECT_LEFT + _RECT_W // 6, _RECT_CENTRE_Y

    response = two_plane_client.post(
        f"/sessions/{session_id}/planes/merge", headers=auth(), json={"x": x, "y": y}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "malformed_request"
    assert "meet" in body["message"].lower()


def test_merge_refuses_when_fewer_than_two_planes_exist(client: TestClient) -> None:
    session_id = upload(client)  # the single-plane stub session

    response = client.post(
        f"/sessions/{session_id}/planes/merge",
        headers=auth(),
        json={"x": _RECT_CENTRE_X, "y": _RECT_CENTRE_Y},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "malformed_request"
