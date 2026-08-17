# SpectraPaint — Design Decisions

**Status:** Living document · **Last updated:** 2026-08-15

Running record of decisions made during the design grilling session. Each entry states what was
decided and why, so nobody has to re-argue it later. Vocabulary is defined in
[../CONTEXT.md](../CONTEXT.md).

---

## 0. Scope

**Decided:** V1 is **one complete path, desktop only**. Shade reading is the **end goal, not
abandoned**.

**V1 — must work end to end:**

Room photo in → wall planes found automatically → dealer picks a shade → realistic render → save
and export the before-and-after.

Desktop Electron only. The web build stays *possible* via the shared REST contract but is not
shipped.

**Beyond V1 — the stated end goal:** add **shade reading** (read the existing wall colour, match it
to the catalogue), completing all three of the report's objectives.

**Explicitly out of scope for V1:** the report's second application area, *Interior Design and
Architecture — pre-execution colour planning and client approval*. This is deliberate, not an
oversight. A designer planning a commercial space is time-rich and precision-hungry, which is the
**opposite** interaction budget from §2's counter-side dealer, and the two would pull the UI in
opposing directions. Revisit as a second interaction profile after V1.

---

## 1. Capture is uncontrolled

**Decided (constraint, not preference):** input is a photograph from an **arbitrary mobile phone**.
Device varies by user. There is no fixed camera, no calibrated rig, and no guaranteed reference
target in the frame.

This is the single hardest constraint on the project and almost everything else follows from it. A
phone JPEG has already had auto white balance, a tone curve, a per-scene 3D LUT and often HDR fusion
baked in by the device before we ever see it, so the true surface colour cannot be recovered
reliably.

**Why the project survives this:** recolouring and shade reading have very different accuracy needs.
Recolouring does *not* require knowing the wall's current colour — only how light falls on it — and
errors in that estimate push the render wrong *in the same direction as the rest of the photo*, so
the result still looks consistent. Shade reading has no such escape. That asymmetry is why V1 is
recolouring only.

Full analysis in [handoff/objective-2-colour-accuracy.md](./handoff/objective-2-colour-accuracy.md).

---

## 2. Who uses it, and how long they have

**Decided:** The dealer operates it at the counter, with customers waiting. Budget per photo:
roughly **3 taps and under 30 seconds**.

**Consequences that flow from this:**

- Automatic wall detection must be right in the common case. Every correction is a moment where the
  dealer looks incompetent in front of a customer.
- Corrections must be **single taps, never brush-editing**.
- A mandatory confirmation step is itself a tap we cannot afford. Default to acting, not asking.

**⚠ Unverified — highest-leverage open question in the project.** This is an inference about Arun
Paint Industries' shop floor, not a verified fact, and the entire interaction budget cascades from
it. The report lists **Mr. Amol Kulkarni** for "domain consultation and requirement validation" —
one conversation confirms or corrects it. See §12.

**For contrast, what a dealer does today:** flips a physical fandeck of 1000+ chips with the
customer and guesses. Existing paint-company visualizers use generic stock room templates, not the
customer's actual room. So the competition is a shade card and imagination — a low bar for
usefulness, a high bar for trust.

---

## 3. Deployment and hardware

**Decided:** Local-first inference over a localhost REST contract, with hardware-adaptive execution.

Full reasoning in [adr/0001-local-first-inference-over-localhost-rest.md](./adr/0001-local-first-inference-over-localhost-rest.md).

Summary:

- Python inference runs as a REST service on localhost; Electron hosts the React UI which talks to
  it. The same React app and the same contract lift server-side later for the web target.
- Floor tier is a **CPU-only office PC, no discrete GPU**.
- The active **execution profile is auto-detected, dealer-overridable, and stamped into every saved
  render and every benchmark number.**
- **Encode-once discipline must be enforced structurally.** SAM 2's encoder is expensive and its
  decoder is milliseconds. The API shape must make re-encoding impossible, not merely discouraged.

### Packaging: a frozen Python sidecar

**Decided:** freeze the Python service with PyInstaller and ship it inside the Electron app, which
launches it as a background process. A dealer never installs Python.

**Why not drop Python entirely** (running the ONNX models through Node and doing the colour maths in
JavaScript, which would delete this whole problem): the *classical* computer vision has no good
JavaScript equivalent. Vanishing-line detection for plane splitting and the guided-filter boundary
refinement live in OpenCV, and reimplementing them ourselves is riskier than packaging pain. The
trade is packaging work versus reimplementation work — we chose packaging, because the algorithms
already exist.

**Budget real time for this.** Large installer and a separate build per platform.

### Code signing: shipping unsigned

**Decided:** ship **unsigned**, permanently. No code-signing certificate will be obtained.

**What this costs us.** Unsigned software triggers Windows' *"Windows protected your PC"* warning,
which most people read as *this is malware*. Worse, **malware authors also use PyInstaller** to
bundle Python into a single executable, so antivirus engines treat that structure as suspicious in
itself. Our benign inference sidecar looks structurally like something they are trained to catch,
and it can be **quarantined** rather than merely warned about — after which the app stops working on
that machine.

**Why we cannot simply fix it:** OV and EV certificates require a **registered business** — the CA
verifies incorporation documents and calls a listed business number. A student cannot obtain one as
an individual; only Arun Paint Industries would be eligible. There is no free option Windows trusts
for closed-source software.

**Mitigations, since prevention is out of reach:**

- The **boot screen** (below) already surfaces service-start failures, so a quarantined sidecar
  becomes a clear message at launch rather than a mystery mid-consultation.
- That message must **name the likely cause and the remedy** — a dealer would never guess that their
  antivirus removed a component, or that it can be restored from quarantine.
- **Microsoft's false-positive review is free and requires no certificate.** Use it as a remedy if
  this actually bites in practice.

**Revisit if** dealers report installs failing. The eligible party (the partner) can obtain a
certificate at any point; verification takes up to two weeks.

### The REST contract

**Decided:** a session-oriented contract, with progress delivered by **server-sent events**.

```
POST   /sessions              (photo upload) → { session_id }   ← processing starts here
GET    /sessions/{id}/events                                     ← SSE progress stream
GET    /sessions/{id}/planes                                     ← wall planes, once ready
POST   /sessions/{id}/renders { assignments, mode }               ← one per shade change
DELETE /sessions/{id}
```

