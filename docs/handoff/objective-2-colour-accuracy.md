# Handoff: Objective 2 — Calibration-Aware Colour Accuracy

**Status:** PARKED — deliberately deferred during the design grilling session. Resume before any
work begins on the shade-reading pipeline.

**Context:** This document captures a design discussion that was opened and then intentionally
set aside. Nothing here is a decision yet. The one open decision is recorded at the bottom.

---

## The objective, as written in the one-page report

> **Ensure Calibration-Aware Colour Accuracy:** Apply colour constancy and calibration techniques
> to measurably reduce the discrepancy between the photographed wall colour and the recommended
> paint shade.

**Gap identified:** the report names no metric and no ground truth. "Measurably" is unearned until
both are pinned down.

---

## Established constraint: capture is uncontrolled

The capture device varies by user and **will be a mobile phone camera in the majority of cases**.
There is no fixed camera, no calibrated rig, and no guaranteed reference target in frame.

This is a hard constraint on the project, not a preference. Everything below follows from it.

Why it hurts: a phone JPEG has already had auto white balance, a tone curve, a per-scene 3D LUT,
and often HDR fusion baked in by the device ISP. The observed pixel is

```
pixel = ISP(tone curve, 3D LUT) ∘ WB_gains ∘ ∫(illuminant_SPD × reflectance × sensor_curves)
```

with the illuminant, the camera spectral sensitivity, the applied WB gains, and the tone curve all
unknown. Inverting that to recover true surface reflectance is research-grade and, worse,
*unverifiable* without ground truth.

---

## Key reframe: this is two tasks with two different accuracy bars

This distinction is the most important idea to carry forward.

### Task A — recolouring for visualization

Rendering the wall in a *chosen* target shade. **Does not need the wall's true colour.** It needs
the **shading field** — how light falls across the wall — and then renders:

```
new_pixel = render(target_reflectance, illumination_at_pixel)
```

If the illuminant estimate is off, the re-rendered wall is wrong *in the same direction as the rest
of the photograph*, so the result still reads as **consistent**. The bar is perceptual
plausibility, not colorimetric truth.

**Verdict: achievable on any phone.** Uncontrolled capture does not block this.

### Task B — reading the existing wall → nearest catalogue shade

Needs absolute reflectance. This is where uncontrolled phone capture genuinely bites, and no
algorithm fully rescues it.

**Verdict: accuracy must be contracted honestly, not assumed.** This is the parked decision.

---

## Techniques that actually move accuracy under phone capture

Ranked by leverage.

1. **Capture RAW/DNG rather than accepting gallery JPEGs.**
   Biggest single win, and free. RAW is upstream of the tone curve and 3D LUT: linear sensor data,
   plus an `AsShotNeutral` tag recording what the phone's own well-tuned commercial ISP estimated
   the illuminant to be — a better free prior than grey-world. Requires building a capture screen
   instead of using a file picker. Available via Android Camera2 / iOS AVCapture on most
   mid-range-and-up phones.

2. **Per-device colour profiles.**
   Characterise the ~15 phone models dealers actually encounter (one ColorChecker shoot each; fit a
   3×3 matrix plus tone curve), store them, and match on the EXIF model tag. Converts "unknown
   camera" into "known camera" for the majority of real traffic. **Likely the most defensible novel
   contribution in the project.**

3. **Use the dealer's own fandeck as the reference target.**
   No need to ship ColorCheckers. The shade card is already in the room during a consultation and
   its Lab values are known from the manufacturer. One shot with it held against the wall yields
   the transfer function *in that exact lighting*.

4. **Ensemble estimation with a confidence signal.**
   Run CWCC (cited in the report), grey-edge, gamut mapping, and `AsShotNeutral` together. Use
   their **mutual disagreement** as a confidence score, and surface that score to the dealer.

5. **Reject pathological inputs rather than guessing.**
   Detect mixed illumination (window + tungsten), clipped highlights, flash, high-ISO noise. Most
   catastrophic errors arise from a small set of *detectable* conditions; a warning beats a wrong
   answer.

---

## Honest accuracy expectations

Ballpark ΔE00 figures — indicative, to be replaced by measured results from our own benchmark.

| Pipeline | ΔE00 | What can be honestly claimed |
|---|---|---|
| Raw JPEG, no correction | 8–15 | Nothing |
| Colour constancy on JPEG | 5–8 | Correct colour *family* |
| + per-device profile + DNG | 3–5 | Correct shade usually within top-3 |
| + fandeck in frame | 1–2 | Genuine shade match |

Perceptual and industrial reference points:
- ΔE00 ≈ 1 — just-noticeable difference side-by-side
- ΔE00 ≈ 2–3 — noticeable to a trained eye
- Paint-industry batch-match tolerance — typically ΔE ≤ 1

**Consequence:** without an in-frame reference we cannot honestly claim shade-match accuracy. We
*can* claim **shortlist accuracy**, which also happens to match how dealers already work — they
confirm against the physical fandeck regardless.

---

## Proposed measurable form of Objective 2

To make "measurably" real, Objective 2 should resolve into two reported numbers:

1. **ΔE00 reduced from X to Y** by the calibration pipeline, on a held-out benchmark.
2. **Correct catalogue shade present in top-3, Z% of the time.**

This requires building a **ground-truth benchmark set**: N walls painted in known catalogue shades,
photographed across M phone models under K lighting conditions, with reference readings taken by
spectrophotometer or a calibrated target. Without this set, Objective 2 cannot be defended.

---

## The parked decision

**What accuracy contract do we commit to for the shade-reading path (Task B)?**

Options as framed during the session:

- **A. Shortlist + confidence** *(was the recommendation)* — return top-3 catalogue shades with
  ΔE00 and a confidence badge; no reference target required. On low confidence, prompt the dealer
  to hold the fandeck against the wall and reshoot, which opts them into the high-accuracy path.
  Makes Objective 2 measurable as the two numbers above.
- **B. Reference target required always** — no shade reading unless a fandeck or card is detected
  in frame. Strongest ΔE00 claim (~1–2) and cleanest science; costs a mandatory workflow step and
  blocks casual or remote photos entirely.
- **C. Single best match, computational only** — simplest UX, but at ΔE00 5–8 it will be
  confidently wrong often, and a dealer who mixes paint on a wrong answer loses money.
  *Argued against.*
- **D. Drop shade reading entirely** — visualization only; the dealer picks the target shade by
  hand and we never claim to read the existing wall. Heavily de-risks the project and Task A still
  works on any phone, but guts the second half of Objective 2 and removes the calibration story
  that differentiates SpectraPaint.

**Nothing has been chosen.** Resume here.

---

## Downstream items blocked on this decision

- Whether a capture screen (RAW/DNG) is required, or a file picker suffices
- Whether per-device colour profiling is in scope, and how profiles are stored and shipped
- Whether fandeck detection is a feature that needs building
- The ground-truth benchmark set: whether it gets built, and by whom
- What the shade-match UI shows: one shade, three, or a confidence state
- Catalogue data requirements — measured Lab values vs. approximate sRGB swatches
