"""Seam 1 — the Catalogue over the contract.

Behaviour only: what a Dealer can find, in what order, and what happens when they cannot. How the
service indexes or ranks it is implementation and is asserted nowhere here — a test that survives
swapping SQLite for something else is a test worth keeping (docs/conventions.md §6).
"""

import json

import pytest
from fastapi.testclient import TestClient

from spectrapaint.api.app import create_app
from spectrapaint.catalogue import open_catalogue

SECRET = "test-secret-not-a-real-one"


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {SECRET}"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(SECRET))


# -- what Catalogue is loaded ---------------------------------------------------------------


def test_the_catalogue_says_what_it_is(client: TestClient) -> None:
    """Every Render records the Catalogue's identity and version, so the contract has to serve
    them (docs/design-decisions.md §7)."""

    body = client.get("/catalogue", headers=auth()).json()

    assert body["catalogue_id"]
    assert body["catalogue_name"]
    assert body["version"]
    assert body["shade_count"] > 1000


def test_the_catalogue_can_be_browsed_by_shade_family(client: TestClient) -> None:
    body = client.get("/catalogue", headers=auth()).json()

    families = body["shade_families"]
    assert len(families) > 1
    assert sum(family["shade_count"] for family in families) == body["shade_count"]
    assert all(family["shade_family"] and family["shade_count"] > 0 for family in families)


def test_the_catalogue_requires_the_secret_like_everything_else(client: TestClient) -> None:
    assert client.get("/catalogue").status_code == 401
    assert client.get("/catalogue/shades").status_code == 401
    assert client.get("/catalogue/shades/PS-1001").status_code == 401


# -- searching ------------------------------------------------------------------------------


def test_a_shade_code_finds_exactly_that_shade(client: TestClient) -> None:
    """The primary path: the Customer points at a chip and reads out the code."""

    known = client.get("/catalogue/shades", params={"limit": 1}, headers=auth()).json()["shades"][0]

    response = client.get(f"/catalogue/shades/{known['shade_code']}", headers=auth())

    assert response.status_code == 200
    assert response.json() == known


def test_a_shade_code_is_found_whatever_case_it_is_typed(client: TestClient) -> None:
    known = client.get("/catalogue/shades", params={"limit": 1}, headers=auth()).json()["shades"][0]
    code = known["shade_code"]

    assert client.get(f"/catalogue/shades/{code.lower()}", headers=auth()).json() == known
    assert client.get(f"/catalogue/shades/{code.upper()}", headers=auth()).json() == known


def test_an_unknown_shade_code_says_what_to_do_next(client: TestClient) -> None:
    """Never a dead end (docs/conventions.md §5): the message leaves the Dealer somewhere to go."""

    response = client.get("/catalogue/shades/NOT-A-CODE", headers=auth())

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "shade_not_found"
    assert body["message"]
    assert not any(word in body["message"].lower() for word in ("sqlite", "index", "query", "null"))


def test_searching_by_code_puts_the_exact_match_first(client: TestClient) -> None:
    known = client.get("/catalogue/shades", params={"limit": 1}, headers=auth()).json()["shades"][0]

    body = client.get("/catalogue/shades", params={"q": known["shade_code"]}, headers=auth()).json()

    assert body["searched"] is True
    assert body["shades"][0]["shade_code"] == known["shade_code"]


def test_searching_by_name_works_on_partial_input(client: TestClient) -> None:
    """A Customer half-remembers a name; the Dealer types the half they got."""

    known = client.get("/catalogue/shades", params={"limit": 1}, headers=auth()).json()["shades"][0]
    fragment = known["name"].split()[-1][:4]

    body = client.get("/catalogue/shades", params={"q": fragment}, headers=auth()).json()

    assert body["shades"], f"nothing matched {fragment!r}"
    assert all(
        fragment.lower() in shade["name"].lower() or fragment.lower() in shade["shade_code"].lower()
        for shade in body["shades"]
    )


def test_a_search_matching_nothing_is_an_empty_answer_not_an_error(client: TestClient) -> None:
    response = client.get("/catalogue/shades", params={"q": "zzzzzzzz"}, headers=auth())

    assert response.status_code == 200
    assert response.json()["shades"] == []


def test_paging_a_search_is_refused_rather_than_silently_ignored(client: TestClient) -> None:
    """A caller paging a search would get a ranking where it expected a page, with nothing in the
    response to reveal it."""

    response = client.get("/catalogue/shades", params={"q": "linen", "offset": 20}, headers=auth())

    assert response.status_code == 422
    assert response.json()["code"] == "malformed_request"


