"""
Latency spike, part 1: the per-shade render loop.

Measures the interactive path the customer actually watches -- everything that
re-runs each time the dealer taps a new shade. Deliberately has NO model
dependencies (numpy only), so it can be run on any machine, including a real
floor-tier shop PC, without installing an ML stack.

Answers open question #6 in docs/design-decisions.md: preview resolution for
shade browsing vs. full-resolution final render.

Pipeline being measured (docs/design-decisions.md section 6):

    ONCE per photo:
        linear    = srgb_to_linear(photo)
        light_map = linear / base_colour

    PER SHADE TAP:
        new_wall  = light_map * target_shade * light_tint
        composite = alpha * new_wall + (1 - alpha) * linear
        output    = linear_to_srgb(composite)

Run:  python bench_render_loop.py [--threads N]

This script is also the project's performance regression gate (#16). CI runs

    python bench_render_loop.py --check

on every push, which measures only the per-tap path at the preview resolutions
and fails the build when it regresses past the budget recorded in
perf-baseline.json. Measurement established the per-shade render as the
bottleneck, and no functional test would notice it getting three times slower --
see docs/design-decisions.md section 9b.
"""

import argparse
import json
import os
import sys
from pathlib import Path

BASELINE_PATH = Path(__file__).with_name("perf-baseline.json")

# Thread limits must be set before numpy is imported.
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--threads", type=int, default=0)
_known, _ = _parser.parse_known_args()
if _known.threads > 0:
    for _var in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[_var] = str(_known.threads)

from time import perf_counter  # noqa: E402

import numpy as np  # noqa: E402

try:
    from spectrapaint.render.engine import light_map_of as _light_map_of  # noqa: E402
except ImportError:
    _light_map_of = None  # standalone run without the package installed

# Resolutions worth distinguishing. A modern phone shoots 12MP; the preview
# candidates are what we would use while the dealer browses shades.
RESOLUTIONS = [
    ("12 MP  (4000x3000)  full phone photo", 4000, 3000),
    ("8 MP   (3264x2448)", 3264, 2448),
    ("2 MP   (1632x1224)  preview candidate", 1632, 1224),
    ("0.9 MP (1280x720)   preview candidate", 1280, 720),
]

REPEATS = 9
WARMUP = 2


def srgb_to_linear(x):
    """Piecewise sRGB EOTF -- the real one, not a 2.2 power curve.

    docs/design-decisions.md pins this explicitly.
    """
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb_pow(x):
    """Naive inverse EOTF. Calls pow() on every pixel of every channel."""
    np.clip(x, 0.0, 1.0, out=x)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def _build_srgb_lut(size=4096):
    grid = np.linspace(0.0, 1.0, size, dtype=np.float32)
    return np.where(grid <= 0.0031308, grid * 12.92, 1.055 * grid ** (1 / 2.4) - 0.055).astype(
        np.float32
    )


_SRGB_LUT = _build_srgb_lut()


def linear_to_srgb_lut(x):
    """LUT-based inverse EOTF. One index + gather instead of a pow per pixel."""
    np.clip(x, 0.0, 1.0, out=x)
    idx = (x * (len(_SRGB_LUT) - 1)).astype(np.int32)
    return _SRGB_LUT[idx]


_LINEAR_LUT_U8 = srgb_to_linear(np.linspace(0.0, 1.0, 256, dtype=np.float64)).astype(np.float32)


def linearize_u8(photo_u8):
    """Realistic linearization: input is 8-bit, so a 256-entry LUT suffices.

    The float path measured above is pessimistic -- a real photo arrives as
    uint8 and never needs a per-pixel pow.
    """
    return _LINEAR_LUT_U8[photo_u8]


def time_it(fn, repeats=REPEATS, warmup=WARMUP):
    """Return median milliseconds over `repeats` runs."""
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(repeats):
        start = perf_counter()
        fn()
        samples.append((perf_counter() - start) * 1000.0)
    return float(np.median(samples))


