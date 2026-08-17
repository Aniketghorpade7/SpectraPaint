"""Seam 1 — the REST contract. Behaviour and lifecycle, never implementation.

docs/conventions.md §6: a test here must survive swapping the semantic model or restructuring
internals. What the contract returns is behaviour; how it decides is not.
"""

import pytest
from fastapi.testclient import TestClient

from spectrapaint.api.app import create_app

SECRET = "test-secret-not-a-real-one"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(SECRET))


def auth(secret: str = SECRET) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def test_health_reports_ready_when_the_secret_is_correct(client: TestClient) -> None:
    response = client.get("/health", headers=auth())

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_request_without_the_secret_is_rejected(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorised"


def test_request_with_the_wrong_secret_is_rejected(client: TestClient) -> None:
    response = client.get("/health", headers=auth("wrong-secret"))

    assert response.status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": SECRET},  # bare, no scheme
        {"Authorization": f"Basic {SECRET}"},  # wrong scheme
        {"Authorization": "Bearer "},  # empty
        {"X-Secret": SECRET},  # right value, wrong header
    ],
)
def test_the_secret_must_be_a_bearer_authorization_header(
    client: TestClient, header: dict[str, str]
) -> None:
    assert client.get("/health", headers=header).status_code == 401


def test_a_rejection_never_reveals_whether_the_secret_was_missing_or_wrong(
    client: TestClient,
) -> None:
    """A caller learns only that it failed — the two responses are indistinguishable."""

    missing = client.get("/health")
    wrong = client.get("/health", headers=auth("wrong-secret"))

    assert missing.status_code == wrong.status_code
    assert missing.json() == wrong.json()


def test_a_rejection_carries_a_message_the_ui_may_show_as_is(client: TestClient) -> None:
    """docs/conventions.md §5: never dead-end, and name no model or technique."""

    body = client.get("/health").json()

    assert set(body) == {"code", "message"}
    assert body["message"]
    assert not any(word in body["message"].lower() for word in ("sam", "onnx", "token", "http"))


def test_the_service_refuses_to_start_without_a_secret() -> None:
    with pytest.raises(ValueError):
        create_app("")
