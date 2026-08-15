# Handoff: Building Our Own Wall Segmentation Model

**Status:** PLANNED — not started. Must be complete before any commercial deployment.

**Why this exists:** V1 development uses NVIDIA's SegFormer/MiT ADE20K checkpoints, which are
published under a **non-commercial research licence**. SpectraPaint is built for Arun Paint
Industries and is intended to run in real dealerships. Those weights **cannot ship**. This document
is the plan to replace them.

**Goal:** a wall-aware semantic segmentation model of **equal or better accuracy** than
SegFormer-B0 on *our* task, that we are unambiguously licensed to deploy, and that runs inside the
CPU floor-tier budget.

---

## ⚠ Read this first: do not distil from the SegFormer checkpoints

The obvious shortcut is to train our model to imitate SegFormer's outputs. **Do not.** Using a
non-commercially-licensed model to produce a commercial one is precisely what that licence exists to
prevent, and a derived model inherits the problem. Our model must be trained from data we are
independently licensed to use.

The same caution applies to using SegFormer to auto-label our training images. That is distillation
wearing a hat.

---

## Why "equal or better accuracy" is realistic

This sounds ambitious until you notice **we are solving a much narrower problem.**

SegFormer-B0 on ADE20K is a **150-class** general scene parser, and its published mIoU is averaged
across all 150 classes. We do not care about 148 of them. We need, at most:

`wall` · `floor` · `ceiling` · `window` · `door` · `other`

A model trained on six indoor classes can comfortably beat a 150-class generalist **on wall IoU in
indoor rooms**, at a fraction of the parameters. We are not competing on ADE20K's leaderboard metric;
we are competing on ours.

There is a second, larger advantage available — see *domain gap* below.

---

## Data — the crux, and where the licence risk really lives

Swapping the model does nothing if the training data carries the same restriction. **Verify the
licence of every dataset before use, and record it.**

### Candidate datasets

| Dataset | Content | Licence position | Verdict |
|---|---|---|---|
| **Hypersim** (Apple) | Photorealistic synthetic indoor scenes, full semantic labels | **CC BY-SA 3.0** — commercially usable with share-alike | **Strongest candidate.** Check share-alike implications for our weights |
| **Structured3D** | Synthetic indoor, wall/floor/ceiling, huge | Needs verification | Promising, verify first |
| **ADE20K** | The current source | MIT CSAIL, historically research-oriented terms | **Verify before relying on.** May restrict *any* model trained on it, not just NVIDIA's |
| **NYU Depth V2** | Real indoor, 40-class labels incl. wall | Research-oriented | Verify; likely research-only |
| **ScanNet** | Real indoor 3D scans | Signed terms-of-use, research only | **Avoid** |
| **Our own captures** | Real rooms, phone-shot, hand-labelled | Ours outright | **Essential — see below** |

### The domain gap, and why our own data is the real contribution

ADE20K and most public indoor datasets are **heavily Western-skewed** — the room geometry, wall
finishes, window styles, furniture and light sources do not match Indian homes. Our input is
specifically *Indian rooms photographed on Indian phones*.

That gap is an opportunity, not just a risk. **A modest set of real, hand-labelled photographs of
local rooms, shot on the phones our customers actually use, is likely worth more than a large
mismatched public dataset** — and it is a genuinely defensible novel contribution to write up.

Recommended shape:

1. **Pretrain** on permissively-licensed synthetic data (Hypersim / Structured3D) for volume.
2. **Fine-tune** on our own labelled set of real local rooms for domain fit.
3. **Hold out** a test set of our own data that is never trained on.

Collecting this doubles as the ground-truth set that §10 of `design-decisions.md` already requires
for evaluating wall-detection accuracy. **One collection effort, two deliverables.**

---

## Architecture

Constraints: must run on the **CPU floor tier** (no GPU), export cleanly to **ONNX**, and stay well
under SegFormer-B0's cost so it does not eat the 30-second per-photo budget.

