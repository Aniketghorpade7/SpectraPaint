# Spec: SpectraPaint V1

**Status:** Ready for implementation
**Scope:** All of V1, end to end
**Vocabulary:** [CONTEXT.md](../../CONTEXT.md) — terms in **bold** are defined there
**Constraints:** [ADR-0001](../adr/0001-local-first-inference-over-localhost-rest.md),
[design-decisions.md](../design-decisions.md)

---

## Problem Statement

A **Customer** walks into a paint shop wanting to repaint a room and cannot picture the result. The
**Dealer** hands them a **Fandeck** — a book of a thousand printed chips — and the Customer tries to
imagine a two-centimetre square scaled up to their living room wall, under their own lighting, next
to their own furniture. They cannot. So they hesitate, take a chip home, and often do not come back.

The visualisation tools the paint industry already provides do not solve this, because they show
**generic stock rooms** rather than the Customer's actual room. A Customer looking at a stranger's
tastefully lit living room learns nothing about their own north-facing bedroom.

The Dealer's problems compound this:

- They cannot close confidently, because the Customer is not confident.
- They get complaints after the fact — *"this isn't the colour I picked"* — which cost money and
  goodwill.
- They cannot easily upsell an **Accent Wall**, because the Customer cannot picture one.
- A Customer who leaves undecided is usually gone, and there is no record of what was already shown
  and rejected when they do return.

All of this happens at a counter, with other customers waiting. Anything that takes minutes of
fiddling will not be used.

## Solution

SpectraPaint shows the Customer **their own room**, repainted in a **Shade** the Dealer actually
sells, with the room's real lighting, shadows and texture preserved so the result is believable.

The Dealer loads a **Room Photo**, the app finds the **Wall Planes** automatically, the Dealer taps a
Shade, and the room updates. Tapping another Shade updates it again, immediately. The Customer sees
their own walls change colour in front of them.

The result is believable because the app never repaints pixels naively. It works out how light falls
across each wall — the **Light Map** — and replaces only the underlying paint colour, carrying the
shadows, gradients and roller texture through untouched.

Everything runs on the Dealer's own machine. No internet, no cloud, and Customer room photographs
never leave the shop.

---

## User Stories

### Starting a consultation

1. As a Dealer, I want to open the app and have it be ready to use, so that I am not waiting while a Customer stands at my counter.
2. As a Dealer, I want to see a loading screen while the app prepares itself, so that I know it is working rather than frozen.
3. As a Dealer, I want the app to tell me if something failed to start, so that I find out before a Customer is in front of me rather than during.
4. As a Dealer, I want to start a new **Consultation** in one action, so that I can begin as soon as the Customer describes what they want.
5. As a Dealer, I want to load a Room Photo from the Customer's phone or a file, so that we are looking at their actual room.
6. As a Dealer, I want processing to begin the instant the photo loads, so that the wait overlaps with me talking to the Customer instead of following it.

### Understanding the wait

7. As a Dealer, I want to see what the app is doing in plain language while it prepares a photo, so that the Customer does not think it has hung.
8. As a Dealer, I want progress messages that sound purposeful rather than technical, so that I look competent rather than like I am running an experiment.
9. As a Dealer, I want to know that the slow part happens only once per photo, so that I can tell the Customer that colours will change instantly from here.

### Finding the walls

10. As a Dealer, I want the app to find the walls in the photo by itself, so that I do not spend the Customer's time drawing outlines.
11. As a Dealer, I want each **Wall Plane** treated separately, so that walls at different angles keep their different brightness and the room still looks three-dimensional.
12. As a Dealer, I want furniture, windows, doors, floor and ceiling excluded from the walls, so that I do not paint over the Customer's wardrobe.
13. As a Dealer, I want shadows on a wall to remain part of that wall, so that repainting does not leave a ghost of the old colour in the dark corner.
14. As a Dealer, I want wall edges to be soft where the photo is soft, so that the result does not look cut out and pasted on.
15. As a Dealer, I want to correct the detected walls with a single tap when they are wrong, so that a mistake costs me a moment rather than a consultation.
16. As a Dealer, I want to merge two regions the app split wrongly, so that one wall is treated as one wall.
17. As a Dealer, I want to split a region the app merged wrongly, so that I can treat a corner as two walls.
18. As a Dealer, I want to add a wall the app missed entirely, so that an unusual room still works.
19. As a Dealer, I want the app to fall back to letting me tap the walls when automatic detection finds nothing, so that I am never stuck with no way forward.