**This shape is what makes encode-once structural rather than a convention people remember.** A
photo can only enter through `POST /sessions`; every render refers to a `session_id`. There is
deliberately **no endpoint accepting an image and a shade together**, so re-encoding is not something
to avoid — it cannot be expressed. ADR-0001's requirement is satisfied by *omitting* an endpoint
rather than by adding a guard.

`mode` carries realistic-vs-true-colour (§6). Processing begins on upload, not on render request, so
the expensive work overlaps with the dealer talking to the customer (§13).

**Why SSE for progress:** it is plain HTTP, so it **lifts to a server unchanged** — which the
one-codebase-two-deployments argument depends on. Progress flows one way only, so WebSocket's
bidirectionality would be unused capability. And the code reads as *"when a message arrives, show
it"*, with no timer or change-detection bookkeeping.

**Rejected:** piping progress through Electron's child-process stream. It works only because Python
is a local child process; a server deployment has no such channel, so it would require a second
mechanism for the web target and break the shared contract. Polling was a close second — genuinely
defensible on localhost, where the traffic costs nothing and a 200ms interval is imperceptible — but
it trades cleaner code for more state to manage.

### Open: tier definitions

The tier table is **not yet written** and is required before implementation:

| Needed | Detail |
|---|---|
| Tier list | Names, and the detection rule for each (available execution providers? VRAM? a startup benchmark probe?) |
| Per tier | Which `.onnx` variant, and what encode resolution |
| Profile stamp | Exact fields recorded on each render |

### Correction: GPU support is a packaging decision, not a code decision

An earlier claim that an execution-provider list gives "opportunistic GPU use with no branching"
was too clean:

- `CUDAExecutionProvider` is **not** in the standard `onnxruntime` package. It requires
  `onnxruntime-gpu`, which pulls in CUDA/cuDNN at hundreds of MB — directly undercutting the
  small-installer argument that justified dropping PyTorch.
- CUDA is NVIDIA-only. On a Windows office PC with integrated graphics — our actual floor tier —
  the relevant provider is **DirectML**, not CUDA.

**Open:** which ORT package ships, whether DirectML is included, and whether GPU support is a
separate build. Until decided, assume **CPU-only shipping build**.

---

## 4. What counts as a "wall"

**Decided:** The unit is a **wall plane** — each visible wall face is its own instance, coloured
independently.

**Why:**

- Different wall faces sit at different angles to the light, so they differ in brightness. That
  difference is the main depth cue in the photo. Colour them all as one region and the room goes
  flat and reads as fake.
- **Accent walls are a real paint-retail upsell.** Dealers will want one face in a different shade.

---

## 5. How walls are found

**Decided:** Semantic model proposes → SAM 2 refines → soft alpha matte → automatic plane split.

**Pipeline:**

1. An **ADE20K-trained semantic segmentation model** labels the scene. ADE20K is a 150-class model;
   we use five of those classes — `wall`, `floor`, `ceiling`, `windowpane`, `door`.
2. That wall region **constrains** SAM 2, which returns crisp boundaries.
3. Output is a **soft alpha matte, never a binary mask.**
4. Plane splitting from **vertical structure** — vanishing lines / strong vertical edges, plus
   shading-gradient reversal. Split automatically and render immediately, **zero taps**. Merge and
   split are exposed only as a correction the dealer reaches for.

**Key reasons:**

- **SAM 2 is class-agnostic.** It has no concept of "wall" — its automatic mode returns dozens to
  hundreds of unlabelled segments. Something must supply wall-ness; ADE20K's `wall` class does.
- **Shadows must stay inside the wall region.** A shadow cast on a wall *is still the wall*. SAM 2
  is appearance-driven, so a strong shadow boundary looks to it like an object boundary — it may cut
  the dark strip near the ceiling out of the mask, leaving a visible ghost of the old paint.
  Constraining SAM 2 with the semantic region **substantially reduces** this, because the ADE20K
  `wall` class is trained across lighting conditions. It does not *prevent* it — an appearance-driven
  decoder can still cut at a strong shadow edge.
- **Hard mask edges are the single biggest realism tell.** Real wall boundaries have lens blur and
  antialiasing; a binary mask gives a razor edge that reads as edited.
- **Boundary precision is decoupled from network resolution.** Whatever resolution the tier affords
  for encoding, the mask is upsampled and its boundary band refined at full resolution with a cheap
  edge-aware pass. Since perceived quality depends mostly on boundary accuracy, this keeps
  floor-tier output presentable.

### ⚠ Model licensing — decided, with a dependency

The official **SegFormer / MiT ADE20K checkpoints are published by NVIDIA under a non-commercial
research licence.** SpectraPaint is intended for commercial deployment in dealerships, so **these
weights cannot ship.**

**Decided:** use SegFormer for **development and demonstration only**, and **build our own wall
segmentation model** of equal or better accuracy to replace it before any commercial deployment.

Plan: [handoff/custom-wall-segmentation-model.md](./handoff/custom-wall-segmentation-model.md).

Two consequences worth stating plainly:

- **This is a real, tracked deliverable, not an intention.** A "swap it later" that lives only in
  someone's head is how an industry partner ends up with software they cannot legally use.
- **Do not distil from the SegFormer checkpoints**, and do not use them to auto-label our training
  images. Training a commercial model from a non-commercial one is what that licence exists to
  prevent, and the derived model inherits the restriction. Using SegFormer purely as a *measured
  baseline* for comparison is fine.

Encouraging: our task is far narrower than ADE20K's 150 classes — we need about six indoor classes —
so a much smaller model can beat a general scene parser **on wall accuracy specifically**. Public
indoor datasets are also heavily Western-skewed, so a modest set of hand-labelled local rooms shot
on real customer phones is likely worth more than a large mismatched dataset, and doubles as the
ground-truth set §10 already requires.

SAM 2 itself is Apache-2.0 and is fine. The licence of **every** shipped weight must be recorded.

### Correction: the exclusion list is not fully deliverable

Earlier this document said to exclude "switchplates, sockets, mirrors, wall art, pipes."

ADE20K **has** `mirror` and `painting`. It has **no class** for switchplate, electrical socket or
pipe — the semantic model will label all three as `wall`, and SAM 2 constrained to the wall region
has no reason to remove them. **They will be painted over.**

