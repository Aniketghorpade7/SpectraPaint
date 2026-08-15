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
"""

import argparse
import os
import sys

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

import numpy as np  # noqa: E402
from time import perf_counter  # noqa: E402


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
    return np.where(
        grid <= 0.0031308, grid * 12.92, 1.055 * grid ** (1 / 2.4) - 0.055
    ).astype(np.float32)


_SRGB_LUT = _build_srgb_lut()


def linear_to_srgb_lut(x):
    """LUT-based inverse EOTF. One index + gather instead of a pow per pixel."""
    np.clip(x, 0.0, 1.0, out=x)
    idx = (x * (len(_SRGB_LUT) - 1)).astype(np.int32)
    return _SRGB_LUT[idx]


_LINEAR_LUT_U8 = srgb_to_linear(
    np.linspace(0.0, 1.0, 256, dtype=np.float64)
).astype(np.float32)


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

    del photo, alpha, linear, light_map, new_wall, composited
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Measure the per-shade render loop (no models needed)."
    )
    parser.add_argument(
        "--threads", type=int, default=0, help="Limit BLAS/OMP threads (0 = default)"
    )
    args = parser.parse_args()

    print("SpectraPaint latency spike -- part 1: per-shade render loop")
    print(f"numpy {np.__version__} | python {sys.version.split()[0]}")
    if args.threads:
        print(f"thread limit: {args.threads}")
    print()
    print("Note: numpy element-wise ops are single-threaded, so core COUNT")
    print("barely matters here. Single-core speed is what this measures.")
    print()

    header = (
        f"{'resolution':<38} {'ONCE/photo':>12} {'PER TAP':>10} {'PER TAP':>10}"
    )
    print(header)
    print(f"{'':<38} {'lin+lightmap':>12} {'(pow)':>10} {'(LUT)':>10}")
    print("-" * len(header))

    detail = {}
    for label, w, h in RESOLUTIONS:
        r = bench(w, h)
        detail[label] = r
        once = r["srgb_to_linear"] + r["light_map"]
        print(
            f"{label:<38} {once:>10.0f}ms {r['TAP_TOTAL_pow']:>8.0f}ms "
            f"{r['TAP_TOTAL_lut']:>8.0f}ms"
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
    print(f"{'stage':<{name_w}} " + " ".join(f"{l.split()[0]:>9}" for l in detail))
    print("-" * (name_w + 10 * len(detail)))
    for stage in stages:
        row = " ".join(f"{detail[l][stage]:>9.1f}" for l in detail)
        print(f"{stage:<{name_w}} {row}")


if __name__ == "__main__":
    main()