# -- browsing -------------------------------------------------------------------------------


def test_browsing_returns_a_page_and_the_true_total(client: TestClient) -> None:
    """The virtualised list sizes its scrollbar from the total before it has the rows."""

    body = client.get("/catalogue/shades", params={"limit": 10}, headers=auth()).json()

    assert len(body["shades"]) == 10
    assert body["total"] > 1000
    assert body["searched"] is False


def test_browsing_a_family_returns_only_that_family(client: TestClient) -> None:
    family = client.get("/catalogue", headers=auth()).json()["shade_families"][2]

    body = client.get(
        "/catalogue/shades",
        params={"shade_family": family["shade_family"], "limit": 500},
        headers=auth(),
    ).json()

    assert body["total"] == family["shade_count"]
    assert {shade["shade_family"] for shade in body["shades"]} == {family["shade_family"]}


def test_pages_do_not_overlap_or_skip_a_shade(client: TestClient) -> None:
    first = client.get("/catalogue/shades", params={"limit": 50}, headers=auth()).json()
    second = client.get(
        "/catalogue/shades", params={"limit": 50, "offset": 50}, headers=auth()
    ).json()

    codes = [shade["shade_code"] for shade in first["shades"] + second["shades"]]
    assert len(codes) == len(set(codes)) == 100


def test_a_page_larger_than_the_ceiling_is_refused(client: TestClient) -> None:
    """One request cannot make the service serialise the whole Catalogue."""

    response = client.get("/catalogue/shades", params={"limit": 100_000}, headers=auth())

    assert response.status_code == 422
    assert response.json()["code"] == "malformed_request"


# -- what a swatch needs ----------------------------------------------------------------------


def test_every_shade_carries_what_a_swatch_must_show(client: TestClient) -> None:
    """Shade Code prominently, a colour to draw, and Finish as metadata beside it."""

    shades = client.get("/catalogue/shades", params={"limit": 100}, headers=auth()).json()["shades"]

    for shade in shades:
        assert shade["shade_code"]
        assert shade["name"]
        assert shade["shade_family"]
        assert 0 <= shade["lab"]["l"] <= 100
        assert -128 <= shade["lab"]["a"] <= 127
        assert -128 <= shade["lab"]["b"] <= 127
        assert isinstance(shade["finishes"], list)


def test_finishes_are_metadata_and_no_endpoint_renders_with_them(client: TestClient) -> None:
    """Finish does not affect the render in V1 (docs/design-decisions.md §8), and the contract
    offers nowhere to send one."""

    paths = {route.path for route in client.app.routes if getattr(route, "methods", None)}

    assert not any("finish" in path for path in paths)


# -- swapping the Catalogue --------------------------------------------------------------------


def test_swapping_the_data_file_changes_the_catalogue_with_no_code_change(tmp_path) -> None:
    """The acceptance criterion, end to end: a different file, the same service, different Shades.

    This is the one that matters commercially — Arun Paint Industries' measured values arrive as a
    file, and nothing in the app is allowed to need editing when they do.
    """

    swapped = tmp_path / "another-manufacturer-2027-01.json"
    swapped.write_text(
        json.dumps(
            {
                "catalogue_id": "another-manufacturer",
                "catalogue_name": "Another Manufacturer",
                "version": "2027-01",
                "colour_space": {"space": "CIELAB", "reference_white": "D65", "observer": "2"},
                "shades": [
                    {
                        "shade_code": "AM-0001",
                        "name": "Counter Grey",
                        "shade_family": "Greys",
                        "lab": {"l": 60.0, "a": 0.0, "b": 0.0},
                        "finishes": ["matte"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    client = TestClient(
        create_app(SECRET, open_catalogue({"SPECTRAPAINT_CATALOGUE_FILE": str(swapped)}))
    )

    metadata = client.get("/catalogue", headers=auth()).json()
    assert metadata["catalogue_id"] == "another-manufacturer"
    assert metadata["shade_count"] == 1
    assert metadata["shade_families"] == [{"shade_family": "Greys", "shade_count": 1}]

    assert client.get("/catalogue/shades/AM-0001", headers=auth()).status_code == 200
    # A code from the Catalogue that is no longer loaded is simply not there.
    assert client.get("/catalogue/shades/PS-1001", headers=auth()).status_code == 404