**Decided:** **accept for V1**, and **add switchplate / socket / pipe as classes when training our
own model** (task in [handoff/custom-wall-segmentation-model.md](./handoff/custom-wall-segmentation-model.md)).

The timing is favourable: we are already labelling our own photographs of real rooms for the licence
replacement, so adding a few small classes while someone is already drawing wall boundaries costs
little — and it makes our model genuinely *better* than the baseline it replaces, not merely legally
shippable.

**Accepted cost:** V1 demos and early dealer trials will show painted-over switches, which is
exactly when first impressions form. This is the most customer-visible flaw in the render — nobody
needs to be told a dark-blue light switch looks wrong.

**Rejected:** a heuristic detector for small bright rectangles. It misfires on picture frames, vents,
reflections and light patches, and every false positive leaves an unpainted hole in the middle of the
wall — worse than the original problem.

**The principle still holds:** exclusion is **semantic, not photometric**. The test is "is this wall
material?", never "does this look like the rest of the wall?" Include shadows, sheen variation and
texture.

### Correction: furniture occlusion is helped, not solved

ADE20K has no single `furniture` class, and a small semantic model's boundaries around furniture are
exactly where this pipeline is weakest. Occlusion is *substantially* handled, not free.

---

## 6. How a shade becomes pixels

**Decided:** Divide-and-multiply ("ratio relighting") in **linear RGB**.

```
light_map  =  photo / base_colour                        ← computed ONCE per photo
new_wall   =  light_map × target_shade × light_tint      ← one multiply per shade change
output     =  α × new_wall + (1 − α) × photo
```

All three steps happen in **linear RGB**, including the alpha composite. Compositing in gamma space
produces dark fringing at the boundary.

**Why this works:** a wall carries one paint colour, so its *large-scale* variation — bright near the
window, dark in the corner, roller texture, corner falloff — is lighting, not paint. All of it lives
in `light_map`, carried through untouched. **There is no shadow-handling step; we simply never
modify shadows.** Only the flat base colour is swapped.

**Why not the obvious shortcut** (Lab: keep `L*`, overwrite `a*b*`): it treats shadow as a
*lightness* phenomenon only. In reality less light means less of everything — a shadowed region is
both darker *and* less colourful. Overwrite the colour channels uniformly and every shadow returns
at full chroma, so the wall looks flat, plasticky and stuck-on. Multiplication attenuates chroma in
shadow automatically; the Lab shortcut cannot.

**Honest caveat on the premise:** "all variation is lighting" is true for *large-scale* variation.
Genuine reflectance defects — stains, patches, previous touch-ups — are **not** lighting, and §5
deliberately keeps them inside the wall region. They ride through the light map and get re-tinted by
the new shade. That is knowingly accepted, and is arguably correct behaviour anyway: a stain on a
repainted wall would be covered, so re-tinting it is closer to truth than preserving it.

### The room's light colour must be added back

**Decided:** tint the target shade by a rough estimate of the room's light — **realistic by
default** — with a **"true colour" toggle** showing the shade under neutral light.

**The problem this fixes, which is easy to miss:** dividing by `base_colour` cancels out the
*illuminant* along with the old paint, because `base_colour` already contains it. So
`light_map × target_shade` renders the shade **as it would look under neutral white light**. Drop
that into a tungsten-lit room and every other surface is warm while the wall is clean and cool —
it reads as pasted-in, and the cause is not obvious from looking at it.

**This does not reopen Objective 2.** A rough whole-image estimate (grey-world or similar) is
enough. It is *precise* colour reading that is hard; approximate tint is cheap.

**Why the toggle, not just one mode:** rendering *faithfully* and rendering *realistically* are
genuinely different goals. A customer comparing the screen to the physical chip will ask "is that
the real colour?" and the dealer needs an answer. The toggle also resolves a metric conflict —
**§10's shade-fidelity measurement is taken in true-colour mode**, so realism tinting cannot
silently degrade the reported number.

Saved renders must record which mode produced them.

### Light map: blend between one channel and three, by saturation

**Decided:** use a three-channel light map when the current wall is pale enough that all channels
carry signal, sliding toward a **single-brightness** light map as the wall gets more saturated.

**The failure this prevents:** on a deep red wall, the camera's blue channel is near zero across the
*entire* wall — no signal, only sensor noise. Dividing by it doesn't recover information that was
never captured; it amplifies noise into the render. Saturated walls are common in Indian homes, so
this is not an edge case.

**Why blending rather than always using one channel:** how much light hits a surface is essentially
*one* number. The three-channel version only buys the fact that shadows are a slightly different
*colour* than lit areas — a real gain on a pale wall, meaningless on a saturated one. Most walls
people repaint are white, cream or beige, so the common case keeps the better treatment and the
minority case degrades safely.

**Open:** the blend curve, and whether the transition is visible on two similar walls landing either
side of it.

### Noise: clean the light map in proportion to how noisy it is

**Decided:** measure how noisy each wall region actually is and smooth the light map proportionally —
heavily on dark, underexposed walls, barely at all on well-lit ones.

**The problem this addresses** is not clipping, which is what it looks like. It is **missing
information**. A dark wall is captured using only a small handful of the camera's brightness levels;
repainting it cream stretches those few levels across a wide bright range, and the gaps between them
surface as blotches, banding and speckle. The camera never recorded the detail, so nothing recovers
it.

**Why proportional rather than uniform:** roller texture and plaster grain live in exactly the same
fine detail as the noise. Smooth too hard and the wall goes plastic and flat — the look this whole
design fights. Targeting the smoothing at regions that measurably need it preserves texture
wherever it was genuinely captured.

**Open:** the noise estimate and the smoothing curve (§12 item 20). A wall that is half in shadow may
receive uneven treatment.

### Corners: every pixel belongs to exactly one plane

**Decided:** adjacent wall planes are split cleanly at the corner — no pixel is claimed by two
planes. Soft matte edges are used **only where a wall meets something that is not a wall**.

**The bug this prevents:** if both planes claim the same boundary pixels, compositing paints them
twice, producing a dark or muddy line down the corner. It presents as a mysterious rendering
artefact and takes far longer to diagnose than it should. Exclusive assignment makes it
*structurally impossible* rather than something to remember.