### Choosing a Shade

20. As a Dealer, I want to search by **Shade Code**, so that when the Customer points at a chip in the Fandeck I can bring it up immediately.
21. As a Dealer, I want to search by Shade name, so that a Customer who remembers "Almond" and not a number can still be served.
22. As a Dealer, I want to browse the whole **Catalogue** on screen, so that a Customer with no starting point can explore.
23. As a Dealer, I want the Catalogue grouped by **Shade Family**, so that browsing a thousand Shades is navigable.
24. As a Dealer, I want a row of recently used Shades, so that I can flick back to something we looked at two minutes ago.
25. As a Dealer, I want suggested Shades to start from, so that an undecided Customer has somewhere to begin.
26. As a Dealer, I want to see the Shade Code clearly on every swatch, so that I can pull the physical chip from the Fandeck to confirm the real colour.
27. As a Dealer, I want to know which **Finish** options a Shade is available in, so that I can quote the right product.

### Seeing the room repainted

28. As a Dealer, I want the room to update as soon as I tap a Shade, so that the Customer experiences it as instant.
29. As a Dealer, I want the repainted wall to keep its shadows, so that the result looks like a photograph rather than a drawing.
30. As a Dealer, I want the repainted wall to keep its texture, so that roller marks and plaster grain still read as a real wall.
31. As a Dealer, I want the repainted wall to keep its corner darkening and light falloff, so that the room keeps its depth.
32. As a Dealer, I want the wall to look like it belongs in the room's lighting, so that a warm-lit room does not end up with one oddly cool wall.
33. As a Dealer, I want to switch to **True Colour Mode**, so that I can answer the Customer when they ask whether that is really the colour on the chip.
34. As a Dealer, I want **Realistic Mode** to be the default, so that the normal case looks right without me doing anything.
35. As a Dealer, I want to paint one wall a different Shade from the others, so that I can show and sell an **Accent Wall**.
36. As a Dealer, I want each Wall Plane to hold its own Shade independently, so that a two-tone scheme is possible.
37. As a Dealer, I want a clean edge where two walls meet, so that a corner between two different Shades looks like a real corner.
38. As a Dealer, I want a dark wall repainted in a pale Shade to still look acceptable, so that the Customer most wanting a change is not the one shown the worst result.
39. As a Dealer, I want to compare before and after, so that the Customer can see the difference rather than just the outcome.

### Keeping the work

40. As a Dealer, I want the Consultation saved automatically, so that I do not lose it by forgetting to press something.
41. As a Dealer, I want to group a Customer's Consultations into a **Bundle**, so that one client's work stays together.
42. As a Dealer, I want to rename a Bundle, so that I can label it the way I think about the job rather than by a customer record.
43. As a Dealer, I want to reopen a Bundle when a Customer returns, so that we continue rather than start again.
44. As a Dealer, I want a reopened Consultation to show exactly what the Customer saw last time, so that the tool never contradicts a decision they already made.
45. As a Dealer, I want to try new Shades on a reopened photo without waiting for the whole preparation again, so that a return visit is faster than a first one.
46. As a Dealer, I want to see what was already tried and rejected, so that I do not show the Customer the same thing twice.
47. As a Dealer, I want to delete a Bundle or a Consultation, so that I control what is kept on my machine.
48. As a Dealer, I want to be warned before my disk fills up, so that the app does not fail in the middle of a consultation.
49. As a Dealer, I want to see which Bundles are using the most space, so that deciding what to delete is informed rather than guesswork.

### Sending it home with the Customer

50. As a Dealer, I want to export the rendered room as an image, so that the Customer can take the idea away with them.
51. As a Dealer, I want the exported file named after the Shade, so that there is at least some record of which colour it was.
52. As a Dealer, I want to share the export through whatever the Customer uses, so that I am not forced into one messaging app.
53. As a Dealer, I want the exported image at full quality, so that it still looks right on the Customer's phone.

### When things go wrong

54. As a Dealer, I want the app to keep working when it cannot find a wall, so that an awkward photo does not end the consultation.
55. As a Dealer, I want the app to accept a poor-quality photo and warn me, rather than refusing it, so that a Customer who brought only one photo is still served.
56. As a Dealer, I want the app to recover on its own if part of it stops, so that a technical fault does not become the Customer's problem.
57. As a Dealer, I want a clear explanation if a component was removed by my antivirus, so that I have some chance of fixing it.
58. As a Dealer, I want failures to never leave me at a dead end, so that there is always something I can do next.

