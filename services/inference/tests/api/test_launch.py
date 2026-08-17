"""Seam 1 — lifecycle. Launches the service the way Electron does and talks to it over TCP.

Everything here is cross-platform on purpose: this is the test that catches a handshake or process
problem on Windows, which is the shipping target while development happens on Linux
(docs/design-decisions.md §9c).
"""

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx2 as httpx
import pytest

from spectrapaint.service import HANDSHAKE_PREFIX, HOST, SECRET_ENV_VAR, bind_listening_socket

SERVICE_ROOT = Path(__file__).resolve().parents[2]
SECRET = "launch-test-secret"
STARTUP_TIMEOUT_SECONDS = 30


@pytest.fixture
def service() -> Iterator[tuple[subprocess.Popen[str], int]]:
    process = subprocess.Popen(
        [sys.executable, "-m", "spectrapaint"],
        cwd=SERVICE_ROOT,
        env={**os.environ, SECRET_ENV_VAR: SECRET, "PYTHONPATH": str(SERVICE_ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        yield process, read_announced_port(process)
    finally:
        process.terminate()
        process.wait(timeout=10)


def read_announced_port(process: subprocess.Popen[str]) -> int:
    assert process.stdout is not None
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:
            break
        if line.startswith(HANDSHAKE_PREFIX):
            return int(json.loads(line[len(HANDSHAKE_PREFIX) :])["port"])

    process.kill()
    pytest.fail("The service never announced a port.")


def test_the_service_announces_a_usable_port_and_serves_on_it(
    service: tuple[subprocess.Popen[str], int],
) -> None:
    _, port = service

    response = httpx.get(
        f"http://{HOST}:{port}/health",
        headers={"Authorization": f"Bearer {SECRET}"},
        timeout=STARTUP_TIMEOUT_SECONDS,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_the_running_service_rejects_a_request_without_the_secret(
    service: tuple[subprocess.Popen[str], int],
) -> None:
    _, port = service

    response = httpx.get(f"http://{HOST}:{port}/health", timeout=STARTUP_TIMEOUT_SECONDS)

    assert response.status_code == 401


def test_the_service_will_not_run_without_a_secret() -> None:
    """Refusing to start beats starting unauthenticated."""

    environment = {k: v for k, v in os.environ.items() if k != SECRET_ENV_VAR}
    result = subprocess.run(
        [sys.executable, "-m", "spectrapaint"],
        cwd=SERVICE_ROOT,
        env={**environment, "PYTHONPATH": str(SERVICE_ROOT)},
        capture_output=True,
        text=True,
        timeout=STARTUP_TIMEOUT_SECONDS,
    )

    assert result.returncode != 0
    assert SECRET_ENV_VAR in result.stderr


def test_each_launch_takes_a_different_port_than_one_already_in_use() -> None:
    """Port 0 is what removes collision as a failure mode."""

    first = bind_listening_socket()
    second = bind_listening_socket()
    try:
        assert first.getsockname()[1] != second.getsockname()[1]
    finally:
        first.close()
        second.close()


def test_the_socket_is_reachable_only_on_loopback() -> None:
    listener = bind_listening_socket()
    try:
        bound_host, _ = listener.getsockname()
        assert bound_host == "127.0.0.1"
    finally:
        listener.close()


def test_the_handshake_is_one_line_and_carries_no_secret() -> None:
    from spectrapaint.service import handshake_line

    line = handshake_line(port=51234, pid=999)

    assert "\n" not in line
    assert SECRET not in line
    assert json.loads(line[len(HANDSHAKE_PREFIX) :]) == {"port": 51234, "pid": 999}


def test_a_second_process_cannot_hijack_the_bound_port() -> None:
    """SO_REUSEADDR is not set, so the port stays exclusively ours — Windows would otherwise
    allow another process to bind over it."""

    listener = bind_listening_socket()
    port = listener.getsockname()[1]
    intruder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            intruder.bind((HOST, port))
    finally:
        intruder.close()
        listener.close()
