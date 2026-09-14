"""Loading the exported graphs, and warming them before a Customer is waiting.

What lives here is the *hardware* side of running a model: finding the graphs, opening ONNX Runtime
sessions, and paying the load cost at boot instead of mid-Consultation. What does **not** live here
is any decision about walls — that is :mod:`spectrapaint.segmentation`, which asks this module for a
loaded graph and does the maths itself. Keeping the split means the pipeline can be reasoned about
without knowing how a session is configured, and the session configuration can change without
touching the pipeline.

Three properties worth stating, because each is a decision:

* **Loaded once, per process.** Sessions are cached behind a lock, so two photos arriving together
  cannot both pay the load, and the second does not start until the first has finished loading
  rather than loading a second copy of a 105 MB graph beside it.
* **CPU only.** ``CPUExecutionProvider`` is named explicitly rather than left to ONNX Runtime's
  default list, which would silently prefer a GPU provider if one were ever installed. Until the
  packaging question is settled the shipping assumption is a CPU-only build
  (design-decisions.md §3), and a model that runs on a different device in development than in a
  shop is a model whose measurements mean nothing.
* **Warming is the boot screen's job.** ``warm_in_background`` is called by the process entry point
  after the port is announced, so the load overlaps the boot screen the Dealer is already looking
  at. The per-photo budget is thirty seconds and model loading has no business inside it
  (docs/specs/v1-spectrapaint.md, "Performance").

Thread count is left to ONNX Runtime. The latency spike found these stages memory-bandwidth-bound
rather than CPU-bound, with core count nearly irrelevant (spikes/latency/RESULTS.md), so pinning a
thread count here would be a number chosen for no measured reason.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime

from spectrapaint.runtime.location import (
    REFINER_ID,
    SEMANTIC_ID,
    ModelsMissing,
    models_are_available,
    resolve_models_dir,
)

logger = logging.getLogger(__name__)


# The provider(s) depend on the hardware profile.
def get_execution_providers():
    hardware_profile = os.environ.get("SPECTRAPAINT_HARDWARE_PROFILE", "cpu")
    if hardware_profile == "gpu":
        # Try to use CUDAExecutionProvider, fall back to CPU if not available
        try:
            if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
                return ["CUDAExecutionProvider"]
        except Exception:
            pass
        # If we get here, fall back to CPU
        return ["CPUExecutionProvider"]
    else:
        return ["CPUExecutionProvider"]


@dataclass(frozen=True)
class Graph:
    """One exported graph, with the constants that describe how to feed it.

    ``config`` is the ``runtime.json`` written beside the graph by ``tools/export_onnx.py`` — input
    size, normalisation constants, and for the semantic model the ADE20K class indices. Read from
    the file rather than restated here, so these numbers cannot drift from the weights they belong
    to.
    """

    session: onnxruntime.InferenceSession
    config: dict[str, Any]

    def run(self, inputs: dict[str, np.ndarray]) -> list[np.ndarray]:
        """Run the graph once and return its outputs, in the order it declares them."""
        return self.session.run(None, inputs)


@dataclass(frozen=True)
class Graphs:
    """Every graph the wall pipeline needs, loaded and ready.

    The refiner is two graphs because SAM 2 was exported at its natural seam: ``refiner_encoder``
    depends only on the photo and runs once for it, ``refiner_decoder`` takes that output plus a
    prompt set and may be run again for a different set. Ticket #7 needs exactly that when it
    decodes one Wall Plane at a time.
    """

    semantic: Graph
    refiner_encoder: Graph
    refiner_decoder: Graph

    @property
    def semantic_classes(self) -> dict[str, int]:
        """ADE20K label indices for the five classes the pipeline uses."""
        return self.semantic.config["classes"]


_lock = threading.Lock()
_loaded: Graphs | None = None


def _load_graph(models_dir: Path, model_id: str, graph_name: str, config: dict[str, Any]) -> Graph:
    # Determine the quality tier from environment
    quality_tier = os.environ.get("SPECTRAPAINT_QUALITY_TIER", "better")
    # Base graph name from the graph_name argument
    base_name = graph_name
    # If quality tier is faster, try to load a variant with '-fast' suffix
    if quality_tier == "faster":
        # Create the faster variant name by inserting '-fast' before the extension
        if base_name.endswith(".onnx"):
            fast_name = base_name[:-5] + "-fast.onnx"
        else:
            fast_name = base_name + "-fast"
        fast_path = models_dir / model_id / fast_name
        path = fast_path if fast_path.is_file() else models_dir / model_id / base_name
    else:
        path = models_dir / model_id / base_name

    session = onnxruntime.InferenceSession(str(path), providers=get_execution_providers())
    return Graph(session=session, config=config)


def _read_config(models_dir: Path, model_id: str) -> dict[str, Any]:
    with open(models_dir / model_id / "runtime.json", "rb") as f:
        return json.load(f)


def load(models_dir: Path | None = None) -> Graphs:
    """Every graph, loaded once per process.

    Blocks while another caller is loading rather than loading a second copy — sessions hold the
    weights in memory, and two of them is the difference between fitting on a shop PC and not.

    ``models_dir`` is an argument so a test can point at a directory it prepared, and defaults to
    whatever :func:`resolve_models_dir` decides. Raises ``ModelsMissing`` if the graphs are not
    there, which the caller turns into either a clean boot failure or a plain-language
    preparation failure — never a stack trace in front of a Customer.
    """

    global _loaded
    with _lock:
        if _loaded is not None:
            return _loaded

    directory = resolve_models_dir() if models_dir is None else models_dir
    semantic_config = _read_config(directory, SEMANTIC_ID)
    refiner_config = _read_config(directory, REFINER_ID)

    _loaded = Graphs(
        semantic=_load_graph(directory, SEMANTIC_ID, semantic_config["graph"], semantic_config),
        refiner_encoder=_load_graph(
            directory, REFINER_ID, refiner_config["encoder_graph"], refiner_config
        ),
        refiner_decoder=_load_graph(
            directory, REFINER_ID, refiner_config["decoder_graph"], refiner_config
        ),
    )
    logger.info("Model graphs loaded from %s", directory)
    return _loaded


def warm(models_dir: Path | None = None) -> None:
    """Load the graphs and run one throwaway inference through each.

    Loading a session is not the whole cost: ONNX Runtime allocates its arenas and picks its
    kernels on the first run, so a graph that has been loaded but never run still makes the first
    photo wait. One run with zeros pays that here instead.

    The encoder's output feeds the decoder's warm-up, because the decoder cannot be run without
    something shaped like real image features, and inventing that shape here would be a second
    place that has to agree with the exporter.
    """

    graphs = load(models_dir)

    semantic = graphs.semantic.config
    graphs.semantic.run(
        {
            "pixel_values": np.zeros(
                (1, 3, semantic["input_height"], semantic["input_width"]), dtype=np.float32
            )
        }
    )

    refiner = graphs.refiner_encoder.config
    features = graphs.refiner_encoder.run(
        {
            "pixel_values": np.zeros(
                (1, 3, refiner["input_height"], refiner["input_width"]), dtype=np.float32
            )
        }
    )

    points = refiner["max_prompt_points"]
    graphs.refiner_decoder.run(
        {
            "feature_0": features[0],
            "feature_1": features[1],
            "feature_2": features[2],
            "point_coords": np.zeros((1, 1, points, 2), dtype=np.float32),
            # Every prompt is padding, so this asks the decoder for nothing in particular. The run
            # is for the allocator, not for its answer.
            "point_labels": np.full((1, 1, points), refiner["padding_point_label"], dtype=np.int32),
        }
    )


def warm_in_background(models_dir: Path | None = None) -> threading.Thread | None:
    """Start warming on a daemon thread, and return it, or None if there is nothing to warm.

    Called by the process entry point after the port is announced. On a thread because the service
    must answer requests while this happens — the boot screen is already up, and a Dealer who
    uploads a photo immediately should wait for the model, not for the model *and* a serialised
    startup.

    A missing set of graphs is not an error here. The entry point has already refused to boot in
    that case, and in a source checkout without an export the rest of the service is still worth
    running; the failure is reported when a photo actually needs a wall.
    """

    if models_dir is None and not models_are_available():
        logger.info("No exported model graphs found, so nothing is warmed.")
        return None

    def run() -> None:
        try:
            warm(models_dir)
        except (ModelsMissing, OSError, RuntimeError):
            # Warming is an optimisation. If it fails the photo path will fail too, with a message
            # the Dealer can act on; crashing the boot thread would add nothing but noise.
            logger.warning("Warming the model graphs failed", exc_info=True)

    thread = threading.Thread(target=run, name="spectrapaint-warm-models", daemon=True)
    thread.start()
    return thread


def reset_for_tests() -> None:
    """Forget the loaded graphs.

    Exists so a test can load from one directory and then another; nothing in the service calls it.
    """

    global _loaded
    with _lock:
        _loaded = None
