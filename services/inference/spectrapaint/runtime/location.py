"""Where the exported model graphs come from.

One function decides this, so "point the service at another directory of graphs and it uses them"
has a single place it can be true — and a single place to read when it is not. The shape follows
:mod:`spectrapaint.catalogue.location` deliberately; two ways of answering "where is my data" would
be two things to learn.

Two ways a directory is found, in order:

1. ``SPECTRAPAINT_MODELS_DIR`` — an explicit path. This is how the packaged app works: Electron
   knows where the graphs were installed and passes the directory in the service's environment.
2. The development directory ``models/`` in the repository, which is where
   ``tools/fetch_models.py`` and ``tools/export_onnx.py`` put their output.

Deliberately absent: any search of installation directories, and any fallback that lets the service
start without graphs. A service that boots happily and only discovers it cannot find a wall when a
Customer is at the counter has turned a setup problem into a Consultation problem — the same
argument the Catalogue makes for loading at construction.
"""

import os
from collections.abc import Mapping
from pathlib import Path

MODELS_DIR_ENV_VAR = "SPECTRAPAINT_MODELS_DIR"

# services/inference/spectrapaint/runtime/location.py -> the repository root is five levels up.
# Only ever reached in a source checkout: in a packaged build the environment variable is set.
DEVELOPMENT_MODELS_DIR = Path(__file__).resolve().parents[4] / "models"

# Model ids, as named in models/manifest.toml. The directory layout is the manifest's, so a graph
# and the weights it was exported from stay together.
SEMANTIC_ID = "semantic-segformer-b0-ade20k"
REFINER_ID = "refiner-sam2-hiera-tiny"

# Every file the pipeline needs on disk, relative to the models directory. The `.onnx` graphs and
# the `runtime.json` sidecars that describe how to feed them — see tools/export_onnx.py.
REQUIRED_FILES = (
    f"{SEMANTIC_ID}/semantic.onnx",
    f"{SEMANTIC_ID}/runtime.json",
    f"{REFINER_ID}/sam2-encoder.onnx",
    f"{REFINER_ID}/sam2-decoder.onnx",
    f"{REFINER_ID}/runtime.json",
)

_MESSAGE_NO_MODELS = (
    "SpectraPaint could not find the files it needs to detect walls. Please reinstall the app, or "
    "contact whoever set it up for you."
)


class ModelsMissing(Exception):
    """The model graphs could not be found, or the directory found is incomplete.

    Carries a plain-language ``message`` the UI may show as-is, and a ``detail`` for the log — the
    Dealer cannot act on a filesystem path, and whoever reads the log cannot act without one
    (conventions.md §5).
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.message = _MESSAGE_NO_MODELS
        self.detail = detail


def resolve_models_dir(
    environ: Mapping[str, str] | None = None,
    *,
    development_dir: Path | None = None,
) -> Path:
    """The directory holding the exported graphs, or ``ModelsMissing`` saying why there is none.

    Both inputs are arguments rather than reads of process state, so a test can describe an
    environment without mutating the one it runs in.

    Every required file is checked, not just the directory. A half-exported directory is the more
    likely accident — an interrupted export, or a cache restored from an older exporter — and it
    fails in a far less obvious place if it is allowed through.
    """

    environ = os.environ if environ is None else environ
    development_dir = DEVELOPMENT_MODELS_DIR if development_dir is None else development_dir

    configured = environ.get(MODELS_DIR_ENV_VAR, "").strip()
    if configured:
        directory = Path(configured)
        if not directory.is_dir():
            raise ModelsMissing(
                f"{MODELS_DIR_ENV_VAR} is set to {configured!r}, which is not a directory."
            )
    else:
        directory = development_dir
        if not directory.is_dir():
            raise ModelsMissing(f"{MODELS_DIR_ENV_VAR} is not set and {directory} does not exist.")

    missing = [name for name in REQUIRED_FILES if not (directory / name).is_file()]
    if missing:
        raise ModelsMissing(
            f"{directory} is missing {', '.join(missing)}. Fetch the weights and export the "
            "graphs: python tools/fetch_models.py && python tools/export_onnx.py"
        )

    return directory


def models_are_available(
    environ: Mapping[str, str] | None = None,
    *,
    development_dir: Path | None = None,
) -> bool:
    """Whether a complete set of graphs is on disk, without raising if it is not.

    For callers that must not fail when the graphs are absent — warming at boot asks this before
    starting work, so a source checkout with no export yet still runs the parts of the service that
    do not need a model.
    """

    try:
        resolve_models_dir(environ, development_dir=development_dir)
    except ModelsMissing:
        return False
    return True
