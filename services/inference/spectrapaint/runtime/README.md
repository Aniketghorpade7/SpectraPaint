# runtime — hardware adaptation

Detects the execution profile, selects the ONNX model variant for the tier, and warms models
at boot so loading never enters the per-photo budget.

The profile is auto-detected, Dealer-overridable, and stamped onto every render and benchmark
number, or measurements stop being comparable across machines.

**What exists today (ticket #6):** `location.py` finds the exported graphs — `SPECTRAPAINT_MODELS_DIR`
if set, otherwise the repository's `models/` — and `graphs.py` opens the ONNX Runtime sessions, once
per process, on `CPUExecutionProvider` only. `warm_in_background()` is called by the process entry
point after the port is announced, so loading overlaps the boot screen instead of the per-photo
budget.

**What does not exist yet:** the tier table. `design-decisions.md` §3 leaves it open, and #6 did not
close it — there is one CPU path, which is what "assume a CPU-only shipping build" asks for. The
measurements it needs are in `spikes/latency/RESULTS.md`.
