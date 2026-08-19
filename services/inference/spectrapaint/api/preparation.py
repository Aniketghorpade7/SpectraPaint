"""Photo preparation, as a stream of plain-language progress events.

A photo is prepared once, on upload, in the background. Preparation walks a list of stages; before
each stage runs, its plain-language message is recorded — "Reading your photo…", never "running
inference" (docs/specs/v1-spectrapaint.md, "Progress messaging").

Two properties of this module carry the acceptance criteria of ticket #4:

* **The events are recorded, not just sent.** A client that opens the stream slightly after
  preparation began — or after it finished — replays the log and still sees sensible progress,
  instead of an empty or hanging stream.
* **The stream terminates cleanly.** Every job ends with exactly one terminal event, ``done`` or
  ``failed``, after which the stream closes.

The job runs on a worker thread rather than an asyncio task. Two reasons:

* The work here (Pillow decoding) is CPU-bound C code; on uvicorn's event loop it would stall every
  other request. On its own thread it cannot.
* A thread lives independently of any request's event loop, so the job keeps progressing while
  stream readers come and go — and it is what makes the stream testable: TestClient does not run
  ``asyncio.create_task`` jobs scheduled during one request once that request returns, so an
  event-loop job would never progress under test (docs/technical-difficulties.md).

The stage list is the seam where the model pipeline arrives: ticket #6 (detect walls) adds its
stages here and the work runs in the same machinery — buffering, streaming and termination are
unchanged. Nothing about this module names a model or a technique.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)

# How often a reader re-checks the job for new events. The first event lands within one poll of
# work starting; the terminal within one poll of work ending. Localhost, one reader: imperceptible.
POLL_INTERVAL_SECONDS = 0.05

# Shown as-is when preparation fails — plain language, and an action the Dealer can take.
MESSAGE_PREPARATION_FAILED = "That photo could not be read. Please try another photo."


@dataclass(frozen=True)
class Stage:
    """One step of preparation: the message shown while it runs, and the work itself."""

    message: str
    run: Callable[[], None]


class PreparationJob:
    """One photo's background preparation.

    Runs its stages on a worker thread, recording a progress event before each one, and finishes
    with exactly one terminal event. Events stay recorded for the life of the session, so any
    stream that connects — early, mid-preparation, or after completion — sees the same sensible
    progress.
    """

    def __init__(self, stages: list[Stage]) -> None:
        self._stages = stages
        self._events: list[dict[str, str]] = []
        self._terminal: dict[str, str] | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name="spectrapaint-preparation",
            daemon=True,
        )

    def start(self) -> None:
        """Begin preparation. Called once, by the session that owns the job."""
        self._thread.start()

    def _run(self) -> None:
        for stage in self._stages:
            with self._lock:
                self._events.append({"phase": "progress", "message": stage.message})
            try:
                stage.run()
            except Exception:
                # A photo that cannot be prepared fails this job, not the stream: the reader hears
                # one terminal 'failed' event and the stream closes, like a 'done' would.
                logger.warning("Photo preparation failed", exc_info=True)
                with self._lock:
                    self._terminal = {"phase": "failed", "message": MESSAGE_PREPARATION_FAILED}
                return

        with self._lock:
            self._terminal = {"phase": "done"}

    async def stream(self) -> AsyncIterator[dict[str, str]]:
        """Every recorded event, then each new one as it lands, then the terminal event.

        Each reader tracks its own position, so several streams against one session (and a reader
        that joins late) all behave independently. The lock is dropped before yielding, so a slow
        reader cannot hold up the job that is feeding it.
        """

        index = 0
        while True:
            with self._lock:
                pending = self._events[index:]
                terminal = self._terminal
                index = len(self._events)

            for event in pending:
                yield event
            if terminal is not None:
                yield terminal
                return

            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def build_preparation_stages(contents: bytes) -> list[Stage]:
    """The photo-preparation steps, in order.

    Today, one stage: decode the photo's pixels. The upload's structural check (``verify()``) does
    not decode — a JPEG with its end-of-image marker stripped passes it — so this is the first place
    a photo that only *looks* valid is actually read, and it fails preparation cleanly rather than
    somewhere downstream (docs/design-decisions.md §13, "Start on photo load"). Later tickets add
    their stages to this list.
    """

    return [Stage(message="Reading your photo…", run=lambda: _decode_pixels(contents))]


def _decode_pixels(contents: bytes) -> None:
    image = Image.open(io.BytesIO(contents))
    image.load()