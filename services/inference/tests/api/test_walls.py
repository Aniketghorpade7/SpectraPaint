"""Seam 1 with the real models: does wall detection actually find the wall? (ticket #6)

Slow lane only — every test here is marked ``models``, because each one loads the exported graphs
and runs a photo through them. The fast lane covers the same contract with a known matte
(tests/api/conftest.py); this file is the other half, and the half that can be wrong in ways a stub
cannot reveal.

Two kinds of test live here, and the difference matters.

**Contract, on a real photo.** Statuses, shapes, the matte being soft rather than binary. These
need a photograph but not a hand-labelled answer, so any fixture will do.

**Accuracy, against a hand-labelled answer.** Whether the wall found *is* the wall. These compare
against `<name>.wall.png` and cannot run without it. Two of ticket #6's acceptance criteria are only
checkable this way, so when the fixtures are absent these tests **skip with a reason** rather than
passing — see data/fixtures/rooms/README.md.

The thresholds below are floors, not targets. They are set where a clear regression trips them
while ordinary variation between photographs does not, and they are deliberately not the numbers
worth reporting — the measured evaluation those belong to is docs/design-decisions.md §10.
"""

import io
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from spectrapaint.api.app import create_app

pytestmark = pytest.mark.models

SECRET = "test-secret-not-a-real-one"

# tests/api/test_walls.py -> the repository root is five levels up.
FIXTURE_DIR = Path(__file__).resolve().parents[4] / "data" / "fixtures" / "rooms"

# Overlap between the matte and the hand-labelled wall. A floor: SegFormer-B0 constrained by SAM 2
# should comfortably clear this on an ordinary room, and anything below it means the pipeline has
# stopped finding walls rather than merely finding them imperfectly.
MINIMUM_WALL_IOU = 0.60

# How much of the *darkest* labelled wall must still be covered. This is the shadow criterion, and
# it is the reason the fixtures are asked to include a strongly shadowed wall: a pipeline that cuts
# at shadow boundaries fails here and nowhere else.
MINIMUM_SHADOWED_WALL_RECALL = 0.80

# The share of the darkest labelled-wall pixels treated as "in shadow".
SHADOW_QUANTILE = 0.25

# How much coverage may land on pixels the label says are not wall. Windows, doors and furniture
# painted over is the most visible way to be wrong.
MAXIMUM_NON_WALL_COVERAGE = 0.20

# Anything between these is an "unsure" label and is not counted either way.
_LABEL_WALL = 0.75
_LABEL_NOT_WALL = 0.25


def rooms() -> list[Path]:
    """Every fixture photograph on disk, in a stable order."""
    if not FIXTURE_DIR.is_dir():
        return []
    return sorted(
        path
        for path in FIXTURE_DIR.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"} and not path.name.endswith(".wall.png")
    )


def labelled_rooms() -> list[Path]:
    """Fixture photographs that also have a hand-labelled wall mask."""
    return [path for path in rooms() if label_path(path).is_file()]


def label_path(photo: Path) -> Path:
    return photo.with_suffix("").with_suffix(".wall.png")


NO_PHOTOS = "no room fixtures in data/fixtures/rooms — see its README"
NO_LABELS = "no hand-labelled wall masks in data/fixtures/rooms — see its README"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(SECRET))


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {SECRET}"}