**Why the two edge types differ:** where a wall meets furniture, a window or the ceiling, the
photograph genuinely is soft — lens blur and antialiasing — and a soft matte is what stops the
render looking cut out. But a wall-to-wall boundary is an **architectural corner**, sharp in real
life, and it *should* stay crisp when two planes carry different shades. Blending there would mix
two colours into a stripe matching neither — most visible exactly where an accent wall meets its
neighbour.

**Open:** the assignment rule for contested pixels. Genuinely rounded corners will render slightly
harder than reality; accepted.

### Base colour — grouped by existing paint

**Decided:** estimate **one base colour per group of wall planes that share the same existing
paint** — never one per plane.

**This corrects an outright bug in the earlier design.** If each plane divides by its *own* base,
every plane's light map peaks at 1.0, so a sunlit wall and a shadowed wall come back **equally
bright** after recolouring. That erases the inter-plane brightness difference which §4 exists
entirely to protect — the room flattens, which is the exact failure per-plane segmentation was
chosen to avoid.

Grouping rule: compare each plane's colour; planes that look like the same paint share one base, so
their relative brightness survives. Planes that are clearly a different colour — a pre-existing
accent wall — get their own base.

**Open:** the "same colour" threshold. It will occasionally group or split wrongly.

### Base colour — how the value is derived

The base colour is an **RGB triple**, not a scalar. Derivation:

0. Use **only fully-opaque pixels** of the alpha matte, eroded inward from the boundary. Partially
   covered edge pixels are contaminated by whatever lies behind the wall and would pollute the
   estimate.
1. Rank the group's wall pixels by **luminance**.
2. Take pixels around the **~90th percentile** — "the wall in full light". Skipping the top few
   percent avoids being fooled by blown-out spots and shiny reflections.
3. Take the **mean RGB of those pixels**.

**Do not take a per-channel percentile independently** — that silently neutralises the wall's colour
cast, because each channel's 90th percentile comes from a different set of pixels.

**Error behaviour:** a *brightness* error in this estimate shifts the result's overall brightness but
leaves the pattern of light correct — a quality issue. A *chromatic* error produces a colour cast in
the result, which is a correctness issue. The two are not equally forgiving.

### Colour spaces — three jobs, no conflict

**Linear RGB and sRGB hold exactly the same colours.** The difference is only how the numbers are
written down; gamma squishes them to give more precision to dark tones. Linear undoes the squish so
arithmetic behaves like real light. What limits available colours is the **primaries**, not the
encoding.

**RAL is a catalogue, not a colour space** — a numbered list of standard colours. RAL Design is
defined in Lab directly; **RAL Classic is defined by physical reference samples**, so its published
Lab/sRGB values vary by source and gloss level. Same caution applies to a dealer's fandeck.
**CIELAB** *is* a space, and can describe every visible colour.

| Space | Job |
|---|---|
| **CIELAB** | Storing catalogue shades; measuring colour difference (ΔE00) |
| **Linear RGB** | The light maths — divide, multiply, composite |
| **sRGB** | What goes to the screen |

```
Catalogue shade (Lab) → linear RGB → maths → sRGB → screen
```

**Pinned conventions** (these must not be left to library defaults):

- Lab reference white **D65, 2° observer**. D50 vs D65 changes every catalogue conversion.
- "Gamma" means the **piecewise sRGB transfer function**, not a plain 2.2 power curve.

The maths must happen in linear because light adds and multiplies simply only there. Lab is warped
to match perception, so multiplying Lab values is physically meaningless — and shadows are a
multiplication in the real world.

**Gamut:** most real paint colours sit inside sRGB, since pigments are far less intense than pure
light — but **saturated yellows, oranges and some greens in real fandecks do fall outside**, and
those are common in retail. An out-of-gamut mapping policy is still open (see §12). The customer is
viewing an sRGB monitor regardless.

---

## 7. Where shades come from

**Decided:** Request Arun Paint Industries' real measured values; build against a **public stand-in
dataset** meanwhile so nothing is blocked.

The catalogue is a **swappable, versioned data file**, loaded into SQLite for fast search and
grouping. The file stays the source of truth. This turns a project-blocking external dependency into
a file swap, and lets the app serve a second manufacturer later without a rewrite.

**What we need per shade:** shade code, name, family, and a colour value in **Lab**.

**Decided: one catalogue at a time.** The app serves whichever single catalogue is loaded; swapping
the file serves a different dealer or manufacturer. Multiple brands cannot be searched together.

**Accepted cost:** cross-brand matching — answering *"I liked this other brand's colour, what's your
closest match?"*, which dealers are asked regularly — is off the table, and adding multi-brand
support later means migrating saved sessions whose shade codes carry no brand.

**Cheap hedge, take it now:** record **which catalogue** a session used, alongside the catalogue
version (§9). One field. It adds no multi-brand capability, but a future migration will know what
`2140` referred to instead of having to guess — two brands can easily share a code.

**Consequence:** true accuracy is unknown until their data arrives, so accuracy evaluation waits for
it.

---

## 8. How the dealer picks a shade

**Decided:** search by code or name, **plus** suggestions, **plus** a full browsable on-screen
catalogue. All three.

- **Search by shade code** is the primary path — the customer points at a chip in the fandeck and
  reads out the code.
- **Suggestions** cover the customer who wants to explore. In V1 these are **curated and popular
  shades only** — best-sellers, dealer-featured, recently used — with **no reading of the current
  wall at all**.

  This is deliberate. An earlier draft said suggestions came from "a rough read of the current
  wall", which quietly pulled parked shade-reading work into V1 and blurred the scope boundary.
  Curated suggestions have zero dependency on deferred work and are commercially useful anyway,
  since the dealer can promote what is in stock or high-margin. Room-aware suggestions become the
  first visible payoff of Objective 2 when it is unparked.
- **Full catalogue browse**, grouped by family, with a recently-used row so nobody scrolls a
  thousand tiles.

**Guard-rail, since we are now inviting people to judge colour on a monitor:** on-screen swatches
**narrow down**, they do not decide. Show the shade code prominently on every swatch so the dealer
can pull the physical chip to confirm. The screen finds candidates; the fandeck settles the
argument.

**Finish (matte/satin/gloss) is catalogue metadata only** in V1 — it does not change the preview,
since specular handling was deferred (§11).

