# runtime — hardware adaptation

Detects the execution profile, selects the ONNX model variant for the tier, and warms models
at boot so loading never enters the per-photo budget.

The profile is auto-detected, Dealer-overridable, and stamped onto every render and benchmark
number, or measurements stop being comparable across machines.