### Running on my machine

59. As a Dealer, I want the app to work without an internet connection, so that a dropped line does not cost me a sale.
60. As a Dealer, I want Customer photos to stay on my computer, so that I am not responsible for other people's data leaving my shop.
61. As a Dealer, I want the app to run acceptably on the computer I already own, so that using it does not require buying hardware.
62. As a Dealer, I want the app to use my graphics card if I have one, so that better hardware gives a better experience.
63. As a Dealer, I want to choose between faster and better quality, so that I can trade one for the other when I am busy.

### Evaluating the project

64. As a project member, I want every render to record the settings that produced it, so that measurements taken on different machines remain comparable.
65. As a project member, I want to measure wall detection against hand-labelled photos, so that Objective 3 has a defensible number.
66. As a project member, I want to measure the rendered wall's colour against the Shade requested, so that render fidelity is proven rather than asserted.
67. As a project member, I want to measure how long each stage takes on a given machine, so that performance claims are evidence-based.
68. As a project member, I want to swap in a different Catalogue without changing code, so that the app is not welded to one manufacturer.

---

## Implementation Decisions

### Overall shape

Three parts, per ADR-0001:

- **Python inference service** — all image and model work, exposed over HTTP on localhost.
- **Electron shell** — hosts the UI, spawns and supervises the Python service as a child process.
- **React UI** — talks only to the service's HTTP contract.

The same React application against the same contract can later be served from a server for the web
target. One codebase, two deployments.

### The REST contract

```
POST   /sessions              (photo upload) → { session_id }   ← processing starts here
GET    /sessions/{id}/events                                     ← SSE progress stream
GET    /sessions/{id}/planes                                     ← Wall Planes, once ready
POST   /sessions/{id}/renders { assignments, mode }               ← one per Shade change
DELETE /sessions/{id}
```

**Encode-once is enforced structurally, by omission.** A photo enters only through `POST /sessions`;
every render refers to a `session_id`. There is deliberately **no endpoint accepting an image and a
Shade together**, so re-encoding cannot be expressed rather than merely being discouraged.

`assignments` maps each Wall Plane to a Shade Code. `mode` selects Realistic or True Colour.

Progress is delivered by **server-sent events** — plain HTTP, so it survives the lift to a server;
one-way, which is all that is needed.

### Service security

Bind to an **OS-assigned free port**. Generate a **fresh secret per launch**, passed by Electron to
the UI, and require it on every request. Localhost is not private: any local process, and any web
page open in the Dealer's browser, can otherwise reach the service and read stored Customer photos.

### Segmentation pipeline

1. An **ADE20K-trained semantic model** labels the scene; five of its classes are used — `wall`,
   `floor`, `ceiling`, `windowpane`, `door`.
2. That wall region **constrains** SAM 2, which produces crisp boundaries.
3. Output is a **soft Alpha Matte**, never a binary mask.
4. The wall region is split into Wall Planes automatically using **vertical structure** — vanishing
   lines and strong vertical edges, plus shading-gradient reversal. Zero taps; merge and split are
   exposed only as corrections.

Boundary precision is **decoupled from network resolution**: the mask is upsampled and its boundary
band refined at full resolution with a cheap edge-aware pass, so perceived quality stays roughly
constant across hardware.

**Licensing:** the standard SegFormer ADE20K checkpoints are non-commercial and are used for
development only. Replacement is tracked in
[handoff/custom-wall-segmentation-model.md](../handoff/custom-wall-segmentation-model.md). Do not
distil from them.

### Electron shell

The Electron **main** process owns everything the renderer must not:

- Spawning and supervising the Python sidecar, including quiet restart on death and logging each
  restart so a recurring fault is not masked.
- Holding the service's port and per-launch secret.
- Native dialogs — opening a Room Photo, choosing an export destination, handing a file to the
  system share sheet.
- Reporting disk space for the low-disk warning.

The **renderer** hosts React and does no Node or filesystem work.

**Secret transfer — security-relevant.** `nodeIntegration` stays off and `contextIsolation` stays on.
A **preload script** uses `contextBridge` to expose a narrow API — an HTTP client that injects the
secret and the base URL — so the renderer can call the service without ever holding the raw secret
or being able to reach arbitrary hosts.