---

## 9. What gets saved

**Decided:** Save sessions; dealer can delete; auto-clear after a set period.

Rationale: a **before-and-after the customer takes home** is a real sales tool — people leave, lose
their nerve, and don't come back. Reopening last week's session when a customer returns is a second
chance at the sale.

**Entity model:**

**Customer** (name, phone — optional, just enough to find them again) → **Session** (date, notes) →
**Photo** (image, EXIF, capture info) → **WallPlane** (alpha matte, plane index, base-colour group)
→ **Render** (which shade on which plane, timestamp).

Two non-obvious requirements:

- **Stamp the execution profile on every render.** Decided in §3, but it must physically live in
  this table or benchmark numbers stop being comparable.
- **Record which rendering mode was used** — realistic tint or true colour (§6). Otherwise a
  reopened session cannot be reproduced or explained.
- **Record which catalogue** the session used, not just its version (§7).
- **Save the shade code *and* its resolved colour values *and* the catalogue version.** If Arun
  updates their fandeck next year, `AP-2140` may mean a different colour. A saved session that
  silently changes meaning is worse than one that is missing.

### Storage format and reopening

**Decided:** store **everything at full resolution as lossless PNG**. Reopening a session shows the
image the customer actually saw — never a regenerated one.

**Why not regenerate:** between visits the app may have updated, the models may have changed, or the
catalogue may have been revised. Regenerating shows the customer something subtly different from
what they decided on, at the worst possible moment for the tool to disagree with itself.

**Why lossless PNG rather than truly uncompressed:** a 12-megapixel photo is 4000×3000, so raw is
~36 MB *per render*. Five shades in a session is ~180 MB and a hundred sessions is ~18 GB on a shop
PC nobody maintains. PNG is **already lossless** — identical pixels — at roughly a third the size.
Uncompressed would cost three times the disk for literally no quality benefit.

### Bundles, sharing, deletion

**Decided:** the dealer can group one client's sessions into a renameable **Bundle**, share a
render, and delete.

**Bundle** replaces the plain `Customer` grouping in the entity model above — dealers think in
*jobs*, not customer records, and a renameable label matches how they actually organise work:

**Bundle** (renameable) → **Session** → **Photo** → **WallPlane** → **Render**

**Decided: sharing produces a plain rendered JPEG.** No overlay, no branding, no before-and-after
composite. The JPEG is generated for sharing rather than handing out the PNG archive, and the
**shade code goes in the filename** (`AP-2140-Almond-Cream.jpg`) since that costs nothing.

**Known trade-off, accepted:** a shared render carries no visible record of which shade it was. The
customer gets home with a picture of their own room in a nice colour and no name for the colour —
the single most useful thing for closing the sale is absent from the one artifact they take away.
Messaging apps also frequently strip filenames, so the filename mitigation is partial at best.
Revisit if dealers report customers returning unable to name their choice.

**⚠ Sharing has a privacy consequence worth naming.** The moment a render can be shared,
photographs of customers' homes can leave the shop — the exposure ADR-0001 avoided by staying local.
Benign in the normal case (sending a customer their own room), but it is a deliberate hole in the
local-only posture, not an oversight.

### Retention: nothing is deleted automatically

**Decided:** **no auto-clear.** Data is removed only when the dealer chooses to remove it.

**The cost, stated plainly:** a 4000×3000 lossless PNG is roughly 10–15 MB. A shop doing ten
consultations a day at four shades each generates about **500 MB per day — roughly 15 GB per
month.** A typical shop PC fills within two years of steady use, sooner if business is good, and
nobody will be watching. The failure mode is the app breaking on a full disk *during a
consultation*.

**Two requirements that make manual-only viable** — manual deletion is meaningless if the dealer
cannot see what to delete, or only learns about the problem once it is one:

- **Warn on low disk space well before it is critical**, not at the point of failure.
- **Provide a storage view** showing which bundles consume the space, so deletion is an informed
  action rather than guesswork.

Revisit if real usage data shows shops filling disks faster than expected.

### Location

**Decided:** the database and images live in the OS standard **per-user application data
directory**, not beside the application. Survives reinstalls and upgrades, and needs no admin
rights to write.

---

## 9b. Continuous integration

**Decided:** GitHub Actions, **split by seam**, with a pull-request merge gate.

**Why CI is load-bearing here rather than hygiene:** V1 is broken into fifteen tickets worked in
**isolated fresh contexts**. No agent working one ticket can see what another built. A solo human
developer remembers what they broke; independent agents do not. **CI is the only integration memory
this project has.**

### Two lanes, because the seams have opposite cost profiles

| | Seam 2 — render engine | Seam 1 — REST contract |
|---|---|---|
| Needs | numpy only | SAM 2 + semantic model, GB of weights |
| Runtime | Seconds | Minutes |
| Runs | **Every push** | **Pull requests into `main`, and nightly** |

The repository is private, so Actions minutes are metered (roughly 2,000/month on Free, 3,000 on
Pro — the **GitHub Student Developer Pack grants Pro**). Running the model lane on every push would
exhaust that mid-month and produce a pipeline slow enough that people stop waiting for it.

### Merge gate

Branch per ticket → pull request → **green pipeline plus human review** before merge.

The pull request is the **only point where a human reads agent-written code before it lands**. The
diff is also a far better review surface than a terminal. The risk to watch is rubber-stamping: an
unread approval turns the gate into decoration.

### Model weights in CI

**Actions cache, keyed on model version, populated from the original upstream source.** The nightly
slow-lane run keeps the cache warm, so pull-request runs almost always hit it.

**Do not mirror the SegFormer weights into a GitHub Release.** Downloading non-commercially-licensed
checkpoints for development is one thing; **redistributing them is another**, and this project has
already had to be careful about exactly that licence. Mirroring is fine once our own model exists.

### Two jobs worth more here than in a typical project

- **Performance regression gate.** Measurement established that the per-shade render is the
  bottleneck (§13). A 3× regression there would kill the product and **no functional test would
  notice**. `spikes/latency/bench_render_loop.py` needs only numpy, so it can run on every push and
  fail past a threshold.
- **Licence gate.** Fail the build when an unapproved licence appears among dependencies or shipped
  weights. This guards a constraint the project has already nearly tripped over (§5).

### Status

