"""Where saved work lives: the OS per-user application data directory.

One function decides this, for the same reason the Catalogue has one: "a Consultation survives a
restart" is only true if every process agrees on where the files are, and that agreement needs a
single place it can be read.

Two ways a directory is found, in order:

1. ``SPECTRAPAINT_STORAGE_DIR`` — an explicit path. This is how tests describe a throwaway
   directory without touching the machine's real one, and how support can point an install at
   another disk.
2. The per-user application data directory, via ``platformdirs`` (conventions.md §2). On
   Windows this is ``%APPDATA%\\SpectraPaint`` — the packaged Electron build sets
   ``SPECTRAPAINT_STORAGE_DIR`` to ``app.getPath('userData')`` so both halves share one library.

Deliberately absent: any fallback to a directory inside the repository. A source checkout that
quietly writes Bundles into its own tree looks identical to a working install until the packaged
app cannot find yesterday's Consultations.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from platformdirs import user_data_dir

STORAGE_DIR_ENV_VAR = "SPECTRAPAINT_STORAGE_DIR"

# One name, shared with Electron's userData so both processes read the same library.
APP_NAME = "SpectraPaint"


def resolve_storage_dir(environ: Mapping[str, str] | None = None) -> Path:
    """The directory this installation keeps its SQLite database and images in.

    Both inputs are arguments rather than reads of process state, so a test can describe an
    environment without mutating the one it runs in (the catalogue/location.py rule).
    """

    environ = os.environ if environ is None else environ

    configured = environ.get(STORAGE_DIR_ENV_VAR, "").strip()
    if configured:
        return Path(configured)

    # appauthor=False: no phantom vendor folder on Windows — the directory is SpectraPaint's own.
    # Note: platformdirs' user_data_dir differs slightly from Electron's app.getPath('userData')
    # on Linux (~/.local/share/SpectraPaint vs ~/.config/SpectraPaint) and macOS
    # (~/Library/Application Support/SpectraPaint variations). The packaged app passes
    # SPECTRAPAINT_STORAGE_DIR to keep both halves on one directory; this default is for
    # local development and tests.
    return Path(user_data_dir(APP_NAME, appauthor=False))
