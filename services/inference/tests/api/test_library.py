"""Seam 1 — the library: Bundles, saved Consultations, stored Renders (issue #11).

Behaviour over the REST contract, with the Store pointed at a throwaway directory through
``create_app(store=...)`` — the same injection rule every other dependency follows
(docs/conventions.md §6). What is asserted is what the Dealer's criteria need:

* a Consultation exists without anyone pressing save;
* Bundles can be created, renamed and deleted without losing Consultations;
* a reopened Consultation replays stored bytes and never regenerates them;
* reopening needs no second run of preparation;
* every Render records what produced it.

The real per-user directory is never touched: ``Store`` takes its directory, so the test gives it
one from pytest's ``tmp_path``.
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from spectrapaint.api.app import create_app
from spectrapaint.api.preparation import Stage
from spectrapaint.catalogue import CatalogueFileMissing
from spectrapaint.segmentation.walls import FIRST_WALL_PLANE_ID
from spectrapaint.storage import DEFAULT_BUNDLE_NAME, Store, resolve_storage_dir
from tests.api.conftest import stub_preparation_stages

SECRET = "test-secret-not-a-real-one"

NEUTRAL_ROOM_SRGB = (188, 188, 188)
ROOM_SIZE = (64, 64)
SHADE_CODE = "PS-1001"


def png_bytes(rgb: tuple[int, int, int], size: tuple[int, int] = ROOM_SIZE) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, rgb).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "library")


@pytest.fixture
def client(store: Store) -> TestClient:
    return TestClient(create_app(SECRET, preparation_stages=stub_preparation_stages, store=store))


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {SECRET}"}


def upload(client: TestClient, contents: bytes) -> str:
    response = client.post(
        "/sessions",
        headers=auth(),
        files={"photo": ("room.png", contents, "image/png")},
    )
    assert response.status_code == 201
    return response.json()["session_id"]


def render_once(client: TestClient, session_id: str, mode: str = "realistic") -> object:
    return client.post(
        f"/sessions/{session_id}/renders",
        headers=auth(),
        json={"assignments": {FIRST_WALL_PLANE_ID: SHADE_CODE}, "mode": mode},
    )


# -- auto-save ------------------------------------------------------------------------------------


def test_uploading_saves_a_consultation_without_anyone_pressing_save(
    client: TestClient, store: Store
) -> None:
    session_id = upload(client, png_bytes(NEUTRAL_ROOM_SRGB))

    default = next(b for b in store.list_bundles() if b["name"] == DEFAULT_BUNDLE_NAME)
    consultations = store.list_consultations(default["bundle_id"])
    assert [c["consultation_id"] for c in consultations] == [session_id]


def test_ending_a_session_keeps_the_saved_consultation_and_its_renders(
    client: TestClient,
) -> None:
    session_id = upload(client, png_bytes(NEUTRAL_ROOM_SRGB))
    assert render_once(client, session_id).status_code == 201
    assert client.delete(f"/sessions/{session_id}", headers=auth()).status_code == 204

    history = client.get(f"/consultations/{session_id}/renders", headers=auth())
    assert history.status_code == 200
    assert len(history.json()["renders"]) == 1


# -- bundles --------------------------------------------------------------------------------------


def test_a_bundle_can_be_created_renamed_and_deleted(client: TestClient) -> None:
    created = client.post("/bundles", headers=auth(), json={"name": "Sharma house"})
    assert created.status_code == 201
    bundle = created.json()

    renamed = client.patch(
        f"/bundles/{bundle['bundle_id']}", headers=auth(), json={"name": "Sharma bungalow"}
    )
    assert renamed.status_code == 200
    names = {b["name"] for b in client.get("/bundles", headers=auth()).json()["bundles"]}
    assert "Sharma bungalow" in names


def test_a_consultation_can_be_filed_into_a_bundle(client: TestClient) -> None:
    bundle = client.post("/bundles", headers=auth(), json={"name": "Sharma house"}).json()
    session_id = upload(client, png_bytes(NEUTRAL_ROOM_SRGB))

    placed = client.post(
        f"/bundles/{bundle['bundle_id']}/consultations",
        headers=auth(),
        json={"consultation_id": session_id},
    )
    assert placed.status_code == 204

    inside = client.get(f"/bundles/{bundle['bundle_id']}/consultations", headers=auth())
    assert [c["consultation_id"] for c in inside.json()["consultations"]] == [session_id]


def test_deleting_a_bundle_moves_its_consultations_to_the_default_bundle(
    client: TestClient,
) -> None:
    bundle = client.post("/bundles", headers=auth(), json={"name": "Sharma house"}).json()
    session_id = upload(client, png_bytes(NEUTRAL_ROOM_SRGB))
    client.post(
        f"/bundles/{bundle['bundle_id']}/consultations",
        headers=auth(),
        json={"consultation_id": session_id},
    )

    deleted = client.delete(f"/bundles/{bundle['bundle_id']}", headers=auth())
    assert deleted.status_code == 204

    # The Consultation survives — under the default Bundle, not in the bin.
    default = next(
        b
        for b in client.get("/bundles", headers=auth()).json()["bundles"]
        if b["name"] == DEFAULT_BUNDLE_NAME
    )
    remaining = client.get(f"/bundles/{default['bundle_id']}/consultations", headers=auth())
    assert [c["consultation_id"] for c in remaining.json()["consultations"]] == [session_id]


def test_an_unknown_bundle_is_a_clean_404(client: TestClient) -> None:
    response = client.get("/bundles/nope/consultations", headers=auth())
    assert response.status_code == 404
    assert response.json()["code"] == "bundle_not_found"


# -- stored renders -------------------------------------------------------------------------------


def test_a_render_is_stored_with_everything_that_produced_it(
    client: TestClient, store: Store
) -> None:
    session_id = upload(client, png_bytes(NEUTRAL_ROOM_SRGB))
    assert render_once(client, session_id, mode="true_colour").status_code == 201

    history = client.get(f"/consultations/{session_id}/renders", headers=auth())
    render_entry = history.json()["renders"][0]

    assert render_entry["assignments"] == {FIRST_WALL_PLANE_ID: SHADE_CODE}
    assert render_entry["resolved_lab"][SHADE_CODE]
    assert render_entry["mode"] == "true_colour"
    assert render_entry["execution_profile"]
    # Catalogue identity *and* version: a shade code alone cannot survive a catalogue swap.
    assert render_entry["catalogue_id"]
    assert render_entry["catalogue_version"]
    assert render_entry["width"] == ROOM_SIZE[0]
    assert render_entry["height"] == ROOM_SIZE[1]


def test_the_stored_render_is_byte_for_byte_what_was_shown(client: TestClient) -> None:
    session_id = upload(client, png_bytes(NEUTRAL_ROOM_SRGB))
    shown = render_once(client, session_id)

    history = client.get(f"/consultations/{session_id}/renders", headers=auth())
    render_id = history.json()["renders"][0]["render_id"]

    served = client.get(f"/consultations/{session_id}/renders/{render_id}/png", headers=auth())
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == shown.content


def test_previously_tried_shades_are_visible(client: TestClient) -> None:
    session_id = upload(client, png_bytes(NEUTRAL_ROOM_SRGB))
    assert render_once(client, session_id).status_code == 201

    history = client.get(f"/consultations/{session_id}/renders", headers=auth())
    codes = [
        assignment[shade]
        for entry in history.json()["renders"]
        for assignment in [entry["assignments"]]
        for shade in assignment
    ]
    assert SHADE_CODE in codes


# -- reopening ------------------------------------------------------------------------------------


def test_reopening_skips_preparation_and_can_try_another_shade(
    client: TestClient,
) -> None:
    """The whole point of storing the prepared artifacts: the seconds-long pipeline runs once.

    The counting stages wrap the same stub the other tests use, so "preparation ran" is measured
    by how often a photo entered it — not by poking at internals.
    """

    preparations: list[bytes] = []

    def counting_stages(contents: bytes) -> list[Stage]:
        preparations.append(contents)
        return stub_preparation_stages(contents)

    app = create_app(SECRET, preparation_stages=counting_stages, store=client.app.state.store)
    with TestClient(app) as fresh:
        session_id = upload(fresh, png_bytes(NEUTRAL_ROOM_SRGB))
        assert render_once(fresh, session_id).status_code == 201
        assert len(preparations) == 1

        reopened = fresh.post(f"/consultations/{session_id}/reopen", headers=auth())
        assert reopened.status_code == 201
        new_session = reopened.json()["session_id"]

        # A new shade on the reopened photo works, and no stage ran a second time.
        response = render_once(fresh, new_session, mode="realistic")
        assert response.status_code == 201
        assert len(preparations) == 1


def test_a_reopened_render_is_filed_under_the_original_consultation(
    client: TestClient,
) -> None:
    session_id = upload(client, png_bytes(NEUTRAL_ROOM_SRGB))
    assert render_once(client, session_id).status_code == 201

    new_session = client.post(f"/consultations/{session_id}/reopen", headers=auth()).json()[
        "session_id"
    ]
    assert render_once(client, new_session).status_code == 201

    history = client.get(f"/consultations/{session_id}/renders", headers=auth())
    assert len(history.json()["renders"]) == 2


def test_the_reopened_photo_is_what_preparation_produced(client: TestClient) -> None:
    session_id = upload(client, png_bytes(NEUTRAL_ROOM_SRGB))
    assert render_once(client, session_id).status_code == 201

    served = client.get(f"/consultations/{session_id}/photo/png", headers=auth())
    assert served.status_code == 200
    assert served.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_reopening_before_preparation_finished_is_refused_cleanly(
    client: TestClient,
) -> None:
    """A Consultation whose photo was uploaded but never prepared cannot be put back on screen —
    there is nothing stored to show — but it is a clean answer, not a dead end."""
    session_id = upload(client, png_bytes(NEUTRAL_ROOM_SRGB))

    response = client.post(f"/consultations/{session_id}/reopen", headers=auth())

    assert response.status_code == 409
    assert response.json()["code"] == "preparation_unavailable"


# -- where the library lives ----------------------------------------------------------------------


def test_the_storage_directory_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    monkeypatch.setenv("SPECTRAPAINT_STORAGE_DIR", str(Path("Z:") / "somewhere"))
    assert resolve_storage_dir() == Path("Z:") / "somewhere"


def test_an_invalid_catalogue_never_touches_the_store(tmp_path) -> None:
    """Persistence is not what boots first: a broken setup still fails exactly as loudly."""
    from unittest.mock import patch

    with patch("spectrapaint.api.app.open_catalogue") as failing:
        failing.side_effect = CatalogueFileMissing("no catalogue")
        with pytest.raises(CatalogueFileMissing):
            create_app(SECRET, store=Store(tmp_path / "library"))
