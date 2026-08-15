# 1. Local-first inference over a localhost REST contract

Date: 2026-08-14

## Status

Accepted

## Context

The one-page report lists React, Electron, Node, Python, REST, PyTorch and SQLite, and states the
product works "across desktop and web" — but never specifies which machine executes SAM 2
inference. That omission determines the model variant we can use, the latency budget, where SQLite
lives, whether the tool works without internet, and whether customer room photographs leave the
dealership.

Relevant technical facts:

- SAM 2 splits into an expensive **image encoder** (Hiera backbone, run once per photograph) and a
  **lightweight mask decoder** (run per prompt, milliseconds). Interactive clicking is therefore
  nearly free after a single per-photo encode — a structure that suits modest local hardware.
- Variant sizes: `tiny` ≈ 39M params, `small` ≈ 46M, `base_plus` ≈ 81M, `large` ≈ 224M. The small
  variants are viable on CPU.
- Exporting to ONNX Runtime removes PyTorch from the shipped artifact, cutting an Electron
  installer from well over a gigabyte to something distributable. PyTorch remains in the
  development and export toolchain, so the report's stated tech stack still holds.

The deployment environment is a paint dealership, where a consultation happens with a customer
physically present.

## Decision

Inference runs **locally on the dealer's machine**. The Python inference layer is built as a **REST
service bound to localhost** from day one. Electron hosts the React UI, which talks to
`localhost:PORT`.

The same React application, against the same REST contract, can later be deployed server-side to
serve the web target. "Desktop and web" is satisfied by one codebase and one contract rather than
two products.

Execution adapts to available hardware rather than assuming a fixed tier:

- Device selection via ONNX Runtime execution provider list
  (`["CUDAExecutionProvider", "CPUExecutionProvider"]`), so GPU use is opportunistic and fallback is
  automatic with no branching in our code.
- Model variant selected per tier by loading a different `.onnx` file into an identical call site
  (variant signatures are the same; only weights differ).
- Int8 dynamic quantization of the encoder available for the floor tier.
- The floor tier is a CPU-only office PC with no discrete GPU.

Only the SAM 2 encoder is hardware-sensitive; relighting and compositing are OpenCV/numpy work that
is CPU-bound and cheap regardless. The adaptivity concern is therefore confined to one component.

To prevent silent quality drift, the active **execution profile is auto-detected as a default,
overridable by the dealer, and stamped into every saved render and every benchmark measurement.**

Mask boundary precision is deliberately decoupled from the network's input resolution: whatever
resolution the tier affords for encoding, the mask is upsampled and its boundary band refined at
full resolution with a cheap edge-aware classical pass. Perceived quality — which depends mostly on
boundary accuracy — stays roughly constant across tiers.

## Consequences

### Positive

- Works with no internet connection; a dropped link cannot kill an in-store consultation.
- Customer room photographs never leave the premises. Privacy, consent flows and data-retention
  policy stay out of scope entirely.
- No GPU hosting cost, which matters for a project whose funding has an expiry date.
- No cold-start latency.
- The demo runs on any machine, including an examiner's laptop.
- Benchmarks remain comparable because the profile is recorded alongside every number.

### Negative

- Packaging a Python runtime inside Electron is real, non-trivial work.
- CPU encode latency must be measured early. Budget 1–4s per photograph on a modest CPU. This is
  acceptable once per photo and unacceptable if we accidentally re-encode per click, so
  encode-once discipline must be enforced structurally, not by convention.
- The `large` SAM 2 variant is effectively out of reach on the floor tier.
- Model updates ship as application updates rather than server-side deployments.
- A settings surface for the profile override must exist, and a profile field must be threaded
  through the persistence model.

## Alternatives considered

- **Thin client plus central GPU server.** Would unlock SAM 2 `large`, centralise model updates and
  avoid packaging pain. Rejected because it makes the tool dependent on dealership internet,
  incurs an ongoing GPU bill, adds cold-start latency, and moves customer photographs off-premises
  — dragging privacy and consent into scope.
- **Hybrid: local segmentation, server-side refinement.** Highest quality ceiling. Rejected because
  it requires building and maintaining both paths plus the fallback logic between them, roughly
  doubling the integration surface — too much for the timeline.
- **Server-only web application, dropping Electron.** Simplest single deployment. Rejected because
  it contradicts the report's stated Electron deliverable and an in-store tool with no offline mode
  is a weak industry proposition.
- **Assuming a discrete NVIDIA GPU in-store.** Rejected because it requires the industry partner to
  commit to hardware purchase, and makes the project undemoable on any machine without one.
- **Pinning all hardware to the floor tier.** Maximum reproducibility and near-zero tiering code.
  Rejected because it discards real available capability and caps best-case visual quality at what
  a weak office PC can produce.
