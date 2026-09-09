"""Photo preparation, as a stream of plain-language progress events.

A photo is prepared once, on upload, in the background. Preparation walks a list of stages; before
each stage runs, its plain-language message is recorded — "Reading your photo…", never "running
inference" (docs/specs/v1-spectrapaint.md, "Progress messaging").

Three properties of this module carry the acceptance criteria of tickets #4 and #6:

* **The events are recorded, not just sent.** A client that opens the stream slightly after
  preparation began — or after it finished — replays the log and still sees sensible progress,
  instead of an empty or hanging stream.
* **The stream terminates cleanly.** Every job ends with exactly one terminal event, ``done`` or
  ``failed``, after which the stream closes.
* **Preparation begins when the photo loads, not when a render is requested.** Finding the walls is
  part of *this* list, so it happens while the Dealer is still looking at the progress messages
  rather than when a Shade is first tapped.

Issue #3 added the fourth property: **the render path reads what preparation produced.** The last
stage returns the ``PreparedPhoto`` — the photo, and the Wall Planes found in it — and the job keeps
it; ``POST /sessions/{id}/renders`` waits for preparation and renders from that, never from the
upload bytes.

The job runs on a worker thread rather than an asyncio task. Two reasons:

* The work here (Pillow decoding, numpy linearisation, ONNX inference) is CPU-bound C code; on
  uvicorn's event loop it would stall every other request. On its own thread it cannot.
* A thread lives independently of any request's event loop, so the job keeps progressing while
  stream readers come and go — and it is what makes the stream testable: TestClient does not run
  ``asyncio.create_task`` jobs scheduled during one request once that request returns, so an
  event-loop job would never progress under test (docs/technical-difficulties.md).

Ticket #6 filled in the seam this module was built around: the stage list now runs the real model
pipeline, and buffering, streaming and termination are unchanged, exactly as §12 of
docs/implementation-decisions.md predicted. Nothing here still names a model or a technique — the
stages call :mod:`spectrapaint.segmentation`, which owns all of that.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace

import numpy as np

import numpy as np
from PIL import Image

from spectrapaint.quality import assess_quality
from spectrapaint.render.luts import linearise_u8
from spectrapaint.runtime.graphs import load as load_graphs
from spectrapaint.runtime.location import ModelsMissing
from spectrapaint.segmentation.matte import RefinerFeatures, encode_photo
from spectrapaint.segmentation.semantic import SemanticRegions
from spectrapaint.segmentation.walls import (
    CEILING_PLANE_ID,
    NoWallFound,
    WallPlane,
    ceiling_from,
    get_regions,
    planes_from,
    wall_regions,
)

logger = logging.getLogger(__name__)

# How often a reader re-checks the job for new events. The first event lands within one poll of
# work starting; the terminal within one poll of work ending. Localhost, one reader: imperceptible.
POLL_INTERVAL_SECONDS = 0.05

# Shown as-is when preparation fails for a reason with no better message of its own — a file that
# cannot be decoded at all.
MESSAGE_PREPARATION_FAILED = "That photo could not be read. Please try another photo."

# The prepared photo is capped on its long side so the in-memory working image stays at preview
# scale — docs/specs/v1-spectrapaint.md, "Performance": full-resolution renders are a later ticket;
# the ~1 MP preview is the per-tap path while browsing. 1280 px at 16:9 is ~0.9 MP.
MAX_PREPARED_DIMENSION = 1280


@dataclass(frozen=True)
class Stage:
    """One step of preparation: the message shown while it runs, and the work itself.

    ``run`` may return a ``PreparedPhoto``, which the job keeps for the render path to read
    (issue #3's encode-once rule). A stage that returns anything else — including ``None``, which
    most stages do — leaves the kept photo alone. That rule, rather than "the last value wins",
    is what lets tickets #7–#8 append stages without silently emptying the render path.
    """

    message: str
    run: Callable[[], object | None]


@dataclass(frozen=True)
class DecodedPhoto:
    """The photo itself, in the two forms the rest of preparation needs.

    Both, rather than one and a conversion: the models and the edge-aware refinement want ordinary
    8-bit sRGB, because that is what they were trained on and what "where a human sees an edge"
    means; the render engine wants linear light, because that is where the light maths is valid
    (spec, "Colour management"). Converting between them on demand would mean doing it repeatedly,
    per photo, for no gain.
    """

    srgb: np.ndarray  # HxWx3 uint8, at preview scale
    linear: np.ndarray  # HxWx3 float32, linear RGB, same size


@dataclass(frozen=True)
class PreparedPhoto:
    """The once-per-photo work the render path consumes (issue #3's encode-once rule).

    ``planes`` may be empty: since ticket #10, finding no wall automatically is not a preparation
    failure — the photo is still ready, ``note`` carries why in plain language, and the Dealer taps
    a wall in through the correction surface, the same one merge and split use. ``features`` is the
    photo's already-encoded SAM 2 output, held here so that surface can decode a new prompt without
    paying the encode again — present whenever the semantic pass found a plausible wall region to
    encode, ``None`` on the rarer photo where it found nothing at all to work from, in which case
    the first correction on that session pays the encode once, itself, on demand.
    """

    linear: np.ndarray  # HxWx3 float32, linear RGB at preview scale
    srgb: np.ndarray  # HxWx3 uint8, the same photo as the Dealer sees it
    planes: tuple[WallPlane, ...]  # every Wall Plane found, in a stable order — possibly none
    note: str | None = None  # plain language, set exactly when planes is empty because none found
    # Plain language, set when the photo itself is dark, blurred or heavily clipped
    # (spectrapaint.quality) — never a reason to refuse it (issue #15, "never dead-end"), and
    # independent of `note`: a poor photo can still have a perfectly findable wall.
    quality_note: str | None = None
    features: RefinerFeatures | None = None  # SAM 2's encoder output; None if never encoded

    def plane(self, plane_id: str) -> WallPlane | None:
        """The Wall Plane with this id, or None if the photo has no such plane."""
        for plane in self.planes:
            if plane.plane_id == plane_id:
                return plane
        return None


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
        # What preparation produced, and — since ticket #10 — the session's live record: a
        # correction replaces this with `dataclasses.replace(self._result, ...)` rather than
        # re-running preparation, so `photo()` keeps returning the *current* Wall Planes (and, if
        # a correction had to encode SAM 2's features on demand, the cached result of that too)
        # without a second field to keep in sync with this one.
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

    @classmethod
    def completed(cls, photo: PreparedPhoto) -> PreparationJob:
        """A job whose work is already done — the shape a reopened Consultation arrives in.

        Reopening (issue #11) loads the photo and Alpha Mattes stored when preparation first ran,
        so there is no thread and no stage list: the stream replays exactly one ``done`` event and
        the render path reads the photo immediately. That is the whole reason "try another Shade"
        on a reopened photo skips preparation.
        """

        job = cls([])
        job._events = []
        job._terminal = {"phase": "done"}
        job._result = photo
        return job

    def _run(self) -> None:
        for stage in self._stages:
            with self._lock:
                self._events.append({"phase": "progress", "message": stage.message})
            try:
                produced = stage.run()
            except Exception as failure:
                # A photo that cannot be prepared fails this job, not the stream: the reader hears
                # one terminal 'failed' event and the stream closes, like a 'done' would.
                #
                # This is for faults preparation did not anticipate — a missing model directory is
                # the live example (runtime/location.ModelsMissing). "No wall could be found" is
                # deliberately not one of them since ticket #10: that is caught inside the stage
                # itself and turned into a note on an otherwise-ready photo, never a failure here —
                # see build_preparation_stages. The message is the failure's own where it has one,
                # because a fault the Dealer can act on differently deserves to say so distinctly
                # (conventions.md §5); anything without one gets the generic message rather than a
                # stack trace.
                logger.warning("Photo preparation failed", exc_info=True)
                message = getattr(failure, "message", None)
                with self._lock:
                    self._terminal = {
                        "phase": "failed",
                        "message": message
                        if isinstance(message, str)
                        else MESSAGE_PREPARATION_FAILED,
                    }
                return

            # Kept by type, never by position: a later stage returning None must not discard the
            # photo an earlier one produced (see Stage).
            if isinstance(produced, PreparedPhoto):
                with self._lock:
                    self._result = produced

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

    async def photo(self) -> PreparedPhoto | None:
        """The session's prepared photo, once preparation is over.

        Replays the event stream to its terminal event — the same ``done``/``failed`` a reader
        sees — then returns the photo a stage produced, or None if preparation failed before one
        did. Waiting here rather than returning "not ready" keeps the render contract simple: a
        render requested during preparation is served once the photo exists, not refused.
        """

        async for _ in self.stream():
            pass

        with self._lock:
            result = self._result
        return result if isinstance(result, PreparedPhoto) else None

    def replace_planes(self, planes: tuple[WallPlane, ...]) -> None:
        """Record the plane list after a correction (ticket #10's add/merge/split).

        Preparation is not re-run: this only ever changes what a later ``photo()`` returns, so a
        render requested afterwards sees the corrected walls without paying preparation's cost
        again. A no-op if called before preparation has produced a photo — no correction endpoint
        does that, since each goes through ``require_photo`` (sessions.py) first, same as every
        other route that touches a session.
        """

        with self._lock:
            if isinstance(self._result, PreparedPhoto):
                self._result = replace(self._result, planes=planes)

    def cache_features(self, features: RefinerFeatures) -> None:
        """Record a SAM 2 encode a correction had to run itself, so a later correction on this
        same session reuses it instead of paying the encoder again.

        Only reached for a session whose semantic pass found no plausible wall region at all —
        preparation already caches the encode for every other session (difficulty 21). A no-op
        under the same "preparation must already have produced a photo" rule as ``replace_planes``.
        """

        with self._lock:
            if isinstance(self._result, PreparedPhoto):
                self._result = replace(self._result, features=features)


@dataclass
class _Workspace:
    """What one photo's stages hand to each other.

    A stage's ``run`` takes no arguments by design — the job calls them in order and keeps only the
    ``PreparedPhoto`` — so the intermediate results of a multi-stage pipeline need somewhere to
    live. This is that somewhere, private to one call of :func:`build_preparation_stages`, which is
    why the stages can be plain closures and the job needs to know nothing about the pipeline's
    shape.
    """

    decoded: DecodedPhoto | None = None
    regions: SemanticRegions | None = None
    planes: tuple[WallPlane, ...] = field(default_factory=tuple)
    features: RefinerFeatures | None = None
    # Set exactly when a stage caught NoWallFound instead of raising it further — the one thing
    # that lets find_the_edges tell "nothing found, legitimately" apart from "look_at_the_room did
    # not run at all", which is the ordering bug photo() already guards for the decode stage.
    note: str | None = None
    # The photo's own quality note (spectrapaint.quality), set once the decode stage has pixels to
    # judge. Independent of `note` above: a dark or blurry photo can still have a findable wall.
    quality_note: str | None = None

    def photo(self) -> DecodedPhoto:
        """The decoded photo, or a plain failure if the stage that decodes it did not run.

        A `RuntimeError` rather than an assertion: assertions vanish under `-O`, and a stage order
        this code depends on should not be checked only in some builds.
        """
        if self.decoded is None:
            raise RuntimeError("the decode stage did not run before the stages that need it")
        return self.decoded


def build_preparation_stages(contents: bytes) -> list[Stage]:
    """The photo-preparation steps, in order.

    Four stages, and the split is by what the Dealer is waiting for rather than by what the code
    does: decoding is quick, the semantic pass and the refiner are the seconds-long ones, and the
    last is short. A single "Preparing your photo…" covering all four would leave the longest wait
    in the Consultation with no sign of progress.

    The upload's structural check (``verify()``) does not decode — a JPEG with its end-of-image
    marker stripped passes it — so the first stage is the first place a photo that only *looks*
    valid is actually read, and it fails preparation cleanly rather than somewhere downstream
    (docs/design-decisions.md §13, "Start on photo load").

    Automatic detection finding no wall is deliberately **not** one of the ways this can fail
    (ticket #10). ``NoWallFound`` is caught inside the two stages that can raise it, and turned into
    ``workspace.note`` instead — preparation still reaches ``done`` with an empty ``planes``, which
    is what lets the Consultation surface land the Dealer on the correction surface's Add tool
    rather than a dead end (conventions.md §5, design-decisions.md "never dead-end").
    """

    workspace = _Workspace()

    def decode() -> None:
        workspace.decoded = decode_photo(contents)
        # Judged here, once, on the pixels every later stage also works from — never a reason to
        # fail preparation (spectrapaint.quality, issue #15).
        workspace.quality_note = assess_quality(workspace.decoded.srgb)

    def look_at_the_room() -> None:
        # Keep the full semantic regions even when no wall is worth offering — a ceiling may still be
        # present (a photo cropped to the ceiling). The wall threshold is checked but the regions are
        # retained for the ceiling pass.
        try:
            regions = get_regions(load_graphs(), workspace.photo().srgb)
            workspace.regions = regions
            if regions.wall_fraction < 0.02:
                raise NoWallFound(
                    f"the semantic pass labelled {regions.wall_fraction:.1%} of the photo as wall, "
                    f"below the 2% needed"
                )
        except NoWallFound as failure:
            workspace.note = failure.message
            # regions already stored if get_regions succeeded; only a load failure leaves it None

    def find_the_edges() -> None:
        photo = workspace.photo()

        if workspace.regions is None:
            if workspace.note is None:
                raise RuntimeError("the semantic stage did not run before the refinement stage")
            # The semantic pass could not be run at all (missing models) or found nothing at all.
            # Encoding would be wasteful and SAM 2 was never tested against "nothing here".
            return

        graphs = load_graphs()
        workspace.features = encode_photo(graphs, photo.srgb)
        # Wall planes — may be empty if nothing wall-like survived refinement, but that is not a
        # failure that blocks the ceiling attempt.
        try:
            found = planes_from(graphs, photo.srgb, workspace.regions, workspace.features)
            workspace.planes = tuple(found)
        except NoWallFound as failure:
            workspace.note = failure.message
            workspace.planes = ()
        # Ceiling — at most one, no splitting. Cheap ~120 ms decode against already-cached features.
        try:
            ceiling = ceiling_from(graphs, photo.srgb, workspace.regions, workspace.features)
        except Exception:
            ceiling = None
        if ceiling is not None:
            # Ensure wall and ceiling do not double-claim pixels where both mattes are confident.
            if workspace.planes:
                wall_max = None
                for plane in workspace.planes:
                    if wall_max is None:
                        wall_max = plane.alpha[..., 0].copy()
                    else:
                        wall_max = np.maximum(wall_max, plane.alpha[..., 0])
                if wall_max is not None:
                    wins = ceiling.alpha[..., 0] >= wall_max
                    confident_wall = wall_max >= 0.5
                    resolved = np.where(confident_wall & ~wins, 0.0, ceiling.alpha[..., 0]).astype(np.float32)
                    ceiling = WallPlane(
                        plane_id=ceiling.plane_id, alpha=resolved[..., None], surface="ceiling"
                    )
                    if float(resolved.mean()) < 0.02:
                        ceiling = None
            if ceiling is not None:
                workspace.planes = (*workspace.planes, ceiling)
                # If we now have at least one plane, clear a stale "no wall found" note — the photo
                # does have something paintable (a ceiling).
                if workspace.planes:
                    workspace.note = None

    def prepared() -> PreparedPhoto:
        photo = workspace.photo()
        return PreparedPhoto(
            linear=photo.linear,
            srgb=photo.srgb,
            planes=workspace.planes,
            note=workspace.note,
            quality_note=workspace.quality_note,
            features=workspace.features,
        )

    return [
        Stage(message="Reading your photo…", run=decode),
        Stage(message="Looking at the room…", run=look_at_the_room),
        Stage(message="Finding the edges of the walls…", run=find_the_edges),
        Stage(message="Getting the walls ready…", run=prepared),
    ]


def decode_photo(contents: bytes) -> DecodedPhoto:
    """Decode, downscale to preview scale, and linearise.

    This is the once-per-photo work the render path never repeats. Downscaling happens before
    linearisation so the LUT input is the actual working pixel data, exactly as the preview-sized
    render will consume it.
    """

    with Image.open(io.BytesIO(contents)) as image:
        rgb = image.convert("RGB")
        if max(rgb.size) > MAX_PREPARED_DIMENSION:
            scale = MAX_PREPARED_DIMENSION / max(rgb.size)
            rgb = rgb.resize(
                (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))),
                resample=Image.Resampling.LANCZOS,
            )
        photo_u8 = np.ascontiguousarray(np.asarray(rgb, dtype=np.uint8))

    linear = np.ascontiguousarray(linearise_u8(photo_u8), dtype=np.float32)
    return DecodedPhoto(srgb=photo_u8, linear=linear)


__all__ = [
    "MESSAGE_PREPARATION_FAILED",
    "ModelsMissing",
    "NoWallFound",
    "DecodedPhoto",
    "PreparationJob",
    "PreparedPhoto",
    "Stage",
    "build_preparation_stages",
    "decode_photo",
]