def bench(width, height):
    rng = np.random.default_rng(0)

    # A photo, as float32 in 0..1. float32 not float64: half the memory
    # traffic, and these ops are memory-bound.
    photo = rng.random((height, width, 3), dtype=np.float32)

    # Soft alpha matte for one wall plane.
    alpha = rng.random((height, width, 1), dtype=np.float32)

    base_colour = np.array([0.55, 0.52, 0.48], dtype=np.float32)
    target_shade = np.array([0.78, 0.70, 0.58], dtype=np.float32)
    light_tint = np.array([1.06, 1.00, 0.92], dtype=np.float32)

    results = {}

    # ---- once per photo -------------------------------------------------
    photo_u8 = (photo * 255).astype(np.uint8)
    results["linearize_u8_lut"] = time_it(lambda: linearize_u8(photo_u8))
    results["srgb_to_linear"] = time_it(lambda: srgb_to_linear(photo))
    linear = srgb_to_linear(photo).astype(np.float32)

    if _light_map_of is not None:
        _bench_alpha = np.ones((height, width, 1), dtype=np.float32)
        results["light_map"] = time_it(lambda: _light_map_of(linear, base_colour, _bench_alpha))
        light_map = _light_map_of(linear, base_colour, _bench_alpha).astype(np.float32)
    else:
        results["light_map"] = time_it(lambda: linear / base_colour)
        light_map = (linear / base_colour).astype(np.float32)

    # ---- per shade tap --------------------------------------------------
    def multiply():
        return light_map * target_shade * light_tint

    results["multiply"] = time_it(multiply)
    new_wall = multiply()

    def composite():
        return alpha * new_wall + (1.0 - alpha) * linear

    results["composite"] = time_it(composite)
    composited = composite()

    results["encode_pow"] = time_it(lambda: linear_to_srgb_pow(composited.copy()))
    results["encode_lut"] = time_it(lambda: linear_to_srgb_lut(composited.copy()))

    # ---- the whole per-tap path ----------------------------------------
    def full_tap_pow():
        w = light_map * target_shade * light_tint
        c = alpha * w + (1.0 - alpha) * linear
        return linear_to_srgb_pow(c)

    def full_tap_lut():
        w = light_map * target_shade * light_tint
        c = alpha * w + (1.0 - alpha) * linear
        return linear_to_srgb_lut(c)

    results["TAP_TOTAL_pow"] = time_it(full_tap_pow)
    results["TAP_TOTAL_lut"] = time_it(full_tap_lut)

    # The arrays are freed when this function returns — a `del` here would only unbind names the
    # closures above still refer to.
    return results


def bench_tap(width, height):
    """Median milliseconds for one shade tap at this resolution, LUT gamma path.

    The gate measures only this. It is the loop the customer watches, it is the
    stage measurement found to be the bottleneck, and it is the one a functional
    test cannot see regress.

    The Light Map is recomputed here on every tap via the real
    :func:`spectrapaint.render.engine.light_map_of` when the package is
    available, so the gate is not blind to the robust Light Map (#9). The
    benchmark's docstring still models it as "once per photo", but
    :func:`spectrapaint.render.engine.render_many` recomputes it per plane
    group on every tap — the gate now measures what the code actually does.
    """
    rng = np.random.default_rng(0)
    linear = rng.random((height, width, 3), dtype=np.float32)
    alpha = rng.random((height, width, 1), dtype=np.float32)
    base_colour = np.array([0.55, 0.52, 0.48], dtype=np.float32)
    target_shade = np.array([0.78, 0.70, 0.58], dtype=np.float32)
    light_tint = np.array([1.06, 1.00, 0.92], dtype=np.float32)

    if _light_map_of is not None:

        def full_tap_lut():
            light_map = _light_map_of(linear, base_colour, alpha)
            w = light_map * target_shade * light_tint
            c = alpha * w + (1.0 - alpha) * linear
            return linear_to_srgb_lut(c)

        return time_it(full_tap_lut)

    light_map = (linear / base_colour).astype(np.float32)

    def full_tap_lut_fallback():
        w = light_map * target_shade * light_tint
        c = alpha * w + (1.0 - alpha) * linear
        return linear_to_srgb_lut(c)

    return time_it(full_tap_lut_fallback)


