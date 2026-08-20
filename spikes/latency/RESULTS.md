# Latency Spike — Part 1: the per-shade render loop

**Date:** 2026-08-15
**Script:** [bench_render_loop.py](./bench_render_loop.py) (numpy only — no models needed)
**Answers:** open question #6 in [../../docs/design-decisions.md](../../docs/design-decisions.md)

---

## Test machine

| | |
|---|---|
| CPU | Intel i7-14650HX — 8 P-cores @ 5.0–5.2 GHz (cpu0–15), 8 E-cores @ 3.7 GHz (cpu16–23) |
| RAM | 16 GB |
| GPU | RTX 4060 Laptop 8 GB + Intel UHD (not used in part 1) |
| numpy | 2.5.2, Python 3.14.6 |

**This machine is far above the floor tier**, so it was throttled three ways to bracket the range a
real shop PC would fall into. The E-cores are roughly Skylake-class per clock, which is close to a
2018-era office PC.

---

## Results — per-shade tap (the loop the customer watches)

Milliseconds, median of 9 runs, optimised (lookup-table gamma) path:

| Resolution | P-cores, free | 1 E-core | 1 E-core @ 40% | **Likely shop PC** |
|---|---|---|---|---|
| 12 MP (4000×3000) | 641 | 896 | 2828 | **~1000–2800** |
| 8 MP (3264×2448) | 427 | 581 | 1915 | ~600–1900 |
| 2 MP (1632×1224) | 82 | 133 | 401 | **~130–400** |
| 0.9 MP (1280×720) | 43 | 57 | 195 | **~60–200** |

Once-per-photo cost (linearise + light map) at 12 MP: 554 ms / 922 ms / 2885 ms.

---

## Findings

### 1. Full-resolution rendering per tap is not viable

Even on a high-end i7 it costs **641 ms per shade tap**, and a realistic shop PC lands between
**1 and 2.8 seconds**. That is per tap, with a customer watching, in a workflow budgeted at three
taps and thirty seconds total.

**This confirms the audit's finding:** the SAM 2 encode was never the interactive bottleneck. This
is. The encode runs once per photo; this runs every time the dealer touches a colour.

### 2. A ~1 MP preview is viable across the entire range

At 1280×720 the per-tap cost stays between **43 ms and 195 ms** even under heavy throttling — fast
enough to feel immediate. 2 MP is borderline: fine on decent hardware (82 ms), sluggish at the
pessimistic end (401 ms).

### 3. Lookup tables for gamma are mandatory, not an optimisation

Both directions of the sRGB transfer function are expensive when computed per pixel:

| Operation | Naive `pow` | Lookup table | Saving |
|---|---|---|---|
| Encode to sRGB (**every tap**) | 507 ms | 241 ms | **2.1×** |
| Linearise from 8-bit (once per photo) | 457 ms | 139 ms | **3.3×** |

At the throttled end the encode saving alone is **1.5 seconds per tap**. The linearise case is even
clearer: a real photo arrives as 8-bit, so a 256-entry table is exact — a per-pixel `pow` there is
pure waste.

The gamma encode is the **single most expensive stage of the per-tap path**, at ~38% of it.

### 4. These stages are memory-bandwidth-bound, not CPU-bound

A single E-core at 3.7 GHz was only **1.4× slower** than unrestricted P-cores, despite a large clock
and IPC gap. Each 12 MP float32 array is 144 MB, and every operation streams hundreds of megabytes.

**Consequence:** a shop PC's *slower RAM* will hurt more than its slower CPU, and core count is
almost irrelevant — numpy's element-wise operations are single-threaded, so sixteen cores bought
this machine nothing here.

### 5. Untested optimisation worth taking: crop to the wall

We currently render the whole image on every tap, but only pixels inside the wall change. Cropping
to the wall's bounding box should cut cost roughly in proportion to wall area — commonly 3× or more.
Not yet measured; likely the largest single saving still available.

---

## Recommendations

1. **Browse at ~1 MP.** Render previews at roughly 1280×720 while the dealer taps through shades.
2. **Render full resolution only on save or export.** A one-off 1–3 s cost, which the progress
   messaging already decided in §13 covers comfortably.
3. **Use lookup tables for both gamma directions.** Mandatory. 256 entries for linearising 8-bit
   input; ~4096 for encoding.
4. **Crop to the wall's bounding box** before the per-tap maths.
5. **Re-run this script on a real shop PC** when one is available. It needs only numpy, so setup is
   a couple of minutes — no ML stack required.

---

## Caveats

- Throttling models a slow **CPU**, not slow **RAM**. Since these stages are bandwidth-bound, a real
  low-end machine could differ from these figures in either direction.
- The 40% quota case simulates a machine that is both slow *and* contended; it is probably
  pessimistic for a dedicated shop PC.
- Synthetic random image data was used. Real photographs will not change these timings materially —
  the operations are data-independent.

---

## Part 2 — the model stages, measured (ticket #6)

Measured on the exported graphs (`tools/export_onnx.py`), ONNX Runtime 1.29 on
`CPUExecutionProvider`, 24 logical cores, at the graphs' own input sizes. Best of three runs after a
warm-up, so these are steady-state numbers rather than first-run ones.

| Stage | Cost | Notes |
|---|---|---|
| Load 3 sessions | **2 276 ms** | Once per process, at boot |
| First run of each graph | **3 061 ms** | Allocator and kernel selection — the reason warming runs one throwaway inference, not just a load |
| Semantic pass (512×512) | **364 ms** | Per photo |
| SAM 2 encode (1024×1024) | **1 997 ms** | Per photo, and the dominant cost — as Part 1 predicted |
| SAM 2 decode (32 prompts) | **120 ms** | Per prompt set, so per Wall Plane in #7 |
| Boundary refinement + matte | included above | Guided filter over ~0.9 MP; not separately resolvable at this precision |
| Peak RSS | **~2.1 GB** | Whole process, including numpy working buffers |

**Per photo that is ~2.5 s of model work on this machine**, against a thirty-second budget. The
encode being 80% of it is what justified exporting SAM 2 as two graphs: a design that re-encoded per
prompt set would have spent two seconds per Wall Plane in #7, where the split spends 120 ms.

**Caveats, stated plainly.** This is a 24-core development machine, not the 2-core floor tier the
architecture assumes, and these stages were not throttled the way Part 1's were. Peak RSS near
2 GB is the number most worth re-measuring on shop hardware — it feeds the tier table, and it is
close enough to a 4 GB machine's comfortable working set to matter. Neither figure has been measured
on Windows.

## Still to measure

- The same stages on floor-tier hardware (2 cores, and under memory pressure)
- Peak RSS on Windows, where the allocator differs
- Whether DirectML on integrated graphics helps (open question #3)