**SSE carries a constraint worth knowing up front:** the browser's `EventSource` API **cannot set
custom headers**, so the progress stream cannot authenticate the way every other request does.
Resolve by having the preload expose a fetch-based streaming reader (which *can* set headers) rather
than using `EventSource` directly. Passing the secret as a query parameter is the obvious
alternative and should be avoided — it leaks into logs.

### React UI

**Screens and surfaces:**

| Surface | Purpose |
|---|---|
| Boot | Shown until the service is up, the secret exchanged and models warmed. Minimum 2 seconds; longer if models need it. Plain-language progress. |
| Bundles | List of **Bundles**, renameable, with delete. Entry point on open. |
| Consultation | The main working surface: the Room Photo, detected **Wall Planes**, shade selection, before/after. |
| Catalogue | A panel within Consultation, not a separate screen — search, **Shade Family** grouping, recently used, suggestions. |
| Storage | Which Bundles consume space, so manual deletion is informed. |
| Settings | Execution profile override (faster vs better quality). |

**State.** Server state mirrors the session resource and is fetched from the contract rather than
duplicated; avoid a global store beyond what several surfaces genuinely share (active Bundle, active
Consultation, Catalogue index). The render result is server-owned — the UI holds the latest image
and the current assignment map, not a parallel model of the pipeline.

**Preview versus full resolution.** The UI requests a **~1 MP preview** for every Shade change while
the Dealer browses, and a **full-resolution render only on save or export**. This is the direct
consequence of the latency measurements; putting the rule in the UI rather than the service keeps
the contract honest — the service renders what it is asked for.

**Catalogue browsing must be virtualised.** A Fandeck runs to a thousand-plus Shades and rendering
that many swatches eagerly will stall a floor-tier machine. Every swatch shows its **Shade Code**
prominently, so the Dealer can pull the physical chip to confirm.

**Wall correction is tap-driven.** Tap to add a missed wall, tap to merge, tap to split. No brush
tools, no drag-to-draw — the interaction budget does not allow it, and the correction surface
doubles as the failure fallback when automatic detection finds nothing.

**Every surface needs its loading, empty and error state defined**, not just the happy path. For a
tool whose design goal is that the Dealer never looks incompetent, these are the states that decide
whether it succeeds.

**Open:** whether the shop PC is touchscreen. Tap targets, hover affordances and the correction
interaction all change if it is. Pair this with the Amol Kulkarni conversation.

### The render engine

```
light_map  =  linear_photo / base_colour                 ← ONCE per photo
new_wall   =  light_map × target_shade × light_tint      ← per Shade change
output     =  α × new_wall + (1 − α) × linear_photo
```

All steps in **linear RGB**, including the composite — compositing in gamma space produces dark
fringing at boundaries.

**Base Colour** is estimated **per group of Wall Planes sharing the same existing paint**, never per
plane. Per-plane estimation normalises every wall to the same brightness and flattens the room,
defeating the reason Wall Planes exist. Planes are grouped by colour similarity; a pre-existing
Accent Wall gets its own Base Colour.

Base Colour derivation: use only **fully-opaque** matte pixels, eroded inward (edge pixels are
contaminated); rank by **luminance**; take pixels near the **90th percentile**; take their **mean
RGB**. Not a per-channel percentile — that neutralises the wall's colour cast.

**Light Map channels:** three-channel when the existing wall is pale enough to carry signal in all
channels, sliding toward **single-brightness** as it saturates. On a deep red wall the blue channel
is near zero everywhere, so dividing by it amplifies noise rather than recovering information.

**Light tint:** the illuminant cancels when dividing by Base Colour, so the Shade must be tinted back
by a rough whole-image estimate. Without it, a warm-lit room gets one conspicuously cool wall.

**Noise:** smooth the Light Map in proportion to measured noise — heavily on dark underexposed
walls, barely at all on well-lit ones. Texture and noise occupy the same fine detail, so uniform
smoothing would flatten real walls.

**Corners:** every pixel belongs to **exactly one** Wall Plane. Soft matte edges are used only where
a wall meets a non-wall. Double-claimed pixels composite twice and produce a dark seam.

### Colour management

| Space | Job |
|---|---|
| **CIELAB** | Storing Catalogue Shades; measuring **Colour Difference (ΔE00)** |
| **Linear RGB** | The light maths |
| **sRGB** | Output to screen |

