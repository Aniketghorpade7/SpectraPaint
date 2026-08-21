"""Process entry point: bind a port, announce it, serve.

Run as ``python -m spectrapaint``. Electron spawns this as a child process, reads the handshake
line from stdout to learn the port, and supervises the process for the rest of the launch.

Boot order is deliberate: the secret, then the Catalogue, then the model files, and only then the
port. Everything that can be known to be broken is checked before Electron is told the service is
up, so a setup fault is a boot failure the Dealer is told about rather than a Consultation that
falls over with a Customer at the counter.

Two things are deliberately not configurable:

* **The host.** Always loopback. A flag would eventually get set to 0.0.0.0 by someone debugging,
  and a service holding Customer room photographs would be on the network.
* **Where the secret comes from.** Always the environment, never argv — command lines are readable
  by any other process on the machine (``ps`` on Linux, Task Manager or WMI on Windows), which
  would defeat the point of having a secret at all.
"""

import json
import os
import socket
import sys

import uvicorn

from spectrapaint.api.app import create_app
from spectrapaint.catalogue import CatalogueFileInvalid, CatalogueFileMissing, open_catalogue
from spectrapaint.runtime.graphs import warm_in_background
from spectrapaint.runtime.location import MODELS_DIR_ENV_VAR, ModelsMissing, resolve_models_dir
from spectrapaint.storage import Store, resolve_storage_dir

HOST = "127.0.0.1"
SECRET_ENV_VAR = "SPECTRAPAINT_SECRET"

# Electron scans stdout for this prefix. A sentinel rather than bare JSON, so that a stray log line
# can never be mistaken for the handshake.
HANDSHAKE_PREFIX = "SPECTRAPAINT_HANDSHAKE "

EXIT_NO_SECRET = 2
EXIT_NO_CATALOGUE = 3
EXIT_NO_MODELS = 4


def bind_listening_socket() -> socket.socket:
    """Take an OS-assigned free port on loopback, and start listening immediately.

    Binding to port 0 removes port collision as a failure mode — otherwise it surfaces as an
    install that works on most machines and mysteriously does not on one (docs/design-decisions.md
    §13).

    Listening *before* the handshake is announced is what removes the startup race: connections
    Electron makes after reading the port queue in the backlog even if the server has not finished
    starting, so there is no window in which a correct client can be refused.

    SO_REUSEADDR is deliberately not set. On Windows it does not mean what it means on Linux — it
    permits binding a port another process already holds, which is a hijacking risk for a service
    guarding Customer photographs.
    """

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((HOST, 0))
    listener.listen()
    return listener


def handshake_line(port: int, pid: int) -> str:
    """The one line Electron parses. Keep it a single line, and keep the secret out of it."""

    return HANDSHAKE_PREFIX + json.dumps({"port": port, "pid": pid})


def announce(line: str) -> None:
    # Unbuffered, or the parent waits on a line sitting in a pipe buffer and times out the launch.
    print(line, flush=True)


def read_secret() -> str:
    secret = os.environ.get(SECRET_ENV_VAR, "")
    if not secret:
        print(
            f"{SECRET_ENV_VAR} is not set. The service will not run unauthenticated.",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(EXIT_NO_SECRET)
    return secret


def load_catalogue():
    """The Catalogue, or a clean exit saying why there is none.

    Before the port is announced, deliberately. A service that completes the handshake and then
    cannot answer a single Shade lookup looks healthy to Electron, so the failure would surface as a
    broken panel mid-Consultation instead of as a boot failure the Dealer is told about
    (docs/specs/v1-spectrapaint.md — model load failures surface at boot, not mid-consultation).
    """

    try:
        return open_catalogue()
    except (CatalogueFileMissing, CatalogueFileInvalid) as failure:
        # Both halves: the detail names the file for whoever set the machine up, the message is what
        # the Dealer can be shown (conventions.md §5).
        print(f"{failure.message} ({failure.detail})", file=sys.stderr, flush=True)
        raise SystemExit(EXIT_NO_CATALOGUE) from failure


def check_models() -> None:
    """Refuse to boot a packaged install whose model files are missing or incomplete.

    The same argument the Catalogue makes: a service that completes the handshake and then cannot
    find a wall has turned a setup problem into a Consultation problem, and the spec is explicit
    that model failures surface at boot rather than mid-consultation.

    But absence is only a fault when someone said where the files were. Electron sets
    ``SPECTRAPAINT_MODELS_DIR`` in a packaged app, so a missing file there is a broken install and
    the service stops. In a source checkout nobody has set it and the export may simply not have
    been run yet — the rest of the service is still worth running, and the Dealer-facing failure
    arrives with the first photo that needs a wall, saying so in plain language.
    """

    packaged = bool(os.environ.get(MODELS_DIR_ENV_VAR, "").strip())
    try:
        resolve_models_dir()
    except ModelsMissing as failure:
        if packaged:
            print(f"{failure.message} ({failure.detail})", file=sys.stderr, flush=True)
            raise SystemExit(EXIT_NO_MODELS) from failure
        print(f"note: {failure.detail}", file=sys.stderr, flush=True)


def main() -> None:
    secret = read_secret()
    catalogue = load_catalogue()
    check_models()
    listener = bind_listening_socket()
    port = listener.getsockname()[1]

    announce(handshake_line(port, os.getpid()))

    # After the handshake, deliberately: Electron has the port and is showing its boot screen, and
    # the models load in that window instead of inside the thirty-second per-photo budget
    # (docs/specs/v1-spectrapaint.md, "Performance"). A daemon thread, so a slow load delays the
    # first photo rather than every request.
    warm_in_background()

    config = uvicorn.Config(
        create_app(secret, catalogue, store=Store(resolve_storage_dir())),
        log_level="info",
        # Every request would otherwise be logged with its path; the Dealer's machine has no use
        # for that, and Electron already logs the lifecycle events that matter.
        access_log=False,
    )
    uvicorn.Server(config).run(sockets=[listener])


if __name__ == "__main__":
    main()
