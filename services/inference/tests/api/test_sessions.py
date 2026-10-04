"""Seam 1 — session lifecycle over the REST contract.

docs/conventions.md §6: behaviour and lifecycle, never implementation. What the contract returns is
behaviour; how the service decides is not. These tests must survive restructuring the session
registry or swapping the validation library.
"""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import spectrapaint.api.sessions as sessions
from spectrapaint.api.app import create_app
from tests.api.conftest import stub_preparation_stages

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


@pytest.fixture
def prepared_client() -> TestClient:
    """Preparation that decodes for real and attaches a known matte.

    The EXIF tests below are about what ``decode_photo`` — the decode production runs — does to an
    oriented photo, so the decode is genuine and only the model stages stand in (tests/api/conftest
    explains why that is not mocking).
    """

    return TestClient(create_app(SECRET, preparation_stages=stub_preparation_stages))


def landscape_jpeg_with_orientation(orientation: int) -> bytes:
    """Landscape pixels (8×6) carrying an EXIF Orientation tag, as a phone camera stores them.

    Orientation 6 says the stored rows are the visual right-hand side — the picture is portrait
    once the tag is honoured, which is what the Dealer sees in any viewer that applies it.
    """

    buffer = io.BytesIO()
    image = Image.new("RGB", (8, 6), (140, 60, 60))
    exif = image.getexif()
    exif[0x0112] = orientation
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


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


def test_the_prepared_photo_is_served_before_any_render(prepared_client: TestClient) -> None:
    """The photo route answers from the in-memory session (issue #49).

    The stored copy at ``/consultations/{id}/photo/png`` only exists after the first render's gate
    persists the preparation; the Consultation needs the prepared pixels the moment preparation is
    done, so it can show them instead of the raw upload.
    """

    session_id = upload(prepared_client, PNG_BYTES).json()["session_id"]

    response = prepared_client.get(f"/sessions/{session_id}/photo/png", headers=auth())

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(response.content)).size == (2, 2)


def test_the_prepared_photo_is_encoded_once_per_session(
    prepared_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking for the photo again costs nothing: the PNG is encoded once and reused (issue #49)."""

    from spectrapaint.api import sessions

    encodes: list[int] = []
    real_encode = sessions._encode_photo

    def counting_encode(srgb):  # noqa: ANN001, ANN202
        encodes.append(1)
        return real_encode(srgb)

    monkeypatch.setattr(sessions, "_encode_photo", counting_encode)
    session_id = upload(prepared_client, PNG_BYTES).json()["session_id"]

    first = prepared_client.get(f"/sessions/{session_id}/photo/png", headers=auth())
    second = prepared_client.get(f"/sessions/{session_id}/photo/png", headers=auth())

    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert len(encodes) == 1


def test_the_photo_route_fails_cleanly_for_an_unknown_session(client: TestClient) -> None:
    response = client.get("/sessions/does-not-exist/photo/png", headers=auth())

    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"
    assert response.json()["message"]


def test_an_exif_orientation_is_applied_to_the_prepared_photo_and_its_mattes(
    prepared_client: TestClient,
) -> None:
    """A photo stored landscape with EXIF Orientation=6 is portrait once prepared (issue #49).

    The photo the Dealer is shown, the mattes and every later render are built on the prepared
    pixels, so the orientation must be applied once, here — not left for the browser to apply to
    the raw upload while everything downstream works on unrotated pixels.
    """

    response = prepared_client.post(
        "/sessions",
        headers=auth(),
        files={"photo": ("room.jpg", landscape_jpeg_with_orientation(6), "image/jpeg")},
    )
    session_id = response.json()["session_id"]

    photo = prepared_client.get(f"/sessions/{session_id}/photo/png", headers=auth())

    assert photo.status_code == 200
    prepared = Image.open(io.BytesIO(photo.content))
    assert prepared.size == (6, 8)  # portrait: the stored rows were turned upright

    planes = prepared_client.get(f"/sessions/{session_id}/planes", headers=auth()).json()
    assert planes["photo_width"] == 6
    assert planes["photo_height"] == 8
    assert planes["planes"]
    for plane in planes["planes"]:
        matte = prepared_client.get(
            f"/sessions/{session_id}/planes/{plane['plane_id']}/matte", headers=auth()
        )
        assert matte.status_code == 200
        assert Image.open(io.BytesIO(matte.content)).size == (6, 8)


def test_a_photo_without_an_exif_orientation_is_unchanged(prepared_client: TestClient) -> None:
    """The transpose is harmless when there is no tag — the technical call in the bug doc."""

    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), (140, 60, 60)).save(buffer, format="JPEG")

    response = prepared_client.post(
        "/sessions", headers=auth(), files={"photo": ("room.jpg", buffer.getvalue(), "image/jpeg")}
    )
    session_id = response.json()["session_id"]

    photo = prepared_client.get(f"/sessions/{session_id}/photo/png", headers=auth())

    assert Image.open(io.BytesIO(photo.content)).size == (8, 6)


def test_the_contract_is_exactly_the_documented_surface(client: TestClient) -> None:
    """Encode-once is enforced structurally, by omission.

    The documented contract (docs/specs/v1-spectrapaint.md) has no endpoint accepting an image
    alongside a Shade, and this test pins the whole surface so one cannot appear silently. The
    planes endpoints were added deliberately, by ticket #6, which is what changing this list is
    for.
    """

    expected = {
        ("/health", frozenset({"GET"})),
        # Issue #14. The execution profile the Dealer's settings surface and the benchmark read,
        # so what a machine reports and what a result records stay comparable. GET, never taking
        # an image and never writing.
        ("/execution-profile", frozenset({"GET"})),
        ("/sessions", frozenset({"POST"})),
        ("/sessions/{session_id}", frozenset({"DELETE"})),
        ("/sessions/{session_id}/events", frozenset({"GET"})),
        # Issue #49. The prepared photo before any render exists, so the Consultation can show the
        # pixels that were segmented instead of the raw upload. GET, never taking an image:
        # encode-once still holds.
        ("/sessions/{session_id}/photo/png", frozenset({"GET"})),
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
        # Issue #39. Add the ceiling — same point-prompt decode as Add wall, but tagged
        # surface="ceiling" and never grouped with a wall's base colour.
        ("/sessions/{session_id}/planes/ceiling", frozenset({"POST"})),
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