Pinned, not left to library defaults: Lab reference white **D65, 2° observer**; gamma means the
**piecewise sRGB transfer function**, not a 2.2 power curve.

### Performance

Measured in [spikes/latency/RESULTS.md](../../spikes/latency/RESULTS.md):

- **Render previews at ~1 MP (1280×720)** while browsing. Full-resolution per-tap costs 641 ms on a
  high-end i7 and an estimated 1–2.8 s on a shop PC — not viable. At 1 MP it stays 43–195 ms across
  the whole hardware range.
- **Full resolution only on save or export.**
- **Lookup tables for both gamma directions are mandatory.** 256 entries for linearising 8-bit input
  (exact, since photos are 8-bit); ~4096 for encoding. The encode runs every tap and is ~38% of the
  per-tap path.
- **Crop to the Wall Plane bounding box** before per-tap maths.
- These stages are **memory-bandwidth-bound**, not CPU-bound. Core count is nearly irrelevant.

**Model execution:** ONNX Runtime, with the variant selected per hardware tier by loading a different
file into an identical call site. Assume a **CPU-only shipping build** until the packaging question
is settled. Warm models during the boot screen so loading never enters the per-photo budget.

### Persistence

**Bundle** (renameable) → **Consultation** → **Photo** → **Wall Plane** → **Render**

SQLite in the OS per-user application data directory. Renders stored as **full-resolution lossless
PNG**; reopening shows the stored image, never a regenerated one.

Every Render records: the **execution profile**, the **rendering mode**, the **Shade Code**, its
**resolved colour values**, and the **Catalogue version and identity**. A saved Consultation whose
meaning silently changes when the Catalogue is updated is worse than one that is missing.

**No automatic deletion.** Paired with a low-disk warning and a storage view, since manual deletion
is meaningless if the Dealer cannot see what to delete.

### Catalogue

A **swappable, versioned data file** loaded into SQLite for fast search and grouping; the file
remains the source of truth. One Catalogue at a time. Per Shade: Shade Code, name, Shade Family,
Lab value. **Finish** is metadata only in V1 and does not affect the render.

Build against a public stand-in dataset until Arun Paint Industries' measured values arrive.

### Failure behaviour

Never dead-end. No wall detected → fall through to manual tap. Poor photo → proceed with a quality
note, never refuse. Service dies → restart quietly and resume, and log it so a recurring fault is
not masked. Model load failure → surface at boot, not mid-consultation.

### Progress messaging

Plain language, purposeful, never leaking machinery: *"Finding the walls in your photo…"*, *"Working
out how the light falls…"*, *"Sharpening the edges…"*, *"Mixing your shade…"* — never a model name
or the word "inference".

---

## Testing Decisions

### What makes a good test here

Assert **external behaviour**, never implementation. A test should survive swapping the semantic
model, changing the smoothing curve, or restructuring the service internals. Tests that assert
intermediate array shapes or that a particular function was called are liabilities — every one of
those internals is explicitly expected to change.

The Light Map, Base Colour grouping and boundary refinement are **implementation**. What the Dealer
sees, and what the contract returns, are **behaviour**.

### Seam 1 — the REST contract (integration)

The primary seam. Everything below it is exercised without being reached into.

- Session lifecycle: create, retrieve planes, render, delete.
- **Encode-once is structural:** assert the contract exposes no endpoint accepting an image and a
  Shade together, and that renders require an existing `session_id`.
- Multiple renders against one session do not re-run preparation.
- Progress events arrive in order and terminate.
- Assignments map Wall Planes to Shade Codes independently, so an Accent Wall is expressible.
- Realistic and True Colour modes both produce output and are recorded on the Render.
- Failure paths: unknown session, malformed assignment, unknown Shade Code, missing auth secret.
- Auth: requests without the per-launch secret are rejected.

Use small fixture photographs so model runs stay tolerable. These tests are slow by nature; keep
them few and behavioural.

### Seam 2 — the render engine (pure function, unit)

`(linear photo, Alpha Matte, Base Colour, target Shade, light tint) → image`. No I/O, no models, so
these are fast and deterministic — and colour correctness is **analytically checkable**.

- **Synthetic images with known answers.** Construct a photo as `known_shading × known_base`; assert
  output equals `known_shading × target` within tolerance. This is the core correctness property.