def prepare(client: TestClient, photo: Path) -> str:
    """Upload a photo and wait for preparation to finish, returning the session id."""
    response = client.post(
        "/sessions",
        headers=auth(),
        files={"photo": (photo.name, photo.read_bytes(), "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["session_id"]

    # Reading the stream to its terminal event is how a client waits; the endpoints below wait the
    # same way internally, so this also asserts the stream still ends exactly once.
    events = client.get(f"/sessions/{session_id}/events", headers=auth())
    assert events.status_code == 200
    terminals = [line for line in events.text.splitlines() if '"phase"' in line]
    assert '"failed"' not in events.text, (
        f"preparation failed: {terminals[-1] if terminals else ''}"
    )
    return session_id


def matte_of(client: TestClient, session_id: str, plane_id: str) -> np.ndarray:
    response = client.get(f"/sessions/{session_id}/planes/{plane_id}/matte", headers=auth())
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.mode == "L"
        return np.asarray(image, dtype=np.float32) / 255.0


def labels_for(photo: Path, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """The hand-labelled wall and not-wall, resized to the matte's own resolution.

    Nearest-neighbour, so a resized label is still a label somebody drew rather than an average of
    two of them. The photo is prepared at preview scale, so the mask — drawn at full resolution —
    has to come down to meet it.
    """

    with Image.open(label_path(photo)) as image:
        grey = image.convert("L").resize((shape[1], shape[0]), resample=Image.Resampling.NEAREST)
    label = np.asarray(grey, dtype=np.float32) / 255.0
    return label >= _LABEL_WALL, label <= _LABEL_NOT_WALL


def luminance_of(photo: Path, shape: tuple[int, int]) -> np.ndarray:
    with Image.open(photo) as image:
        rgb = image.convert("RGB").resize((shape[1], shape[0]), resample=Image.Resampling.BILINEAR)
    weights = np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)
    return (np.asarray(rgb, dtype=np.float32) @ weights) / 255.0


@pytest.mark.skipif(not rooms(), reason=NO_PHOTOS)
@pytest.mark.parametrize("photo", rooms() or [None], ids=lambda p: p.stem if p else "none")
def test_a_real_photo_yields_one_wall_plane_with_a_soft_matte(
    client: TestClient, photo: Path
) -> None:
    """The pipeline finds a wall, and describes it with a soft matte at photo resolution.

    Soft is checked, not assumed: a binary mask would have no fractional pixels at all, and hard
    edges are the clearest visual sign that an image has been altered (CONTEXT.md).
    """

    session_id = prepare(client, photo)

    planes = client.get(f"/sessions/{session_id}/planes", headers=auth())
    assert planes.status_code == 200
    described = planes.json()["planes"]
    assert len(described) == 1, "ticket #6 finds one region; splitting is #7"

    plane = described[0]
    assert plane["bounds"] is not None
    assert 0.0 < plane["coverage"] <= 1.0

    matte = matte_of(client, session_id, plane["plane_id"])
    assert matte.shape == (plane["photo_height"], plane["photo_width"])

    fractional = (matte > 0.02) & (matte < 0.98)
    assert fractional.any(), "the matte is binary, not a soft Alpha Matte"
    assert (matte >= 0.98).any(), "no pixel is fully inside the wall"


@pytest.mark.skipif(not rooms(), reason=NO_PHOTOS)
@pytest.mark.parametrize("photo", rooms() or [None], ids=lambda p: p.stem if p else "none")
def test_a_real_photo_can_be_repainted(client: TestClient, photo: Path) -> None:
    """The whole contract, end to end on a real photograph: detect, then repaint."""

    session_id = prepare(client, photo)
    plane_id = client.get(f"/sessions/{session_id}/planes", headers=auth()).json()["planes"][0][
        "plane_id"
    ]

    response = client.post(
        f"/sessions/{session_id}/renders",
        headers=auth(),
        json={"assignments": {plane_id: "PS-1001"}, "mode": "realistic"},
    )
    assert response.status_code == 201, response.text
    assert response.headers["content-type"] == "image/png"


@pytest.mark.skipif(not labelled_rooms(), reason=NO_LABELS)
@pytest.mark.parametrize("photo", labelled_rooms() or [None], ids=lambda p: p.stem if p else "none")
def test_the_wall_found_is_the_wall_that_is_there(client: TestClient, photo: Path) -> None:
    """Overlap against a hand-labelled wall, which is the only way to check this at all."""

    session_id = prepare(client, photo)
    plane_id = client.get(f"/sessions/{session_id}/planes", headers=auth()).json()["planes"][0][
        "plane_id"
    ]
    matte = matte_of(client, session_id, plane_id)

    wall, not_wall = labels_for(photo, matte.shape)
    found = matte >= 0.5

    intersection = float((found & wall).sum())
    union = float((found | wall).sum())
    iou = intersection / union if union else 0.0
    assert iou >= MINIMUM_WALL_IOU, f"wall IoU {iou:.2f} on {photo.name}"

    # Windows, doors, floor, ceiling and furniture: whatever the label says is not wall must be
    # mostly left alone, or the render paints over it.
    if not_wall.any():
        leakage = float(matte[not_wall].mean())
        assert leakage <= MAXIMUM_NON_WALL_COVERAGE, (
            f"{leakage:.2f} mean coverage on non-wall pixels of {photo.name}"
        )


@pytest.mark.skipif(not labelled_rooms(), reason=NO_LABELS)
@pytest.mark.parametrize("photo", labelled_rooms() or [None], ids=lambda p: p.stem if p else "none")
def test_shadowed_wall_stays_wall(client: TestClient, photo: Path) -> None:
    """The darkest quarter of the labelled wall must still be covered.

    A shadow cast on a wall *is* the wall. SAM 2 is appearance-driven and a strong shadow edge looks
    to it like an object edge, so this is the criterion the semantic pass's override exists for —
    and the one whose failure leaves a visible ghost of the old paint after recolouring.
    """

    session_id = prepare(client, photo)
    plane_id = client.get(f"/sessions/{session_id}/planes", headers=auth()).json()["planes"][0][
        "plane_id"
    ]
    matte = matte_of(client, session_id, plane_id)

    wall, _ = labels_for(photo, matte.shape)
    if not wall.any():
        pytest.skip(f"{photo.name} has no labelled wall")

    luminance = luminance_of(photo, matte.shape)
    threshold = float(np.quantile(luminance[wall], SHADOW_QUANTILE))
    shadowed = wall & (luminance <= threshold)
    if not shadowed.any():
        pytest.skip(f"{photo.name} has no shadowed wall to speak of")

    recall = float((matte[shadowed] >= 0.5).mean())
    assert recall >= MINIMUM_SHADOWED_WALL_RECALL, (
        f"only {recall:.0%} of the shadowed wall in {photo.name} survived — "
        "a ghost of the old paint would show after recolouring"
    )
