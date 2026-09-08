"""Seam 1 — the Wall Planes list over the REST contract (ticket #6), and its empty case (#10).

docs/conventions.md §6: behaviour and lifecycle, never implementation. What matters here is not
which pixels a matte covers — the accuracy claims belong to the real pipeline and are exercised by
tests/api/test_walls.py — but what the contract *says* when a photo has planes, and what it says
when it has none at all.
"""

import base64

import pytest
from fastapi.testclient import TestClient

from spectrapaint.api.app import create_app
from tests.api.conftest import no_wall_found_preparation_stages, stub_preparation_stages

SECRET = "test-secret-not-a-real-one"

# A 1x1 transparent PNG, small enough to embed. What the photo actually shows is irrelevant here —
# every stage below replaces detection with a known outcome.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGPcUhHFwMDAxMDAwMDAAA"
    "ASzAGKIhSa8QAAAABJRU5ErkJggg=="
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(SECRET, preparation_stages=stub_preparation_stages))


@pytest.fixture
def no_wall_client() -> TestClient:
    """A session whose photo yields no Wall Planes at all — automatic detection's empty answer."""
    return TestClient(create_app(SECRET, preparation_stages=no_wall_found_preparation_stages))


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {SECRET}"}


def upload(client: TestClient) -> str:
    response = client.post(
        "/sessions",
        headers=auth(),
        files={"photo": ("room.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def test_a_found_wall_is_listed_with_no_note(client: TestClient) -> None:
    session_id = upload(client)

    response = client.get(f"/sessions/{session_id}/planes", headers=auth())

    assert response.status_code == 200
    body = response.json()
    assert len(body["planes"]) == 1
    assert body["note"] is None


def test_finding_no_wall_does_not_fail_the_session(no_wall_client: TestClient) -> None:
    """Automatic detection finding nothing is not a preparation failure (ticket #10).

    Before this ticket, ``NoWallFound`` ended the session's preparation with a terminal ``failed``
    event and nothing else was reachable — the exact dead end conventions.md §5 forbids. It must
    now finish as ``done``, exactly like a photo where a wall *was* found.
    """
    session_id = upload(no_wall_client)

    events = no_wall_client.get(f"/sessions/{session_id}/events", headers=auth())

    assert events.status_code == 200
    assert '"failed"' not in events.text, events.text
    assert '"done"' in events.text


def test_a_photo_with_no_wall_lists_no_planes_and_a_plain_language_note(
    no_wall_client: TestClient,
) -> None:
    session_id = upload(no_wall_client)

    response = no_wall_client.get(f"/sessions/{session_id}/planes", headers=auth())

    assert response.status_code == 200
    body = response.json()
    assert body["planes"] == []
    assert isinstance(body["note"], str) and body["note"]


def test_a_photo_with_no_wall_still_states_its_own_dimensions(
    no_wall_client: TestClient,
) -> None:
    """The Add tool needs the photo's own pixel space to turn a tap into a point in it — and a
    zero-plane photo has no plane object left to read ``photo_width``/``photo_height`` from
    (implementation-decisions.md #40), so the top-level fields are what it falls back to."""
    session_id = upload(no_wall_client)

    response = no_wall_client.get(f"/sessions/{session_id}/planes", headers=auth())

    assert response.status_code == 200
    body = response.json()
    assert body["photo_width"] > 0
    assert body["photo_height"] > 0


def test_a_photo_with_no_wall_cannot_be_rendered_but_fails_cleanly(
    no_wall_client: TestClient,
) -> None:
    """Nothing to paint is a clean refusal, never a crash — the Dealer still has the correction
    surface's Add tool to reach for, which is a route this test does not need to know about."""
    session_id = upload(no_wall_client)

    response = no_wall_client.post(
        f"/sessions/{session_id}/renders",
        headers=auth(),
        json={"assignments": {"wall_plane_1": "PS-1001"}, "mode": "realistic"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "malformed_request"
    assert body["message"]