Complete as of #16. What runs, and where:

| Workflow | Triggers | Does |
|---|---|---|
| `fast-lane.yml` — *Checks* | Every push, and PRs into `main`. Linux **and** Windows | Lint, typecheck, format, shell tests (§9d), model-free service tests. Licence gate on Linux only |
| `fast-lane.yml` — *Performance gate* | Every push. Linux | Per-shade render regression gate. A separate job, so it measures on a runner doing nothing else |
| `slow-lane.yml` | PRs into `main`, nightly at 02:30 UTC, and manually. Linux only | Restores the weight cache, fetches from upstream on a miss, verifies against the manifest, runs the `models`-marked contract tests |

**The pinned weights live in `models/manifest.toml`** — upstream repository, immutable revision,
sha256, licence, and whether the weight is shipped or development-only. That one file is the cache
key, the download list and the licence gate's input, so those three cannot drift apart.
`tools/fetch_models.py` fetches and verifies; a file whose hash does not match the manifest is
deleted rather than used, because it is not the weight whose licence was reviewed.

The cache is keyed on the pinned versions themselves rather than on the manifest file, so editing a
comment does not discard gigabytes. There are deliberately **no `restore-keys`**: a near-miss cache
hit would mean testing a different model version, which is worse than a slow download. The nightly
run exists for the cache rather than the tests — GitHub only lets a branch read caches from its own
ref or the default branch, so without a nightly run on `main` the first pull request of the day pays
the full download.

