"""The execution profile this process runs under.

One helper, read by every stamp and every benchmark, so all of them agree — a render
saved by the Store, the TS-side ``executionProfile`` field, and a benchmark line are
never allowed to disagree about what produced them (issue #14).

The environment variables are set by the sidecar launcher (``sidecar.ts``) at launch
and default to the CPU-only, better-quality build the shipping assumption is
(design-decisions.md §3). Deliberately imports nothing beyond the standard library:
the benchmark spike runs with numpy only and must not pull a web framework in to
read two environment variables.
"""

from __future__ import annotations

import os


def execution_profile() -> str:
    """``<hardware>-<quality>``, e.g. ``cpu-better`` or ``gpu-faster``."""
    hardware = os.environ.get("SPECTRAPAINT_HARDWARE_PROFILE", "cpu")
    quality = os.environ.get("SPECTRAPAINT_QUALITY_TIER", "better")
    return f"{hardware}-{quality}"