- Flat, evenly-lit wall → output is uniformly the target Shade.
- Shaded region stays proportionally darker after recolouring, and its chroma attenuates — the
  property the CIELAB shortcut would have lost.
- Texture present in the input survives to the output.
- Alpha of 0 leaves pixels untouched; alpha of 1 fully replaces; fractional alpha blends in linear
  space.
- Saturated Base Colour does **not** produce runaway values — the saturation blend engages.
- Two Wall Planes with different Base Colours retain their relative brightness (the regression test
  for the per-plane flattening bug).
- Corner pixels belong to exactly one plane; no double-compositing seam.
- Gamma lookup tables agree with the analytic transfer function within tolerance.
- Dark input plus pale target degrades gracefully rather than producing NaN or wild values.

### Deliberately not seams

- **The SAM 2 and semantic model adapters.** Exercised through Seam 1. Mocking them would assert
  only that our mocks work.
- **The React UI.** A conscious gap in V1, accepted to keep the seam count low. The UI holds the
  latest render and the current assignment map, not a parallel model of the pipeline, so almost all
  logic sits below the contract and the remaining surface is thin enough to verify by running it.

  **Two pieces of UI logic are genuinely non-trivial, and should be extracted as pure functions and
  unit-tested if they grow:** the preview-versus-full-resolution rule, and the Wall Plane
  merge/split state transitions. Both are decision logic wearing UI clothing.

  Revisit this exclusion if UI logic accumulates beyond that. The honest risk is that "thin enough
  to verify by running it" quietly stops being true and nobody notices.

### Prior art

None — this is the first code in the repository. `spikes/latency/bench_render_loop.py` is the
closest existing reference for how the render maths is expressed, and its synthetic-array approach
is the model for Seam 2's fixtures.

---

## Out of Scope

- **Shade Reading** — reading a wall's existing colour and matching it to the Catalogue. The end
  goal, deliberately deferred. See
  [handoff/objective-2-colour-accuracy.md](../handoff/objective-2-colour-accuracy.md).
- **Room-aware suggestions.** V1 suggestions are curated and popular Shades only, with no reading of
  the current wall. This keeps the scope boundary clean.
- **Web deployment.** Architecturally supported by the shared contract; not shipped in V1.
- **The interior design and architecture use case.** A designer's interaction budget is the opposite
  of a counter-side Dealer's, and the two would pull the UI apart.
- **Cross-brand matching.** One Catalogue at a time.
- **Specular and gloss handling.** Highlights are the lamp's colour, not the paint's, and separating
  them from a single photo is unreliable. Negligible on matte.
- **Switchplates, sockets and pipes.** ADE20K has no such classes; they will be painted over in V1
  and are addressed by the replacement model.
- **Code signing.** Shipping unsigned; only a registered business is eligible for a certificate.
- **Multi-user, sync, accounts, telemetry.** Single machine, single Dealer.
- **The replacement segmentation model.** Tracked separately; required before commercial deployment,
  not before V1.

---

## Further Notes

**The one unverified assumption.** The interaction budget — roughly three taps and under thirty
seconds — is inferred from what a counter-side consultation looks like, not confirmed. It drives the
automation bar, the no-confirmation-step rule and the single-tap correction rule. Confirm with
Mr. Amol Kulkarni before building far into the UI; several decisions change shape if the real floor
is a sit-down consultation.

**Confirm alongside the persona question:** whether the shop PC is a **touchscreen**. Tap targets,
hover affordances and the whole wall-correction interaction change if it is, and it is cheap to ask
in the same conversation.

**Two limits to communicate rather than hide.** Dark walls repainted in pale Shades cannot recover
detail the camera never captured. Gloss highlights will be tinted wrongly. Both are better said out
loud than discovered by a Customer.

**Measurement before optimisation.** The audit and the latency spike each overturned an assumption —
that the SAM 2 encode was the bottleneck, and that per-plane Base Colour was correct. The remaining
numeric thresholds (colour grouping, saturation blend, noise curve, contested-pixel rule) are
deliberately left as tunable constants. Pick plausible starting values and tune them against real
photographs; deciding them in the abstract means deciding them twice.

**Part 2 of the latency spike is outstanding** — SAM 2 encode, semantic pass, boundary refinement,
model load time, peak RAM, and whether DirectML helps on integrated graphics. Those feed the tier
table, which is still unwritten.
