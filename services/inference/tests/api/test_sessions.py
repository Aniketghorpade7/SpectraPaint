"""Seam 1 — session lifecycle over the REST contract.

docs/conventions.md §6: behaviour and lifecycle, never implementation. What the contract returns is
behaviour; how the service decides is not. These tests must survive restructuring the session
registry or swapping the validation library.
"""

import base64

import pytest
from fastapi.testclient import TestClient

import spectrapaint.api.sessions as sessions
from spectrapaint.api.app import create_app

SECRET = "test-secret-not-a-real-one"

# A 1x1 transparent PNG, small enough to embed. The fixture for every happy-path test.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGPcUhHFwMDAxMDAwMDAAA"
    "ASzAGKIhSa8QAAAABJRU5ErkJggg=="
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(SECRET))


def auth(secret: str = SECRET) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def upload(client: TestClient, contents: bytes, name: str = "room.png") -> object:
    return client.post(
        "/sessions",
        headers=auth(),
        files={"photo": (name, contents, "image/png")},
    )


def test_a_photo_upload_creates_a_session_and_returns_its_id(client: TestClient) -> None:
    response = upload(client, PNG_BYTES)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"session_id"}
    assert body["session_id"]


def test_two_uploads_create_distinct_sessions(client: TestClient) -> None:
    first = upload(client, PNG_BYTES).json()["session_id"]
    second = upload(client, PNG_BYTES).json()["session_id"]

    assert first != second


def test_a_session_can_be_deleted(client: TestClient) -> None:
    session_id = upload(client, PNG_BYTES).json()["session_id"]

    assert client.delete(f"/sessions/{session_id}", headers=auth()).status_code == 204


def test_requests_against_a_deleted_session_fail_cleanly(client: TestClient) -> None:
    """After deletion the session is gone, and the response carries the one error shape."""

    session_id = upload(client, PNG_BYTES).json()["session_id"]
    client.delete(f"/sessions/{session_id}", headers=auth())

    second_delete = client.delete(f"/sessions/{session_id}", headers=auth())

    assert second_delete.status_code == 404
    body = second_delete.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "session_not_found"
    assert body["message"]


def test_deleting_a_session_that_never_existed_fails_cleanly(client: TestClient) -> None:
    response = client.delete("/sessions/does-not-exist", headers=auth())

    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"


def test_a_corrupt_file_is_refused_with_a_clear_message(client: TestClient) -> None:
    """A truncated PNG keeps its magic bytes but is not a real photo — the decode must catch it."""

    response = upload(client, PNG_BYTES[:20])

    assert response.status_code == 422
    assert response.json()["code"] == "unsupported_image"
    assert response.json()["message"]


def test_a_file_that_is_not_an_image_is_refused(client: TestClient) -> None:
    response = upload(client, b"this is a text file, not a photo", name="room.txt")

    assert response.status_code == 422
    assert response.json()["code"] == "unsupported_image"


