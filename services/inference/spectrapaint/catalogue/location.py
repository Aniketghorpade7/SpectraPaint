"""Where the Catalogue file comes from.

One function decides this, so "swap the file and the Catalogue changes, with no code change" has a
single place it can be true — and a single place to read when it is not.

Two ways a path is found, in order:

1. ``SPECTRAPAINT_CATALOGUE_FILE`` — an explicit path. This is how the packaged app works: Electron
   knows where the file was installed and passes it in the service's environment. It is also the
   override a Dealer with a second manufacturer's file uses.
2. The development directory ``data/catalogue/`` in the repository, when it exists and holds exactly
   one JSON file.

Deliberately absent: any search of installation directories, any bundled default compiled into the
package, and any fallback to an empty Catalogue. A service that quietly serves the wrong Shades — or
no Shades — looks identical to a working one until a Customer is standing at the counter.
"""

import os
from collections.abc import Mapping
from pathlib import Path

CATALOGUE_PATH_ENV_VAR = "SPECTRAPAINT_CATALOGUE_FILE"

# services/inference/spectrapaint/catalogue/location.py -> the repository root is five levels up.
# Only ever reached in a source checkout: in a packaged build the environment variable is set, and
# this directory does not exist.
DEVELOPMENT_CATALOGUE_DIR = Path(__file__).resolve().parents[4] / "data" / "catalogue"

_MESSAGE_NO_CATALOGUE = (
    "SpectraPaint could not find its Shade Catalogue. Please reinstall the app, or contact whoever "
    "set it up for you."
)


class CatalogueFileMissing(Exception):
    """No Catalogue file could be found, or the one named does not exist.

    Carries a plain-language ``message`` the UI may show as-is, and a ``detail`` for the log — the
    Dealer cannot act on a filesystem path, and whoever reads the log cannot act without one
    (conventions.md §5).
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.message = _MESSAGE_NO_CATALOGUE
        self.detail = detail


def resolve_catalogue_path(
    environ: Mapping[str, str] | None = None,
    *,
    development_dir: Path | None = None,
) -> Path:
    """The Catalogue file to load, or raise ``CatalogueFileMissing`` saying why there is none.

    Both inputs are arguments rather than reads of process state, so a test can describe an
    environment without mutating the one it runs in.
    """

    environ = os.environ if environ is None else environ
    development_dir = DEVELOPMENT_CATALOGUE_DIR if development_dir is None else development_dir

    configured = environ.get(CATALOGUE_PATH_ENV_VAR, "").strip()
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise CatalogueFileMissing(
                f"{CATALOGUE_PATH_ENV_VAR} is set to {configured!r}, which is not a file."
            )
        return path

    return _only_catalogue_in(development_dir)


def _only_catalogue_in(directory: Path) -> Path:
    """The single JSON file in the development directory.

    Exactly one, or it is an error. Picking the newest, or the highest version, would mean a stale
    file left beside a new one silently decides which Shades the Dealer sells — and the two would
    differ in ways nobody notices until a saved Consultation disagrees with the screen. One
    Catalogue at a time is the rule (docs/design-decisions.md §7); this is where it is enforced.
    """

    if not directory.is_dir():
        raise CatalogueFileMissing(
            f"{CATALOGUE_PATH_ENV_VAR} is not set and {directory} does not exist."
        )

    candidates = sorted(directory.glob("*.json"))

    if not candidates:
        raise CatalogueFileMissing(
            f"{CATALOGUE_PATH_ENV_VAR} is not set and {directory} holds no Catalogue file."
        )

    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise CatalogueFileMissing(
            f"{directory} holds more than one Catalogue file ({names}). "
            f"Leave one, or name the one to load in {CATALOGUE_PATH_ENV_VAR}."
        )

    return candidates[0]
