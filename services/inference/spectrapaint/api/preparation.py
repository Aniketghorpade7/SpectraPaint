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

Issue #3 adds the third property: **the render path reads what preparation produced.** The stage
returns the ``PreparedPhoto`` — decode, downscale, linearise and the stub Wall Plane matte — and
the job keeps it; ``POST /sessions/{id}/renders`` waits for preparation and renders from that
photo, never from the upload bytes.

The job runs on a worker thread rather than an asyncio task. Two reasons:

* The work here (Pillow decoding, numpy linearisation) is CPU-bound C code; on uvicorn's event
  loop it would stall every other request. On its own thread it cannot.
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

import numpy as np
from PIL import Image

from spectrapaint.render.luts import linearise_u8

logger = logging.getLogger(__name__)

# How often a reader re-checks the job for new events. The first event lands within one poll of
# work starting; the terminal within one poll of work ending. Localhost, one reader: imperceptible.
POLL_INTERVAL_SECONDS = 0.05

# Shown as-is when preparation fails — plain language, and an action the Dealer can take.
MESSAGE_PREPARATION_FAILED = "That photo could not be read. Please try another photo."

# The prepared photo is capped on its long side so the in-memory working image stays at preview
# scale (~1.3 MP) -- docs/specs/v1-spectrapaint.md Performance: full-resolution renders are a later
# ticket; the ~1 MP preview is the per-tap path while browsing. 1280 px at 16:9 is ~0.9 MP.
MAX_PREPARED_DIMENSION = 1280

# Stub Wall Plane geometry, decided in docs/design-decisions.md S14: a centred rectangle covering
# 60% x 55% of the photo, with a soft edge band. The segmentation tickets replace the rectangle;
# the shape of the alpha map (HxWx1 float [0, 1]) is the contract that stays.
_STUB_WIDTH_FRACTION = 0.60
_STUB_HEIGHT_FRACTION = 0.55
_STUB_SOFT_BAND_FRACTION = 0.03


@dataclass(frozen=True)
class Stage:
    """One step of preparation: the message shown while it runs, and the work itself.

    ``run`` may return a value; the last returned value becomes the job's result — the render path
    reads the ``PreparedPhoto`` the single stage produces (issue #3's encode-once rule).
    """

    message: str
    run: Callable[[], object | None]


@dataclass(frozen=True)
class PreparedPhoto:
    """The once-per-photo work the render path consumes (issue #3's encode-once rule)."""

    linear: np.ndarray  # HxWx3 float32, linear RGB at preview scale
    wall_alpha: np.ndarray  # HxWx1 float32, the stub Wall Plane matte in [0, 1]


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
        self._result: object | None = None
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
        result: object | None = None
        for stage in self._stages:
            with self._lock:
                self._events.append({"phase": "progress", "message": stage.message})
            try:
                result = stage.run()
            except Exception:
                # A photo that cannot be prepared fails this job, not the stream: the reader hears
                # one terminal 'failed' event and the stream closes, like a 'done' would.
                logger.warning("Photo preparation failed", exc_info=True)
                with self._lock:
                    self._terminal = {"phase": "failed", "message": MESSAGE_PREPARATION_FAILED}
                return

        with self._lock:
            self._result = result
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

    async def photo(self) -> PreparedPhoto | None:
        """The session's prepared photo, once preparation is over.

        Replays the event stream to its terminal event — the same ``done``/``failed`` a reader
        sees — then returns the photo the stage produced, or None if preparation failed.
        """

        async for _ in self.stream():
            pass

        with self._lock:
            result = self._result
        return result if isinstance(result, PreparedPhoto) else None


def build_preparation_stages(contents: bytes) -> list[Stage]:
    """The photo-preparation steps, in order.

    One stage: decode the photo's pixels and build the prepared photo the render path consumes.
    The upload's structural check (``verify()``) does not decode — a JPEG with its end-of-image
    marker stripped passes it — so this is the first place a photo that only *looks* valid is
    actually read, and it fails preparation cleanly rather than somewhere downstream
    (docs/design-decisions.md §13, "Start on photo load"). Later tickets add their stages to this
    list.
    """

    return [Stage(message="Reading your photo…", run=lambda: prepare_photo(contents))]


def prepare_photo(contents: bytes) -> PreparedPhoto:
    """Decode, downscale to preview scale, linearise, and build the stub Wall Plane matte.

    This is the once-per-photo preparation; the render path never repeats it. Downscaling happens
    before linearisation so the LUT input is the actual working pixel data, exactly as the
    preview-sized render will consume it.
    """

    with Image.open(io.BytesIO(contents)) as image:
        rgb = image.convert("RGB")
        if max(rgb.size) > MAX_PREPARED_DIMENSION:
            scale = MAX_PREPARED_DIMENSION / max(rgb.size)
            rgb = rgb.resize(
                (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))),
                resample=Image.Resampling.LANCZOS,
            )
        photo_u8 = np.asarray(rgb, dtype=np.uint8)

    linear = np.ascontiguousarray(linearise_u8(photo_u8), dtype=np.float32)
    return PreparedPhoto(linear=linear, wall_alpha=_stub_wall_alpha(linear.shape[:2]))


def _stub_wall_alpha(shape: tuple[int, int]) -> np.ndarray:
    """The stub Wall Plane matte: a centred, soft-edged rectangle in [0, 1].

    Replaced by the real segmentation mattes; its shape is the contract that stays. Edge band is
    a linear ramp so the alpha composite stays clean in linear space (issue #3 criterion 2).
    """

    height, width = shape
    rect_w = max(1, round(width * _STUB_WIDTH_FRACTION))
    rect_h = max(1, round(height * _STUB_HEIGHT_FRACTION))
    band = max(1, round(min(width, height) * _STUB_SOFT_BAND_FRACTION))

    left = (width - rect_w) // 2
    right = left + rect_w
    top = (height - rect_h) // 2
    bottom = top + rect_h

    x = np.arange(width, dtype=np.float32)
    y = np.arange(height, dtype=np.float32)

    # Distance to the rectangle edge, in pixels, positive inside. Then alpha ramps from 0 at
    # ``edge - band`` to 1 at ``edge``, and is fully 1 in the interior.
    from_left = np.minimum(np.minimum(x[None, :] - left, right - x[None, :]), band) / band
    from_top = np.minimum(np.minimum(y[:, None] - top, bottom - y[:, None]), band) / band
    return np.clip(np.minimum(from_left, from_top), 0.0, 1.0)[..., None].astype(np.float32)
