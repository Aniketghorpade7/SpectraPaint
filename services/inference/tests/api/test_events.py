"""Seam 1 — the progress stream over the REST contract.

Ticket #4's acceptance criteria, asserted as behaviour: events arrive in order and terminate; a
reader that joins after work started still sees sensible progress; messages are plain language; the
secret is required; and a photo that fails preparation streams a terminal ``failed`` instead of
leaving the Dealer waiting on nothing.

docs/conventions.md §6: assert what the contract returns, never how the service decided it. These
tests use injected preparation stages with a fixed rhythm so the stream is deterministic without
timing luck.
"""

import base64
import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from spectrapaint.api.app import create_app
from spectrapaint.api.preparation import Stage, build_preparation_stages

SECRET = "test-secret-not-a-real-one"

# A 1x1 transparent PNG, small enough to embed. The fixture for every happy-path test.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGPcUhHFwMDAxMDAwMDAAA"
    "ASzAGKIhSa8QAAAABJRU5ErkJggg=="
)

# A real JPEG with its end-of-image marker stripped: the upload's structural check (verify()) passes
# it, but decoding its pixels fails — the exact gap preparation is there to catch.
_STRIPPED_EOI_JPEG = None


def stripped_eoi_jpeg() -> bytes:
    global _STRIPPED_EOI_JPEG
    if _STRIPPED_EOI_JPEG is None:
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), (120, 130, 140)).save(buffer, "JPEG")
        _STRIPPED_EOI_JPEG = buffer.getvalue()[:-2]
    return _STRIPPED_EOI_JPEG


def auth(secret: str = SECRET) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def upload(
    client: TestClient,
    contents: bytes,
    name: str = "room.png",
    mime: str = "image/png",
) -> object:
    return client.post("/sessions", headers=auth(), files={"photo": (name, contents, mime)})


def _pause() -> None:
    time.sleep(0.05)


def slow_client() -> TestClient:
    """A service whose preparation walks two real, brief stages — enough to stream."""
    stages = [Stage("First stage…", run=_pause), Stage("Second stage…", run=_pause)]
    return TestClient(create_app(SECRET, preparation_stages=lambda _contents: stages))


def read_events(response) -> list[dict[str, str]]:
    """Every ``data:`` payload in an SSE response, in order."""
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.iter_lines()
        if line.startswith("data: ")
    ]


def test_progress_events_arrive_in_order_and_terminate() -> None:
    client = slow_client()
    session_id = upload(client, PNG_BYTES).json()["session_id"]

    with client.stream("GET", f"/sessions/{session_id}/events", headers=auth()) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = read_events(response)

    assert [event["phase"] for event in events] == ["progress", "progress", "done"]
    assert [event["message"] for event in events if event["phase"] == "progress"] == [
        "First stage…",
        "Second stage…",
    ]
    # The stream ended with the terminal event — it does not hang after 'done'.
    assert events[-1] == {"phase": "done"}


def test_opening_the_stream_after_work_started_yields_sensible_progress() -> None:
    """A reader who connects after preparation finished replays the whole log and still ends.

    This is the strong form of "opening slightly after work has started": the terminal event was
    sent before the reader arrived, so a stream that only listened live would hang forever.
    """
    client = slow_client()
    session_id = upload(client, PNG_BYTES).json()["session_id"]
    time.sleep(0.3)

    with client.stream("GET", f"/sessions/{session_id}/events", headers=auth()) as response:
        events = read_events(response)

    assert [event["phase"] for event in events] == ["progress", "progress", "done"]


def test_progress_messages_are_plain_language(client: TestClient) -> None:
    forbidden = ["inference", "model", "segment", "mask", "pixel", "neural", "sam"]
    stages = build_preparation_stages(PNG_BYTES)

    assert stages, "preparation must walk at least one real stage"
    for stage in stages:
        lower = stage.message.lower()
        for word in forbidden:
            assert word not in lower, f"{stage.message!r} names {word!r}"
        assert stage.message, "a stage must have something to say"


def test_a_photo_that_fails_preparation_streams_a_failed_terminal(client: TestClient) -> None:
    """The upload accepts the photo (verify() passed) but decoding it fails during preparation.

    The Dealer must not sit on an endless stream: the job reports one plain-language 'failed'
    terminal and the stream closes, like a 'done' would.
    """
    session_id = upload(client, stripped_eoi_jpeg(), name="room.jpg", mime="image/jpeg").json()[
        "session_id"
    ]

    with client.stream("GET", f"/sessions/{session_id}/events", headers=auth()) as response:
        events = read_events(response)

    assert [event["phase"] for event in events] == ["progress", "failed"]
    assert events[-1]["message"]
    assert events[-1]["message"] != "done"


def test_the_progress_stream_requires_the_secret(client: TestClient) -> None:
    session_id = upload(client, PNG_BYTES).json()["session_id"]

    response = client.get(f"/sessions/{session_id}/events")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorised"


def test_the_progress_stream_for_an_unknown_session_fails_cleanly(client: TestClient) -> None:
    response = client.get("/sessions/does-not-exist/events", headers=auth())

    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(SECRET))