Start from an ImageNet-pretrained **permissively-licensed** backbone plus a light decoder:

| Option | Notes |
|---|---|
| **MobileNetV3-Large + LR-ASPP** | torchvision, BSD-licensed weights. Very fast on CPU. **Recommended starting point** |
| **DDRNet / PIDNet** | Designed for real-time segmentation; strong speed/accuracy trade-off |
| **BiSeNetV2** | Real-time, well-established |
| **Small U-Net from scratch** | Total licence clarity, but throws away pretraining and will need far more data |

Target: **under ~5M parameters.** Verify torchvision's ImageNet weight licensing as part of the
work — this is widely-practised but should be confirmed and recorded, not assumed.

**Design note:** boundary precision matters more here than raw IoU. `design-decisions.md` §5 already
refines boundaries at full resolution with a classical edge-aware pass, so the network's job is
**correct region semantics**, not crisp edges. That permits a lower-resolution, cheaper network than
IoU alone would suggest. Optimise for *not confusing wall with furniture*, and let the refinement
pass handle sharpness.

---

## What the model must get right

Ranked by impact on the final render, not by pixel count:

1. **Shadowed wall must stay classified as wall.** The single most damaging failure. A dark strip
   near the ceiling misclassified as non-wall leaves a visible ghost of the old paint after
   recolouring. Training data must include strongly and unevenly lit rooms.
2. **Furniture and occluders excluded.** Wardrobes, sofas, curtains, hangings.
3. **Wall vs ceiling separation.** They are often similar in colour and meet at a soft boundary.
4. **Windows and doors excluded** — recolouring a window is instantly, obviously wrong.
5. **Small fixtures — switchplates, sockets, pipes — are now IN scope for this model.** ADE20K has
   no such classes, so V1 paints over them (`design-decisions.md` §5 accepts this as a documented
   limit). **Decided:** add them as classes here. Since we are already labelling our own room
   photographs, adding a few small classes while someone is drawing wall boundaries costs little —
   and it makes this model genuinely *better* than the baseline it replaces, not merely legally
   shippable.

   This is the most customer-visible flaw in the V1 render: nobody needs to be told that a
   dark-blue light switch looks wrong. Fixing it here is the clearest quality win available.

---

## Evaluation — how we prove "equal or better"

The claim must be measured, not asserted. Compare **our model vs SegFormer-B0** on the held-out set
of our own real photographs:

| Metric | Why |
|---|---|
| **Wall IoU** | The headline number |
| **Boundary F-score** (within a few pixels) | IoU is insensitive to edge quality, which is what the render actually shows |
| **Shadowed-region recall** | Specifically measures failure mode #1 above |
| **CPU latency on the floor tier** | Must fit the budget; a more accurate model we cannot run is not a win |
| **Model size on disk** | Installer budget |

Report all five. If our model wins on wall IoU but loses badly on latency, that is not a
replacement.

**Note:** SegFormer-B0 may be used as a *baseline for comparison* in the report. Running it to
measure it is not the same as training against it, and does not create a derived work.

---

## Sequencing

1. Verify dataset licences — **do this first**, it determines everything else
2. Define the class list (6 classes vs binary wall/not-wall)
3. Collect and label the local-room dataset (doubles as the evaluation ground truth)
4. Establish the SegFormer-B0 baseline on that test set
5. Pretrain on permissive synthetic data
6. Fine-tune on local data
7. Evaluate against the five metrics
8. Export to ONNX, verify floor-tier latency
9. Swap in, and record every shipped weight's licence

---

## Related

- [../design-decisions.md](../design-decisions.md) §5 — the segmentation pipeline this model plugs
  into, and §12 item 2, the open question this closes
- [../design-decisions.md](../design-decisions.md) §10 — evaluation, which shares this document's
  data-collection effort
- [objective-2-colour-accuracy.md](./objective-2-colour-accuracy.md) — separately parked; its
  benchmark set could be collected in the same sessions as this one's