**The performance gate** is `spikes/latency/bench_render_loop.py --check`, against the budget in
`spikes/latency/perf-baseline.json`. Both the baseline and the multiplier that turns it into a
budget are recorded in that file, measured on the runner, with the date and the numpy version —
an implicit threshold is one nobody can argue with. It gates the two preview resolutions, since
those are what the Dealer actually browses at (§13, and the spike's own recommendation).

**The licence gate** is `tools/licence_gate.py`, with the policy in `tools/approved-licences.toml`.
It checks npm dependencies, Python dependencies and the weights in the manifest, and it fails if a
weight marked `shipped` carries a licence that is not approved for distribution, or if any weight
file has been committed to the repository at all. That last check is the one that matters: it is the
mechanism preventing the non-commercial SegFormer checkpoint from being mirrored or shipped (§5).

**`main` is protected** — no direct pushes, a green pipeline and a human review required to merge.
The branch-per-ticket workflow is written up in [conventions.md](./conventions.md) §7b.

**Useful coincidence:** the standard private-repo runner is 2-core / 7 GB — roughly **floor-tier
hardware**. Since the benchmark needs no models, CI doubles as a continuous floor-tier performance
check, which the whole local-first bet depends on.

---

## 9c. Development platforms

**Decided:** the shipping target is **Windows**. Development happens on **both Linux and Windows** —
contributors use either. The **packaged artifact is only ever validated on Windows**.

Recording this because none of it is derivable from the code, and a ticket worked in a fresh context
would otherwise assume the development machine and the target machine are the same thing.

### What this costs

Three failure modes pass on Linux and break on Windows, and all three land in the walking skeleton
(§13, ticket #1):

| Failure | Why Linux cannot catch it |
|---|---|
| **Orphaned sidecar on quit** | `SIGTERM` does not exist on Windows; `child.kill()` maps to `TerminateProcess` and a Python child can outlive the parent still holding the port. Needs a Windows branch — `taskkill /pid <n> /T /F` or a job object |
| **Antivirus quarantine** | Defender's reaction to an unsigned PyInstaller binary (§3) is unobservable off Windows, and it is the most likely reason an install dies in a shop |
| **Frozen binary correctness** | PyInstaller does not cross-compile. A Linux build proves nothing about the shipped artifact |

A Windows firewall prompt on first bind is a fourth, usually avoided by binding explicitly to
`127.0.0.1` rather than `0.0.0.0` — which the security decision (§13) already requires.

### Consequences

- **The fast lane runs on `ubuntu-latest` and `windows-latest` both** (§9b). This is the mechanism
  that catches process teardown and path handling permanently, rather than whenever someone
  remembers to check. The slow lane stays single-OS — model weights on two runners is not worth the
  metered minutes.
- **Tooling must be cross-platform.** No bash-only scripts in the contributor path, no `rm -rf` or
  bare `VAR=x cmd` in npm scripts, no hardcoded path separators. If a task genuinely needs a shell,
  it belongs in CI or in a Python script, not in a step a Windows contributor is expected to run.
- **Paths come from libraries, never composed by hand** — `app.getPath('userData')` in Electron and
  `platformdirs` in Python. This is what makes the §9 per-user app-data location work on both
  without branching.
- **`.gitattributes` normalises line endings**, so a Windows checkout does not produce a diff of the
  entire repository.
- **Python 3.12 is the requirement; `pyenv` is not.** conventions.md names `pyenv` because that is
  what the latency spike used — Windows contributors should use the python.org installer or `uv`.
  The version is the constraint; how it is installed is not.

### Manual Windows verification

CI does not cover the packaged installer, Defender, or the boot screen's quarantine message. Those
need a real Windows machine or VM, checked at a handful of points — after packaging lands, and
before any milestone demo. Not part of the per-ticket loop.

---

## 9d. A third, deliberately small test suite for the shell

**Decided:** keep the two seams as the project's testing story, and add a **small `vitest` suite**
covering only shell logic that neither seam can reach.

**Why an exception was needed at all.** The two seams are the REST contract and the render engine.
The walking skeleton (#1) is neither: the path validator that stops the renderer reaching arbitrary
hosts, the boot failure messages, and the rule for when the boot screen gives way all live in the
Electron and React layers. Under a strict two-seam reading they would ship with no automated cover
at all.

**What qualifies for it.** Pure functions where a silent regression is expensive and invisible:

| Covered | Why it earns a test |
|---|---|
| `contract-path.ts` | If the check loosens, the renderer can reach any host and *nothing else in the app notices* |
| `boot-messages.ts` | Asserts every failure says something, names no technique, and that the antivirus-quarantine wording survives an edit |
| `useBoot.ts` readiness rule | The 2-second floor and "wait for the service" rule, without a DOM |

**What does not.** No component rendering, no DOM harness, no Electron integration test, no mocking
of the sidecar. Those would be slow, brittle, and would duplicate what seam 1 already proves.
Anything that needs a real service is a seam-1 test.

**The guard against drift:** these are *pure functions only*. The moment a test needs a DOM, a mock
or a running Electron, it belongs in seam 1 instead — or it is testing implementation, which
conventions §6 already forbids.

Run with `npm test` at the repository root.

---

## 10. Evaluation

Parking shade reading removed the headline metric, so the results chapter rests on four measurements
that need no calibration:

| Measurement | How |
|---|---|
| **Wall detection accuracy** | Region overlap (IoU) against hand-labelled walls on a test set |
| **Speed per photo, per tier** | Direct timing; also validates the local-first bet |
| **Shade fidelity** | Measure the *rendered* wall's colour against the shade requested. Needs no calibration — both sides are numbers we control |
| **Realism** | Preference test with dealers and customers |

**Note on rigour:** the Objective 2 handoff rightly attacked that objective for naming no metric and
no ground truth. **Objectives 1 and 3 have the same weakness** — "realistic visualization" and
"automate segmentation" are equally unmeasured as written. The table above is the answer for
Objectives 1 and 3; the hand-labelled test set must actually be built.

---

## 11. Known limits — communicate, do not hide

- **Dark → light is fundamentally hard.** `light_map × target` clips when the original wall is dark
  and the target pale, and detail crushed in the original exposure cannot be recovered. Light → dark
  is easy. Tell dealers rather than hide it.
- **Shiny highlights are the lamp's colour, not the paint's.** Multiplying them by the new shade
  tints them wrongly. Negligible on matte, visible on satin and gloss. Specular separation was
  considered and **deferred** — it is unreliable from a single photo.
- **Very dark regions produce a noisy light map**, since dividing by small numbers amplifies noise.
  Needs clamping.
- **Switchplates, sockets and pipes will be painted over** (§5) — the most customer-visible flaw in
  V1. Fixed when our own model adds them as classes.
- **The app ships unsigned**, so Windows shows a publisher warning on install and antivirus may
  quarantine the Python sidecar (§3). Detectable at boot, not preventable.
- **A shared render carries no visible shade name** (§9) — only in the filename, which messaging
  apps often strip.
- **Saturated existing walls lose coloured shadows.** By design — see §6's saturation blend. The
  render stays correct, but loses a touch of realism exactly where the maths runs out of signal.
- **Cross-brand matching is not possible** (§7). One catalogue at a time.
- **Output is not bit-identical across hardware tiers.** The abstract promises "repeatable"
  visualization; tiering means the same photo yields slightly different masks on different machines.
  What we can promise is repeatability **within a given execution profile** — hence the stamp.

---

## 12. Open questions

| # | Question | Blocking | Owner | Due |
|---|---|---|---|---|
| 1 | **Confirm the dealer persona and tap budget with Mr. Amol Kulkarni** (§2) | Whole interaction design | — | — |
| 2 | **Build our own wall segmentation model** to replace SegFormer (§5) — *decided, planned, [handoff](./handoff/custom-wall-segmentation-model.md)*. First step: verify dataset licences | Commercial deployment | — | — |
| 3 | Which ORT package ships; DirectML or separate GPU build (§3) | Installer, tier table | — | — |
| 4 | Tier table: names, detection rules, variants, resolutions (§3) | Implementation | — | — |
| 5 | ~~REST contract~~ — **decided:** session-oriented, SSE progress (§3) | Implementation | — | — |
| 6 | ~~Preview vs full-res render~~ — **measured & decided:** browse at ~1 MP, full-res on export only. See [spike results](../spikes/latency/RESULTS.md). Remaining: per-stage budget for the *model* stages (Part 2) | Meeting the 30s budget | — | — |
| 7 | "Same existing paint" grouping threshold (§6) | Render correctness | — | — |
| 8 | Out-of-gamut mapping policy, and clipping policy for light shades (§6, §11) | Render correctness | — | — |
| 9 | Switchplate/socket exclusion — accept for V1 or add a mechanism (§5) | Render quality | — | — |
| 10 | ~~SQLite location; auto-clear~~ — **decided:** per-user app data dir; no auto-clear, with low-disk warning + storage view (§9) | Implementation | — | — |
| 11 | ~~Localhost hardening~~ — **decided:** OS-assigned port + per-launch secret, boot screen (§13) | Security | — | — |
| 12 | ~~Failure-mode behaviour~~ — **decided:** never dead-end (§13) | UX | — | — |
| 13 | Objective 2 accuracy contract — **parked**, see handoff | Post-V1 | — | — |
| 14 | **Run the floor-tier latency spike** — throwaway script, lowest-spec machine available: SAM 2 tiny encode + semantic pass + full-res render loop. Do this *before* app code | Validates the whole local-first architecture | — | — |
| 15 | Latency ceiling at which progress messaging is no longer enough, and what we do there (§13) | UX | — | — |
| 16 | ~~Packaging & signing~~ — **decided:** frozen PyInstaller sidecar, shipped **unsigned** (§3). Watch for antivirus quarantine reports from dealers | Shipping | — | — |
| 17 | ~~Store vs regenerate~~ — **decided:** store full-res lossless PNG (§9). Remaining: the **sharing mechanism**, which must emit JPEG and not hand out the archive | Trust, privacy | — | — |
| 18 | ~~Plane overlap~~ — **decided:** exclusive pixel assignment (§6). Remaining: the assignment rule for contested pixels | Render correctness | — | — |
| 19 | Saturation blend curve for the light map (§6) | Render quality | — | — |
| 20 | Noise estimate and smoothing curve for the light map (§6) | Render quality | — | — |
| 21 | ~~Switchplate/socket exclusion~~ — **decided:** accept in V1, add as classes to our own model (§5) | Render quality | — | — |
| 22 | ~~Sharing mechanism~~ — **decided:** plain JPEG, shade code in filename (§9) | Product | — | — |

---

## 13. Gaps flagged but not yet decided

**The real interactive bottleneck is not the encode.** SAM 2's encoder runs once per photo (1–4s on
a modest CPU). But the full-resolution divide/multiply/composite re-runs **every time the dealer taps
a new shade** — and that is the loop the customer actually watches. The structure above already fixes
most of it (`light_map` is computed once; a shade change is one multiply plus a composite) — but
**measurement showed that is not enough on its own.**

### Measured: render at ~1 MP while browsing, full resolution only on export

Results: [spikes/latency/RESULTS.md](../spikes/latency/RESULTS.md).

**Full-resolution rendering per tap is not viable.** Measured at **641 ms on a high-end i7**, and
**1–2.8 s on a realistic shop PC** — every single time the dealer taps a colour, inside a workflow
budgeted at three taps and thirty seconds. A **~1 MP preview (1280×720) stays between 43 ms and
195 ms** across the whole hardware range, which feels immediate. 2 MP is borderline: fine on decent
hardware, sluggish at the pessimistic end.

Full-resolution rendering happens **once, on save or export** — a 1–3 s cost the progress messaging
above covers comfortably.

**Lookup tables for gamma are mandatory, not an optimisation:**

| Operation | Naive `pow` | Lookup table |
|---|---|---|
| Encode to sRGB (**every tap**) | 507 ms | **241 ms** |
| Linearise from 8-bit (once per photo) | 457 ms | **139 ms** |

The gamma encode is the single most expensive stage of the per-tap path (~38% of it). Linearising
needs only a **256-entry table**, since real photos arrive as 8-bit — a per-pixel `pow` there is
pure waste.

**These stages are memory-bandwidth-bound, not CPU-bound.** A single E-core at 3.7 GHz was only
**1.4× slower** than unrestricted P-cores despite a large clock gap, because each 12 MP float32
array is 144 MB. Consequences: a shop PC's *slower RAM* matters more than its slower CPU, and **core
count is nearly irrelevant** — numpy's element-wise operations are single-threaded.

**Untested and worth taking:** crop to the wall's **bounding box** before the per-tap maths. Only
pixels inside the wall change, so this should cut cost in proportion to wall area — commonly 3× or
more, and likely the largest saving still on the table.

### Decided: if it's slow, explain it — don't degrade quality

**Decided:** we do **not** drop resolution or cut the pipeline to hit a time target. If processing
takes longer than hoped, the UI explains what is happening in language a non-technical person
understands.

Three things make this work rather than merely excuse the wait:

- **Start on photo load, not on shade selection.** Everything expensive — encode, semantic pass,
  plane split, light map — depends only on the *photo*, not on which shade is chosen. Starting the
  moment the photo is picked hides much of the cost inside human time, while the dealer is still
  talking to the customer or typing a code.
- **The honest framing is a good one.** The slow part happens **once per photo**; every subsequent
  shade change is a single multiply. So this is not a slow tool — it is *"setting up your room"*
  once, then colours switch as fast as the customer can point.
- **Messages must sound purposeful, never apologetic, and must not leak machinery.** The design goal
  is *the dealer never looks incompetent in front of a customer*. So: "Finding the walls in your
  photo…", "Working out how the light falls…", "Sharpening the edges…", "Mixing your shade…" —
  never a model name or the word "inference".

**Caveat, still open:** progress feedback changes the *perceived* wait, not the real one. 45 seconds
with clear feedback is fine; three minutes is not, however good the copy. The ceiling at which we
must do something else is undefined — see §12.

**Model load is a real local cold start.** There is no *server* cold start, but loading the encoder
and the semantic model into ORT sessions at launch takes real time. It must not come out of the
30-second per-photo budget — warm the models at app start.

### Decided: never dead-end

**Decided:** every failure lands somewhere the dealer can still work. No error is ever a full stop.

| Failure | Behaviour |
|---|---|
| No wall detected | Fall through to the **manual tap** path — the dealer taps the wall, SAM 2 refines |
| Photo unusable (dark, blurred, heavy HDR) | Proceed anyway with a quiet quality note; never refuse outright |
| Python service dies | Restart it quietly and resume |
| Model fails to load | Surface at boot, not mid-consultation (see boot screen, §3) |

**Why this is cheap:** the fallback already exists. The **correction path** — dealer taps, SAM 2
refines — is exactly what you want when auto-detection fails. Same screen, same code. "No wall
found" needs no special failure state; it quietly becomes the manual path the dealer already knows.

**Two things to watch:** the dealer may not realise anything went wrong, so failures still need a
subtle indication — and silent restarts can mask a fault that keeps recurring, so log them.

### Decided: local service hardening

**Decided:** bind to an **OS-assigned free port**, generate a **fresh secret each launch**, and have
Electron pass it to the UI so only our own app can call the service.

**The risk this closes:** "localhost" feels private but is not. Any program on the machine can reach
it — and so can **any website open in the dealer's browser**, since a web page may issue requests to
localhost. With customer room photographs now stored on that machine (§9), an unprotected service
would let another tab quietly read them. This is a well-worn attack on local services, not a
theoretical one. A random port also removes the port-collision failure, which otherwise appears as a
mysterious broken install on exactly one dealer's PC.

**Considered:** a Windows named pipe, which is unreachable from a browser at all and would remove the
attack surface rather than guard it, with the HTTP contract unchanged. Rejected as more
platform-specific plumbing with fewer worked examples to lean on.

### Decided: boot loading screen

**Decided:** the app shows a loading screen at launch until port selection and secret transfer
complete, with a **minimum of 2 seconds**.

This is also the right place to **warm the models**, which §3 already requires so that loading never
eats into the per-photo budget. So it is "at least 2 seconds, and however long the models need" —
and when it clears, the app is genuinely ready rather than merely looking ready. Model loading can
exceed 2s on a weak machine, so this screen gets the same plain-language progress treatment as the
per-photo one.

---

## Appendix: stack deltas vs. the one-page report

An examiner will notice these. Better to state them.

| Report says | Reality | Why |
|---|---|---|
| PyTorch | PyTorch for development and export; **ONNX Runtime** ships | Removes PyTorch from the installer (ADR-0001) |
| Node.js (Backend) | **No role.** Architecture is Python REST + Electron + React | Inference is Python; Electron already provides the desktop host |
| — | **ADE20K semantic model** added | SAM 2 is class-agnostic and cannot identify a wall (§5) |
| "Centralized platform" (Objective 1) | Local compute, **centralized catalogue data** | See ADR-0001 |
| "across desktop and web" | Desktop V1; web deferred but architecturally supported | §0 |
| CWCC (reference 2) | **Parked** with Objective 2 | Not used in V1 |