def load_baseline(path=BASELINE_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def measure_gates(gates):
    """Measure every gate resolution. Returns the gates with `measured_ms` filled in."""
    measured = []
    for gate in gates:
        milliseconds = bench_tap(gate["width"], gate["height"])
        measured.append(dict(gate, measured_ms=round(milliseconds, 1)))
    return measured


def environment():
    return {"numpy": np.__version__, "python": sys.version.split()[0]}


def run_check(baseline_path):
    """The CI gate. Exit code 1 when any gate resolution is over budget."""
    baseline = load_baseline(baseline_path)
    measured = measure_gates(baseline["gates"])
    env = environment()

    print("SpectraPaint performance regression gate -- per-shade render")
    print(f"numpy {env['numpy']} | python {env['python']}")
    print(f"baseline recorded {baseline['recorded']} on {baseline['hardware']}")
    print(f"budget = baseline x {baseline['threshold_multiplier']}")
    print()

    header = f"{'resolution':<32} {'measured':>10} {'baseline':>10} {'budget':>10}   verdict"
    print(header)
    print("-" * len(header))

    breaches = []
    for gate in measured:
        over_budget = gate["measured_ms"] > gate["budget_ms"]
        if over_budget:
            breaches.append(gate)
        print(
            f"{gate['resolution']:<32} {gate['measured_ms']:>8.1f}ms "
            f"{gate['baseline_ms']:>8.1f}ms {gate['budget_ms']:>8.1f}ms   "
            f"{'OVER BUDGET' if over_budget else 'ok'}"
        )

    print()
    if not breaches:
        print("PASS -- the per-shade render is within budget.")
        return 0

    for gate in breaches:
        factor = gate["measured_ms"] / gate["baseline_ms"]
        print(
            f"FAIL -- {gate['resolution']}: {gate['measured_ms']:.1f}ms is "
            f"{factor:.1f}x the recorded baseline ({gate['baseline_ms']:.1f}ms)."
        )
    print()
    print(
        "The per-shade render is the interactive bottleneck (design-decisions.md section 6\n"
        "and 9b). Either the change made it slower, or the machine was busy -- re-run before\n"
        "assuming the latter. The budget is calibrated to a 2-core CI runner, so a contended\n"
        "or slower development machine can exceed it with nothing wrong; CI is the arbiter.\n"
        "\n"
        "If the cost is deliberate and justified, re-record the baseline:\n"
        "    python spikes/latency/bench_render_loop.py --json\n"
        "and update spikes/latency/perf-baseline.json, saying why in the commit."
    )
    return 1


def run_json(baseline_path):
    """Emit the gate measurements, for recording a new baseline."""
    baseline = load_baseline(baseline_path)
    measured = measure_gates(baseline["gates"])
    print(
        json.dumps(
            {
                **environment(),
                "threshold_multiplier": baseline["threshold_multiplier"],
                "gates": [
                    {
                        "resolution": g["resolution"],
                        "width": g["width"],
                        "height": g["height"],
                        "stage": g["stage"],
                        "baseline_ms": g["measured_ms"],
                        "budget_ms": round(g["measured_ms"] * baseline["threshold_multiplier"], 1),
                    }
                    for g in measured
                ],
            },
            indent=2,
        )
    )
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Measure the per-shade render loop (no models needed)."
    )
    parser.add_argument(
        "--threads", type=int, default=0, help="Limit BLAS/OMP threads (0 = default)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Regression gate: measure the gate resolutions and fail if over budget",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit gate measurements as JSON, for re-recording the baseline",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help="Baseline file to check against (default: perf-baseline.json beside this script)",
    )
    args = parser.parse_args()

    if args.check:
        return run_check(args.baseline)
    if args.json:
        return run_json(args.baseline)

    print("SpectraPaint latency spike -- part 1: per-shade render loop")
    print(f"numpy {np.__version__} | python {sys.version.split()[0]}")
    if args.threads:
        print(f"thread limit: {args.threads}")
    print()
    print("Note: numpy element-wise ops are single-threaded, so core COUNT")
    print("barely matters here. Single-core speed is what this measures.")
    print()

    header = f"{'resolution':<38} {'ONCE/photo':>12} {'PER TAP':>10} {'PER TAP':>10}"
    print(header)
    print(f"{'':<38} {'lin+lightmap':>12} {'(pow)':>10} {'(LUT)':>10}")
    print("-" * len(header))

    detail = {}
    for label, w, h in RESOLUTIONS:
        r = bench(w, h)
        detail[label] = r
        once = r["srgb_to_linear"] + r["light_map"]
        print(
            f"{label:<38} {once:>10.0f}ms {r['TAP_TOTAL_pow']:>8.0f}ms {r['TAP_TOTAL_lut']:>8.0f}ms"
        )

    print()
    print("Per-stage breakdown (milliseconds, median):")
    print()
    stages = [
        "linearize_u8_lut",
        "srgb_to_linear",
        "light_map",
        "multiply",
        "composite",
        "encode_pow",
        "encode_lut",
    ]
    name_w = max(len(s) for s in stages)
    print(f"{'stage':<{name_w}} " + " ".join(f"{label.split()[0]:>9}" for label in detail))
    print("-" * (name_w + 10 * len(detail)))
    for stage in stages:
        row = " ".join(f"{detail[label][stage]:>9.1f}" for label in detail)
        print(f"{stage:<{name_w}} {row}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