def test_a_decompression_bomb_is_refused_not_crashed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A small file claiming to decode to enormous dimensions must be refused with a message,
    never allowed to blow up a later stage — acceptance criterion 6, the crash case."""

    import PIL.Image

    monkeypatch.setattr(PIL.Image, "MAX_IMAGE_PIXELS", 1)

    response = upload(client, PNG_BYTES)

    assert response.status_code == 422
    assert response.json()["code"] == "unsupported_image"
    assert response.json()["message"]


def test_an_empty_file_is_refused(client: TestClient) -> None:
    response = upload(client, b"")

    assert response.status_code == 422
    assert response.json()["code"] == "unsupported_image"


def test_an_over_large_photo_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "MAX_UPLOAD_BYTES", 10)

    response = upload(client, PNG_BYTES)

    assert response.status_code == 413
    assert response.json()["code"] == "photo_too_large"


def test_a_missing_photo_field_is_a_malformed_request(client: TestClient) -> None:
    response = client.post("/sessions", headers=auth())

    assert response.status_code == 422
    assert response.json()["code"] == "malformed_request"


def test_session_creation_requires_the_secret(client: TestClient) -> None:
    response = client.post("/sessions", files={"photo": ("room.png", PNG_BYTES, "image/png")})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorised"


def test_the_contract_is_exactly_the_documented_surface(client: TestClient) -> None:
    """Encode-once is enforced structurally, by omission.

    The documented contract (docs/specs/v1-spectrapaint.md) has no endpoint accepting an image
    alongside a Shade, and this test pins the whole surface so one cannot appear silently. The
    planes endpoints were added deliberately, by ticket #6, which is what changing this list is
    for.
    """

    expected = {
        ("/health", frozenset({"GET"})),
        ("/sessions", frozenset({"POST"})),
        ("/sessions/{session_id}", frozenset({"DELETE"})),
        ("/sessions/{session_id}/events", frozenset({"GET"})),
        # Issue #3. One per Shade change; the photo stays in the session (encode-once).
        ("/sessions/{session_id}/renders", frozenset({"POST"})),
        # Issue #12. Full-resolution JPEG for the OS share sheet; same assignments as renders.
        ("/sessions/{session_id}/exports", frozenset({"POST"})),
        # Issue #6. What walls the photo has, and the matte for one of them. GET, never taking an
        # image, so encode-once is still structural. Ticket #10 adds a POST on the same path,
        # its own route object rather than a merged method set (FastAPI registers one per
        # decorator, even sharing a path): a tapped point, never a Shade or an image, adding a
        # Wall Plane (the Add tool) rather than naming what to render — still nothing this rule
        # forbids.
        ("/sessions/{session_id}/planes", frozenset({"GET"})),
        ("/sessions/{session_id}/planes", frozenset({"POST"})),
        ("/sessions/{session_id}/planes/{plane_id}/matte", frozenset({"GET"})),
        # Ticket #10's other two correction tools. Same shape as Add: a tapped point in, the
        # updated plane list out, no photo and no re-preparation.
        ("/sessions/{session_id}/planes/split", frozenset({"POST"})),
        ("/sessions/{session_id}/planes/merge", frozenset({"POST"})),
        # Issue #5. All three are GET: the Catalogue is a data file the service was pointed at, so
        # there is nothing here that writes, and nothing that takes an image.
        ("/catalogue", frozenset({"GET"})),
        ("/catalogue/shades", frozenset({"GET"})),
        ("/catalogue/shades/{shade_code}", frozenset({"GET"})),
        # Issue #11. The library: Bundles are managed (rename is PATCH; delete moves its
        # Consultations to the default Bundle), a Consultation's history and stored images are
        # replayed byte-for-byte, and reopen builds a live session from what preparation stored —
        # no endpoint here regenerates anything.
        ("/bundles", frozenset({"GET"})),
        ("/bundles", frozenset({"POST"})),
        ("/bundles/{bundle_id}", frozenset({"PATCH"})),
        ("/bundles/{bundle_id}", frozenset({"DELETE"})),
        ("/bundles/{bundle_id}/consultations", frozenset({"GET"})),
        ("/bundles/{bundle_id}/consultations", frozenset({"POST"})),
        ("/consultations/{consultation_id}/renders", frozenset({"GET"})),
        ("/consultations/{consultation_id}/photo/png", frozenset({"GET"})),
        (
            "/consultations/{consultation_id}/renders/{render_id}/png",
            frozenset({"GET"}),
        ),
        ("/consultations/{consultation_id}/reopen", frozenset({"POST"})),
        # Issue #13. Storage view and low-disk warning: bundles by bytes, disk
        # probe, and deleting a Consultation from the view.
        ("/storage", frozenset({"GET"})),
        ("/storage/disk", frozenset({"GET"})),
        ("/consultations/{consultation_id}", frozenset({"DELETE"})),
    }

    actual = set()
    pending = [route for route in client.app.routes]
    while pending:
        route = pending.pop()
        # FastAPI 0.141 keeps included routers nested; unwrap them to reach the leaf routes.
        pending.extend(getattr(route, "routes", None) or [])
        original = getattr(route, "original_router", None)
        if original is not None:
            pending.extend(original.routes or [])
        methods = getattr(route, "methods", None)
        if methods:
            actual.add((route.path, frozenset(methods - {"HEAD"})))

    assert actual == expected
