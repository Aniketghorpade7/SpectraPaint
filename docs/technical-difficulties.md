# SpectraPaint — Technical Difficulties

**Status:** Living document · Append-only, newest entry last

The technical difficulties hit while implementing, whether or not they were solved.

**Why this file exists.** Every ticket is worked in a fresh isolated context, so a difficulty that
cost one contributor a day costs the next one a day again — the second person has no way to know it
was ever met. Recording the dead ends is worth as much as recording the fix: knowing that an
approach was tried and does not work is what stops it being tried a third time.

Write it down **while you are stuck**, not after. The details that make an entry useful — the exact
error, the platform, the version — are the first thing you forget once it works.

---

## When to write an entry

- Something took materially longer than it should have, for a reason worth naming
- A platform difference bit (the target is Windows; contributors develop on Linux or Windows)
- A library, model or tool behaved differently from its documentation
- You tried an approach, it did not work, and you abandoned it
- You are **still blocked** — record it open, and say what you need. An unrecorded blocker looks
  identical to work nobody started
- You worked around something rather than fixing it, and the workaround will outlive your ticket

A difficulty that ends in a deliberate choice usually also earns an entry in
[implementation-decisions.md](./implementation-decisions.md). Link the two rather than repeating.

## Entry format

```markdown
## <n>. <The difficulty, in one line>

**Ticket:** #<number> · **Contributor:** <name> · **Date:** YYYY-MM-DD ·
**Status:** open | worked around | resolved

**What happened:** the symptom, concretely — the actual error, the platform, the versions.

**Why it was hard:** what made it non-obvious. This is the part that saves the next person.

**Where it stands:** the fix, the workaround and what it costs, or — if still open — what is needed
to move it.
```

Number entries sequentially and never renumber. Update an entry's **Status** when it changes, and
say what changed; do not delete a resolved difficulty, because the reason it happened is still true.

---

## 1. SQLite will not use an index for `LIKE`, so the name index looked useless

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (found by an agent) · **Date:** 2026-08-19 ·
**Status:** resolved

**What happened:** an index on the folded name column was added to make prefix search
(`name_folded LIKE 'lin%'`) a seek instead of a scan. `EXPLAIN QUERY PLAN` still said `SCAN`. The
index was doing nothing for the query it was created for.

**Why it was hard:** the query looks exactly like the textbook case an index serves, and the index
*is* used — for `ORDER BY` and as a covering index — so the plan output was not obviously wrong at a
glance. The cause is a documented SQLite rule that is easy to have never met: `LIKE` is
case-insensitive by default, so the optimiser cannot use an ordinary
(case-sensitive, `BINARY`-collated) index for it unless `PRAGMA case_sensitive_like` is on. Turning
that pragma on would have been the wrong fix — it changes the meaning of every `LIKE` in the process.

**Where it stands:** the folded column is already lowercase, so the prefix query is expressed as an
ordinary range comparison instead — `name_folded >= 'lin' AND name_folded < 'lin' || char(0x10ffff)`
— which seeks the index and measures 0.005 ms against 0.071 ms for the `LIKE` scan. `GLOB` also
seeks, and was rejected: its pattern syntax has no escape for `*`, `?` and `[`, all of which a Dealer
can type into a search box. Recorded as decision entry 4 in
[implementation-decisions.md](./implementation-decisions.md).

---

## 2. The renderer could not call the Catalogue endpoints at all

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (found by an agent) · **Date:** 2026-08-19 ·
**Status:** resolved

**What happened:** `apps/desktop/src/contract-path.ts` whitelists what the renderer may ask the main
process to fetch, and its pattern allows no `?`. Every Catalogue request carrying parameters —
search, family filter, paging — would have come back as `malformed_request` from the bridge, never
reaching the service. Caught by reading the check before writing the UI, not by a failing request,
which is the only reason it did not present as a mystery.

**Why it was hard:** it would not have looked like a whitelist problem from the UI. The bridge
returns the same shape the service does, so the panel would have shown a plain-language failure with
a `malformed_request` code and nothing pointing at the main process. The service would have logged
nothing, because nothing arrived.

**Where it stands:** widened to accept one query string, restricted to the characters
`URLSearchParams` emits, with `#` and a second `?` still refused and `..` still refused in the path.
Recorded as decision entry 10, and covered by vitest cases including every character a Dealer might
type. Worth knowing for any future ticket adding an endpoint with parameters: **this check has to be
widened deliberately, and it is silent when it is not.**

---

## 3. `react-hooks/set-state-in-effect` rejected the first shape of `useCatalogue`

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (hit by an agent) · **Date:** 2026-08-19 ·
**Status:** resolved

**What happened:** the hook was first written the conventional way — effects that watch `query` and
`shadeFamily` and set state in response. `eslint-plugin-react-hooks` 7 fails the build on five counts
of `set-state-in-effect`, which is an error, not a warning, in this repository's config.

**Why it was hard:** the rejected shape is the one most React material still teaches, so the error
reads as the linter being fussy rather than as a design note. It is not: each of those effects was a
cascading render, and two of them were storing state the props already answered.

**Where it stands:** restructured, and the result is smaller. The family counts are derived with
`useMemo` instead of mirrored into state. Search is driven from the change handler with a debounce
timer and a token that makes a slow reply from an earlier keystroke unable to overwrite a later one —
which the effect version did not handle at all. Page resets happen in the handler that causes them.
The one remaining effect loads the Catalogue and starts with an `await`, so nothing sets state
synchronously during a render.

**Worth knowing:** if an effect in this codebase needs to set state, that is a signal to look for the
event that caused it. The linter is not going to be argued out of it.

---

## 4. Prettier and the Catalogue generator both wanted to format the same file

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (hit by an agent) · **Date:** 2026-08-19 ·
**Status:** worked around

**What happened:** `npm run format` reformats `data/catalogue/*.json`, collapsing each Lab object
onto one line. `tools/generate_stand_in_catalogue.py --check` then fails, because the file no longer
matches what the generator produces. Running the generator again makes prettier fail instead. Both
are CI checks, so the two of them could not both be green.

**Why it was hard:** each tool is right on its own terms, and the failure only appears when both run
— which is CI, not the command a contributor reaches for while working.

**Where it stands:** `data/catalogue/*.json` is in `.prettierignore`, with a comment saying why. The
generator owns the file's formatting because the generator owns the file. The cost is that a
hand-written Catalogue file dropped into that directory is not formatted by anything, which is
acceptable — hand-writing one is not a workflow we support, and the loader validates content rather
than layout.

---

## 5. FastAPI's TestClient never runs background asyncio tasks started during a request

**Ticket:** #4 · **Contributor:** Prasad Kathe (hit by an agent) · **Date:** 2026-08-19 ·
**Status:** worked around

**What happened:** the first design ran photo preparation as an `asyncio.create_task` inside
`POST /sessions`. Service tests that then opened `GET /sessions/{id}/events` hung forever: the job
never produced events because the task never ran. A minimal reproduction — `create_task` in a POST,
sleep, then read shared state — showed the state untouched 0.3 s after the POST returned.

**Why it was hard:** nothing fails loudly. The POST returns 201, the stream endpoint connects, and
the reader waits on an event that can never arrive, because TestClient's event loop only drives the
app coroutine for the duration of each request. The failure looks like an infinite wait in the app,
not a test-harness quirk, so the diagnosis lands on the wrong layer.

**Where it stands:** worked around by running preparation on a daemon worker thread instead — see
implementation-decisions.md #11. The thread is independent of any request's event loop, so it
progresses under both TestClient and the real uvicorn server (verified end-to-end). A future ticket
that adds background work must either use a thread, or solve this TestClient gap first.


---

## 6. `verify()` accepts a JPEG that cannot be decoded, so the failure surfaced two layers away

**Ticket:** #3 · **Contributor:** Chauhan Anamika Abhimanu (hit by an agent) · **Date:** 2026-08-19 ·
**Status:** solved

**What happened:** the upload gate calls Pillow's `Image.verify()`, which checks structure without
decoding pixels. A JPEG with its end-of-image marker stripped passes it. Preparation then decodes for
real, raises `OSError`, and — before this was fixed — nothing caught it: the render request that
later asked for that session's photo returned a bare `500` with no error code and no message the
Dealer could act on. The docstring on the gate had been edited to *claim* the decode was caught,
which made the gap harder to see than if it had said nothing.

**Why it was hard:** the upload succeeds and hands back a session id, so the photo looks accepted.
The error appears at a different endpoint, in a different module, on a request that did nothing
wrong. Nothing in the upload response or the session state marks the photo as suspect, so the natural
reading is that the render endpoint is broken.

**Where it stands:** solved. Preparation's failure is already a terminal `failed` event
(implementation-decisions.md #11), and `sessions.require_photo` now turns "preparation produced no
photo" into `422 unsupported_image` with the plain-language message, so the render answers in the
contract's error shape. A seam-1 test uploads a stripped-EOI JPEG and asserts that render response,
which is what stops the 500 coming back. The general lesson is the one the gate's docstring now
states honestly: `verify()` is a gate, not a guarantee, and whichever stage first decodes must own
its own errors.

---

## 7. The generic request bridge cannot carry a PNG, so a repaint returned with no image

**Ticket:** #3 · **Contributor:** Chauhan Anamika Abhimanu (hit by an agent) · **Date:** 2026-08-20 ·
**Status:** resolved

**What happened:** the first design for the UI wiring sent the render request through the generic
request bridge (`service-bridge.ts`). That bridge ends in `body: await response.json().catch(() =>
null)`, and the render contract returns `image/png` — so a successful repaint arrived in the
renderer as `ok: true, body: null`. The request succeeded (201), nothing logged and nothing threw,
and the photo on screen simply never changed.

**Why it was hard:** the failure is silent in the worst way. There is no error to catch, no red test
— every seam 1 test sees the endpoint working, because the endpoint does work. It only surfaces by
running the app and watching a tap do nothing, which is precisely the path that is not automated.
The bridge's docstring even documents the JSON body it reads, but a reader has to go looking for the
image response on the other side to notice the mismatch.

**Where it stands:** resolved by a dedicated render bridge (`registerRenderBridge`) that reads
`response.arrayBuffer()` and converts the bytes to a data URL via `photoDataUrl` — the same
second-bridge pattern decision #13 already established for the progress stream, and recorded as
implementation-decisions.md #20. Worth knowing for any future endpoint returning bytes: the export
ticket (#12) will meet the same wall, and the answer is another dedicated bridge, not widening the
generic one.

---

## 8. The pinned SAM 2 checkpoint declares a video model, and transformers warns when loading it

**Ticket:** #6 · **Contributor:** Aniket Ghorpade · **Date:** 2026-08-20 · **Status:** resolved

**What happened:** `facebook/sam2-hiera-tiny` at the pinned revision has a `config.json` declaring
`model_type: sam2_video` and `architectures: [Sam2VideoModel]`. Loading it as the image model —
which is what a room photo needs — makes transformers 5.15.1 print: *"You are using a model of type
`sam2_video` to instantiate a model of type `sam2`… is otherwise not supported and can yield
errors."*

**Why it was hard:** the warning names the exact failure that would matter (silently
randomly-initialised weights produce a model that runs and returns nonsense) without saying whether
it is happening. Taking the warning at face value and reaching for the `sam2` package instead would
have added hydra, a git-sourced dependency and a second copy of the model definitions; ignoring it
would have risked shipping a refiner with uninitialised weights.

**Where it stands:** resolved by measuring instead of guessing — loading with
`output_loading_info=True` reports **0 missing keys and 0 unexpected keys**, so the image model is
fully populated from the video checkpoint, and the warning is the documented "loading a subset"
case. The export then verifies every graph numerically against that PyTorch model, which would catch
the failure the warning describes even if a future revision changed the layout. Nothing needs the
`sam2` package.

---

## 9. A synthetic room cannot tell you whether wall detection works

**Ticket:** #6 · **Contributor:** Aniket Ghorpade · **Date:** 2026-08-20 · **Status:** open

**What happened:** with no room photographs in the repository, the pipeline was first exercised on a
generated image — flat wall gradient, a floor band, a bright rectangle for a window, a dark strip
for a shadow. SegFormer labelled 70.7% of it wall and only 0.4% as any exclusion class: it did not
read the painted-on rectangle as a window or the flat band as a floor. The refiner's raw mask came
back mushy on that input, with a maximum of 0.848 and a mean of 0.512, and the boundary band
consequently covered 59% of the frame instead of a thin ring.

**Why it was hard:** the numbers look like pipeline faults and are mostly the input's fault. A
network trained on photographs has no reason to recognise a rectangle of constant pixels as glass,
and SAM 2 has nothing to latch onto where there is no texture. The trap is that a synthetic scene is
*good enough* to make the plumbing look tested — every shape, dtype and status code is right — while
saying nothing about the two acceptance criteria that are about accuracy. It did find two real bugs
(decision 26), so it was not wasted; it simply cannot answer the question it appears to answer.

**Where it stands:** open, and blocked on real photographs. `data/fixtures/rooms/README.md` says
what is needed — three rooms, hand-labelled, one strongly shadowed, one occluded, one with a window
— and `tests/api/test_walls.py` will assert against them the moment they land, skipping with a
reason until then. Until that happens, the accuracy of this pipeline on real rooms is **unverified**,
and the thresholds in that file are guesses chosen to catch regressions rather than measurements.
The `MergeShapeInfo` warning ONNX Runtime prints when loading the encoder is benign and unrelated —
parity against PyTorch passes — but it is worth knowing it is not a symptom of this.

---

## 10. PyTorch ships JavaScript, and eslint found it

**Ticket:** #6 · **Contributor:** Aniket Ghorpade · **Date:** 2026-08-20 · **Status:** resolved

**What happened:** after `uv sync --group export` installed torch, `npm run check` failed with 84
errors — `'document' is not defined`, `no-cond-assign`, unused variables — all inside
`services/inference/.venv/lib/python3.12/site-packages/torch/utils/model_dump/code.js`. PyTorch
bundles a JavaScript viewer for model dumps, and eslint's ignore list covered `dist`, `out` and
`node_modules` but not a Python virtualenv.

**Why it was hard:** the failure is silent in CI and loud locally, which is the wrong way round. The
fast lane runs `npm run check` *before* `uv sync`, so the virtualenv does not exist yet and the lane
stays green; a contributor who has run the export sees a wall of errors in somebody else's minified
code, none of it theirs, none of it explained by their own diff.

**Where it stands:** resolved — `**/.venv/**` is on eslint's ignore list, with a comment saying why,
because the next person to add a Python dependency that ships web assets should not have to work it
out again. `.prettierignore` already excluded `services`, which is why formatting never complained.

---

## 11. A CSS mask on a greyscale PNG fails open, and brightened the whole room photo

**Ticket:** #6 · **Contributor:** Aniket Ghorpade · **Date:** 2026-08-20 · **Status:** resolved

**What happened:** with the wall overlay shown, the *entire* Room Photo brightened — sofa, floor and
furniture along with the wall — rather than only the detected wall. Reported from a screenshot of
the running app, not caught by any test.

**Why it was hard:** the overlay is a white wash masked by the Alpha Matte, and the matte is served
as an 8-bit greyscale PNG — coverage in the grey level, and **no alpha channel at all**. CSS
`mask-mode` defaults to `match-source`, which for an image means *alpha*. The alpha of a
channel-less PNG is opaque everywhere, so the mask was a no-op and the wash covered its whole
rectangle.

The direction of the failure is what made it slip through: the mask **fails open**. Nothing errors,
no image fails to load, the console is clean, and the overlay simply stops meaning anything while
still looking deliberate. On a photo whose wall is most of the frame it reads as "the overlay is a
bit strong" rather than "the mask is not applied".

Two further wrong turns worth recording, because both cost time. A first attempt to verify it inside
Electron's own offscreen renderer returned a 1×1 screenshot. And in a headless harness the mask was
loaded from a `file://` URL, which does not load — the element then vanished entirely, making the
broken and fixed cases look identical and briefly suggesting the fix did nothing. Production hands
the matte over as a `data:` URL, and reproducing that form is what made the comparison meaningful.

**Where it stands:** resolved with `mask-mode: luminance`, measured rather than assumed — in
headless Chromium at Electron 43's engine version, a half-covered test image brightened on both
halves without the line and on only the covered half with it. `-webkit-mask-source-type: luminance`
was measured in the same harness and had **no effect at all**, so it was removed along with
`-webkit-mask-image`: a fallback that does not fall back is worse than none, because the comment
beside it lies.

Serving the matte as an `LA` PNG, with coverage duplicated into a real alpha channel, would make the
CSS default correct and remove the dependence on one property. It was not done — one channel is the
honest representation of a matte, and this application ships on one known engine — but it is the
change to reach for if the overlay ever moves to a browser target.

---

## 12. The photographs arrived, and the pipeline is less accurate than the thresholds it was given

**Ticket:** #30 · **Contributor:** Aniket Ghorpade · **Date:** 2026-08-21 ·
**Status:** open — narrowed by #31 (implementation decision 49), not closed

Follow-up to [difficulty 9](#9-a-synthetic-room-cannot-tell-you-whether-wall-detection-works), which
is now **resolved** in its own terms: three hand-labelled rooms are in `data/fixtures/rooms/`, and
the slow lane runs twelve tests where it ran four skips. What it found is a new difficulty, which is
why this is a new entry rather than an edit of that one.

**What happened:** nine of the twelve pass. Wall *recall* is excellent — 0.97 to 0.99 across all
three photographs, so the pipeline finds the wall it is looking for. Every failure is precision:

| Photograph | Wall IoU (floor 0.60) | Non-wall leakage (ceiling 0.20) |
|---|---|---|
| `empty-corner` | 0.95 | **0.21** |
| `corner-with-clothesline` | 0.77 | **0.35** |
| `windows-with-curtains` | **0.37** | 0.24 |

The matte paints the door in the first, the hanging clothes in the second, and the curtains and
window glass in the third.

**Why it was hard:** the obvious cause — a missing entry in `EXCLUDED_CLASSES` — is not the cause.
Measured against the semantic map, the over-claimed pixels are labelled **`wall` by SegFormer
itself**: 100% of them in `empty-corner` (median wall confidence 0.97 on a white-painted door), 99%
in `corner-with-clothesline`, 87% in `windows-with-curtains`. The classes the model gets right —
`apparel` and `towel` on the hanging clothes — are already outside the matte. Adding `mirror`, the
only excludable class with any share of an over-claim, would remove 11% of one photograph's and move
no threshold. Exclusion is semantic by design (`design-decisions.md` §5), and a model that calls a
door "wall" with 0.97 confidence cannot be argued out of it semantically.

The one lever that exists is the model's own wall confidence, and it is inconsistent. A 0.9 floor
drops 58% of the clothesline over-claim while keeping 98% of true wall, which would clear that
photograph; on the door it keeps 81% of true wall and 79% of the over-claim, because the model is
confidently wrong rather than unsure. `windows-with-curtains` cannot reach IoU 0.60 by any of these
routes: its certain wall is 10% of the frame while the matte claims 40%.

**What #31 changed (2026-09-15):** that 0.9 confidence floor now ships, and measuring it settled
more than it fixed. It must exempt anything SegFormer argmaxed as `wall` however unsure, or it
deletes shadowed wall (0.765 recall against a 0.80 floor); with the exemption,
`windows-with-curtains` leakage clears its target at 0.185 and the clothesline moves 0.348 to 0.338.
The door does not move at all, as predicted. Three further routes were measured and closed — see
difficulty 26 for the negative-prompt dead end, and implementation decision 49 for the rest. The
difficulty stays **open** because the two defects it names are still there: this checkpoint paints a
door and paints half a curtained wall, and no arrangement of the code downstream of it changes
that.

**Where it stands:** open, and the lane is green rather than red — each fixture is now held to what
it measured (`data/fixtures/rooms/measured.toml`, decision 32) instead of to a target the pipeline
cannot reach, so a regression still fails while the shortfall stays on the record rather than reading
as a pass. This is the domain gap
[`docs/handoff/custom-wall-segmentation-model.md`](./handoff/custom-wall-segmentation-model.md)
predicted, arriving exactly where it said it would — a dev-only ADE20K checkpoint on real Indian
rooms — and it is not fixable in a ticket about test data. Reported as its own defect; #30 is blocked
on it, and the slow lane is red until it lands. The red *is* the finding: the thresholds in
`tests/api/test_walls.py` were described as regression floors chosen without measurements, and the
first measurements say the pipeline does not clear them.

---

## 13. Smoothing a narrow corner dilutes it below any usable floor

**Ticket:** #7 · **Contributor:** Aniket Ghorpade (found by an agent) · **Date:** 2026-08-21 · **Status:** resolved

**What happened:** the first splitter measured `energy[x] = mean |dL/dx|` per column, then box-smoothed with
radius `2%` of width before comparing to `_ENERGY_FLOOR 0.015`. On Room 2 (1280 px, corner at x≈80) the raw
peak is `0.0238` at the true corner — correctly top-ranked — but the smoothed peak is `0.0070`, well below
the floor, so the corner is discarded. Room 1 shows the same: raw `0.0257` → smoothed `0.0043`.

**Why it was hard:** the smoothing is there to quieten texture noise, and it does — but a 1-2 px corner line
spread over a 51 px box (2% of 1280) is diluted `25×`. Lowering the floor to `0.003` does make the corner
pass, but then wardrobe (138) and curtain (218, 701) verticals pass too, because `|dL/dx|` alone cannot tell a
corner from a curtain edge — the smoothed and unsmoothed rankings are the same, only the absolute is wrong.
The side-fraction margin (`15%` of wall width) then excludes the real corners anyway: return walls are `≈30 px`
in a `678 px` frame (`4.4%`), so a `102 px` margin rules out exactly the geometry the feature is for. Both
failures look like tuning, but no tuning of one reaches past the other.

**Where it stands:** resolved by making the **valley primary and thresholding on unsmoothed prominence**.
The shading-gradient reversal (`median luminance` valley, depth `max - valley` over a `15%` neighbourhood) is
now the detector; `|dL/dx|` is supporting evidence and is thresholded on its **raw** value (`0.004` permissive
floor, `0.010` strong). A column with a deep valley is kept even when its edge is modest (the same-colour
shading-only archetype at `0.0029` smoothed), while a column with a strong edge but no valley (curtain) is
rejected. The side-fraction was replaced by a minimum plane **area** (`0.04`) and **width** (`0.03`) — a
texture line near the edge leaves no material wall on one side, a real corner does. Recorded as decision 33.

---

## 14. Striped wallpaper looks like many corners to a column energy

**Ticket:** #7 · **Contributor:** Aniket Ghorpade (found by an agent) · **Date:** 2026-08-21 · **Status:** resolved

**What happened:** a synthetic striped wallpaper (12 px stripes, `188` vs `180` — `8/255` contrast) has a
`mean |dL/dx|` of `≈0.03` at every stripe edge and a median step of `≈0.03` at every edge, so the first
splitter's `energy > 0.015` and `depth > 0.012` tests mark every stripe as a corner. With `12 px` stripes it
produces `5` valleys and `10` energy peaks, the top two are kept (`min_gap 0.18·width`), and the wall is split
into three planes that are wallpaper, not walls.

**Why it was hard:** the per-column cues are correct locally — a stripe edge *is* a strong vertical edge and
*does* have a step — but the pattern repeats. A single threshold cannot tell one corner from ten stripes, and
the valley at a dark stripe centre (`depth 0.03`) is indistinguishable from a corner valley (`0.012-0.09`) in
isolation.

**Where it stands:** resolved by counting. A true corner has one (or two for three planes) deep valleys;
wallpaper has many. When `len(valley_candidates) > 4` the photo is treated as wallpaper and not split — the
same early-return that already existed for `flat wall`. The synthetic wallpaper's contrast was also lowered to
`2/255` (`182` vs `180`) so its valley depth (`0.007`) sits below the `0.030` valley floor and its step
(`0.007`) below the `0.090` step floor, matching a real low-contrast paper. The archetypal same-colour corner
was made steeper (`0.55→0.92` quadratic valley, depth `0.09`) so the true valley stays above the raised floors.
Both are now covered by `tests/render/test_split.py` (flat, corner, shading-only, striped, seam position, sum,
crisp/soft).

---

## 15. The guard against striped wallpaper threw away every real photograph

**Ticket:** #7 · **Contributor:** Aniket Ghorpade · **Date:** 2026-08-21 · **Status:** resolved

Follows [difficulty 14](#14-striped-wallpaper-looks-like-many-corners-to-a-column-energy), whose fix
caused this.

**What happened:** the wallpaper guard rejects a photograph when more than four valley candidates
are found, on the reasoning that a corner produces one valley and wallpaper produces many. It does,
on a drawn image. On the three photographs in `data/fixtures/rooms/` it produced **10, 7 and 19**
candidates, so every photograph was discarded before any seam was ranked — including a wholly
unoccluded corner, where the correct seam was sitting in the candidate list.

**Why it was hard:** the guard was tested and correct. A synthetic striped wall really does produce
many valleys and a synthetic corner really does produce one, so both tests passed and kept passing
through two rounds of review. A real median-luminance profile has ten or twenty shallow local minima
from stains, scuffs and camera noise, and the guard counted every one of them — nothing suppressed
non-maximal dips before the count. The failure is invisible from synthetic inputs by construction: a
step edge drawn into an array has exactly one minimum, so no test built that way can produce the
condition that trips it.

The second trap sat behind the first. With suppression added, the guard passed and the seam went to
the wrong column, because the deepest valley in `empty-corner` is the door frame at the far right —
a region the matte should not have claimed at all (#31). One defect was hiding another.

**Where it stands:** resolved by requiring two of three cues to agree rather than trusting any one
of them, and by suppressing non-maximal peaks per cue before counting anything (decision 34). The
lesson worth keeping is about where each test belongs: `tests/render/test_split.py` is the right
place for the partition algebra, and it cannot answer "does this find a corner in a room" — only
`data/fixtures/rooms/` can.

---

## 16. Every Shade rendered as the wrong colour, and every test agreed it was fine

**Ticket:** #7 · **Contributor:** Aniket Ghorpade · **Date:** 2026-08-22 · **Status:** resolved

**What happened:** writing the Accent Wall test for #7's last criterion — two planes, two Shades,
one request — the assertion "the wall assigned the bluest Shade is blue" failed. The wall was
magenta. So was the other one, and the cause was not the Accent Wall: `lab_to_linear_rgb` computed
`xyz @ MATRIX` where the sRGB primary matrix is written one row per output channel, which applies
its **transpose**. Every Shade in the Catalogue had been decoding to the wrong colour since issue #3.

How wrong: `PS-1001 "Morning Linen"`, Lab(97, 0.49, 0.85), a near-white, rendered as sRGB
(255, 117, 211) — hot pink. Lab white decoded to (1.0, 0.193, 0.719) instead of (1, 1, 1).

**Why it was hard:** nothing was subtly off, and everything passed. `tests/render/test_colour.py`
covered the piecewise transfer function thoroughly and the D65 white-point constant, and never
called `lab_to_linear_rgb` at all. The render tests asserted that a repainted wall is no longer the
room's grey, and that Realistic and True Colour differ from each other — both of which are true of
the wrong colour. So the one thing a paint visualiser exists to get right, "the wall is the colour of
the chip", was the one thing no test asked.

Two things made it invisible for four tickets. The photographs it was tested against are near-neutral
walls, and the wrongness is a channel mix rather than a brightness error, so a render still looked
like a plausible repaint of a room. And the wrong direction is the *easy* orientation to write: for a
row-vector stack, `xyz @ M` reads naturally and is wrong, while `xyz @ M.T` reads awkwardly and is
right.

**Where it stands:** resolved — the matrix is transposed at use, with the trap named in a comment.
The tests that now guard it are a reference table computed from the CIE formulae by hand rather than
from this module, and a property test: a* = b* = 0 is grey by definition, so the three channels must
come out equal. The property test is the one that matters, because a table of expected values can
always be regenerated from a broken implementation by somebody who assumes it is right.


## 18. The contract-pinning test counts routes, and FastAPI keeps PATCH and DELETE apart

**Ticket:** #11 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-22

**Hit:** `test_the_contract_is_exactly_the_documented_surface` collects `(path, methods)` pairs from
the live route table, and the first version of the new expected set wrote
`("/bundles/{bundle_id}", {"PATCH", "DELETE"})` as one entry. It failed: FastAPI registers one route
per method, so the collector emits two pairs for that path. The same trap was waiting on `/bundles`
(GET+POST) and `/bundles/{bundle_id}/consultations` (GET+POST).

**Resolution:** the expected set lists one pair per method, exactly as the collector sees them —
which is also more honest about what the contract is. No production code changed.

**Still open:** nothing.
---

## 18. Local noise estimation mistook wall texture for sensor grain

**Ticket:** #9 · **Contributor:** Prasad Kathe (hit by an agent) · **Date:** 2026-09-05 · **Status:** resolved

**What happened:** the first implementation of local per-region noise estimation (`_local_noise_sigma`) computed a local MAD over a 5% window of the high-pass residual. On the `empty-corner.jpg` daylight fixture (the control that must stay below the noise floor), this produced a mean wall sigma of ~0.0097 — above the `_NOISE_FLOOR 0.008` — causing spurious smoothing of a clean wall. The global MAD correctly measured 0.0047 (well below floor). The local MAD was picking up wall texture (stains, scuffs, paint grain) as noise because the window was not wide enough to average out texture variations.

**Why it was hard:** the symptom looked like a tuning problem (floor too low, window too small), but the root cause was conceptual: MAD over a local window cannot distinguish sensor grain from wall texture — both appear as high-frequency variation. The global MAD works because texture averages out over the whole wall. The phone's night mode on `windows-with-curtains.jpg` also denoised the image, making its global sigma *lower* than the daylight fixture (0.0040 vs 0.0047), so no global floor could make the night fixture smooth while leaving the day fixture sharp — the ordering is backwards.

**Where it stands:** resolved by changing the local estimate to a variance-ratio modulation of the global sigma. The global MAD (`_measured_noise_sigma`) gates whether smoothing runs at all. If it exceeds the floor, a local variance map (`_local_noise_sigma`) scales the global sigma by `sqrt(local_var / global_var)`, clipped to [0.25, 4.0]. This preserves the robust global decision while allowing spatial variation where grain genuinely differs (e.g., underexposed corners). The fixture corpus may not exercise the dark-wall criterion at all (night mode denoises dark regions); this is recorded in implementation-decisions.md #37.

---

## 19. Alpha matte selector indexed rows, not pixels

**Ticket:** #9 · **Contributor:** Prasad Kathe (hit by an agent) · **Date:** 2026-09-05 · **Status:** resolved

**What happened:** `_measured_noise_sigma` and `_smooth_where_dark` used `alpha.reshape(H, -1)[..., 0] > 0.5` to select wall pixels. For an `(H, W, 1)` matte, `reshape(H, -1)` gives `(H, W)`, and `[..., 0]` then takes **column 0 only** — a length-H vector. `residual[on_wall]` therefore kept whole *rows* whose leftmost pixel happened to be wall. At 720 px height, `_NOISE_MINIMUM_PIXELS=1000` could never be met, so the alpha was ignored entirely on all preview resolutions. The frame-wide estimate the review objected to was still what ran.

**Why it was hard:** the bug was a classic NumPy reshaping mistake that looked correct at a glance — `reshape(H, -1)` flattens the spatial dimensions, and `[..., 0]` looks like "channel 0". But it actually selects the first column. The fix is simply `alpha[..., 0] > threshold` to index the channel axis directly, giving an `(H, W)` boolean mask.

**Where it stands:** fixed in both `_measured_noise_sigma` and `_smooth_where_dark`. The threshold `0.5` was also promoted to a named constant `_NOISE_MATTE_THRESHOLD` per conventions §4.

---

## 20. Performance gate silently fell back to plain division

**Ticket:** #9 · **Contributor:** Prasad Kathe (hit by an agent) · **Date:** 2026-09-05 · **Status:** resolved

**What happened:** `spikes/latency/bench_render_loop.py` had a `try/except ImportError` that set `_light_map_of = None` when the `spectrapaint` package wasn't installed. CI ran the gate as `uv run --python 3.12 --with "numpy>=2,<3" python spikes/latency/bench_render_loop.py --check` — **without `spectrapaint` installed**. The import failed, the fallback activated, the bench measured the old cheap `linear / base_colour` path, and the gate reported PASS. The PR description claimed "the gate now fails honestly" — false.

**Why it was hard:** the failure was silent by design. The fallback was added for standalone benchmark runs, but in CI it masked the fact that the gate couldn't see the code it was supposed to guard. Conventions §5 forbids silent recovery without a log, and §7b makes the gate required. The gate passing on the wrong code path is exactly the "silent-recovery-without-a-log" the conventions forbid.

**Where it stands:** fixed by making the import authoritative (dropping the `try/except`), installing `spectrapaint-inference` in the CI environment via `--with-editable services/inference` in `.github/workflows/fast-lane.yml`, and hoisting the Light Map computation out of the per-tap path in `render_many` so the gate measures the actual per-tap cost (multiply–composite–encode, ~36 ms at 1280×720).

---

## 17. Grouping by raw Base Colour splits the same paint at different brightness

**Ticket:** #8 · **Contributor:** Prasad Kathe (hit by an agent) · **Date:** 2026-08-22 · **Status:** resolved

**What happened:** the first grouping implementation compared raw `estimate_base_colour` triples with Euclidean distance `< 0.08`. Two planes of the same white at `0.8` vs `0.5` shading yield bases `0.44` vs `0.27` (distance `0.22`) and were placed in different groups, so the room still flattened — the exact bug grouping exists to fix. `empty-corner.jpg` (two whites, one paint) split; `corner-with-clothesline.jpg` (off-white vs pink) correctly split, so the threshold looked right on one fixture and wrong on the other.

**Why it was hard:** the base estimate deliberately picks the brightest genuinely-wall pixels (`90th` percentile), so a darker wall's base *is* darker — that is correct for the light map, but it means raw distance confounds paint colour with shading. The fix is not a looser threshold (that would merge the accent wall at `0.324` tint distance) but a different space: tint `base / luma` removes shading scale, so same paint yields same tint (`0.015` on empty-corner) while different paint stays apart (`0.324` on clothesline). The mistake is easy to repeat because the spec says "compare each plane's colour" without naming the space.

**Where it stands:** resolved — grouping uses tint distance `< 0.08` (`_tint_of`), and a group re-estimates from the union matte so the seam stays interior. Recorded as implementation-decisions.md #36. The threshold is still tuned against two labelled corners; more fixtures are the only honest way to tighten it.


---

## 21. Making `NoWallFound` non-fatal crashed the whole test process, not just one test

**Ticket:** #10 · **Contributor:** Aniket Ghorpade (hit by an agent) · **Date:** 2026-09-04 · **Status:** resolved

**What happened:** the first version of the "no wall found is not a preparation failure" change (implementation-decisions.md #39/#40's backend half) made `find_the_edges` call `encode_photo` — SAM 2's encoder — unconditionally, on every photo, including one the semantic pass had just found nothing wall-like in at all. The full fast-lane suite (`pytest -m "not models"`, no real models involved by design) started reporting `188 passed` and then the whole process aborted: `terminate called without an active exception`, preceded by ONNX Runtime errors inside `/vision_encoder/backbone/...` — `Status Message: GetElementType is not implemented`. Deterministic across repeated runs, and isolated by bisection to `tests/api/test_sessions.py` alone.

**Why it was hard:** the crash looked like an ONNX Runtime bug unrelated to anything in the diff, and it happened *after* pytest had already printed a full passing summary, which reads as "the tests are fine, something else is wrong." The actual cause was two facts compounding, neither obvious alone: `tests/api/test_sessions.py` uploads a 1×1 PNG through the *real*, unstubbed `create_app(SECRET)` — real preparation, real `load_graphs()`, running in a background daemon thread the moment `POST /sessions` returns, entirely invisible to a test that never awaits it — because this repository checkout happens to have real model weights under `models/`. Before this change, `wall_regions` raising `NoWallFound` on that degenerate input stopped the stage list immediately, so the encoder was never reached; nothing in the existing suite had ever exercised SAM 2 in-process on a genuinely pathological photo. Catching `NoWallFound` and continuing to `find_the_edges` removed that accidental guard, and SAM 2's exported graph — built and traced against real photographs — simply was not built to survive a 1×1 input, which is a fair thing for it not to survive.

**Where it stands:** resolved — `find_the_edges` now only encodes when `wall_regions` succeeded (`workspace.regions is not None`); a photo where the semantic pass found nothing plausible at all leaves `PreparedPhoto.features` as `None`, and the encode that would have cached it is deferred to whichever correction endpoint eventually needs it. This is a narrower claim than "cache the features unconditionally," and it is recorded as its own reasoning in implementation-decisions.md #41 rather than folded into #40, because it was forced by this crash, not decided ahead of it. Worth naming for whoever writes the correction endpoints: `RefinerFeatures` can legitimately be absent, and an endpoint that assumes it is always there will crash the same way this did.

---

## 22. The Add tool's exclusivity rule silently degraded an already-correct wall, twice, before it was right

**Ticket:** #10 · **Contributor:** Aniket Ghorpade (hit by an agent) · **Date:** 2026-09-04 · **Status:** resolved

**What happened:** the first version of `segmentation.corrections.add_plane` enforced "every pixel belongs to exactly one plane" by subtracting every existing plane's raw alpha from the newly-decoded one: `new = clip(new - existing, 0, 1)`. Against real fixtures (a new slow-lane test, `test_the_add_tool_grows_a_plane_from_a_missed_wall` in `tests/api/test_walls.py`), this produced a plane whose alpha at the *exact tapped pixel* was materially lower than SAM 2 had actually decoded there — on `windows-with-curtains.jpg` a genuine 0.9-ish decode came out as 0.36, because an adjacent plane's own soft boundary already held a partial, uncertain claim (0.36-ish) on that same pixel and the subtraction ate it regardless. The second version flipped the direction — reduce the *existing* planes wherever the new one claims a pixel — on the reasoning that a deliberate correction should outrank an old automatic guess. Run again against all three fixtures, it failed a *stronger* test (`(after >= before)[wall_label].all()`, i.e. a correction must never make an already-correct labelled pixel worse) on every single fixture: wherever SAM 2's newly-decoded matte brushed against an existing plane's *confident interior* — not just its uncertain edge — that interior lost coverage it had genuinely earned, degrading a wall the automatic pass had already got right.

**Why it was hard:** both versions look locally reasonable and both are wrong for the same structural reason — neither one asks *which claim is actually stronger at this pixel* before resolving it. Version 1 always favours the old plane; version 2 always favours the new one; the correct rule depends on the two alpha values being compared, pixel by pixel, and there is no way to discover that from reading the code — only from measuring what it does to a real photograph, which is exactly why conventions.md §6 keeps this class of behaviour out of unit tests and in the slow lane. The failure mode is also quiet in a way that makes it dangerous: both wrong versions still return `201` with a plausible-looking plane; nothing about the response shape signals that an unrelated part of the photo just got worse.

**Where it stands:** resolved — the pixel with the *higher* alpha wins outright (ties to the new plane, since it exists because the Dealer tapped there), and the loser is zeroed at that pixel rather than reduced by some amount. This makes the union of every plane's coverage `max(new, existing)` everywhere, by construction, which is what actually guarantees "no pixel gets worse" rather than merely making it likely. All three fixtures pass both the per-pixel non-regression assertion and the "the tapped point itself improved" one. Recorded as implementation-decisions.md #42. Worth naming for the next correction this reasoning might apply to: **"resolve two independent soft claims on the same pixel" needs the max-wins rule, not a one-directional subtraction, whichever direction seems intuitively right.**

---

## 23. The wall overlay never actually aligned with the photo — `.consultation__picture` had no positioning context

**Ticket:** #10 · **Contributor:** Aniket Ghorpade (found by an agent) · **Date:** 2026-09-05 · **Status:** resolved

**What happened:** building the tap-layer button for ticket #10's correction surface (`position: absolute; inset: 0`, a sibling of the wall-overlay divs and the wall-chip buttons, all inside `.consultation__picture`), a screenshot of the actual rendered layout showed the wash covering the *entire browser window*, including the toolbar, not just the photo. `.consultation__picture` — the CSS class every one of these `position: absolute` elements needs a *positioned* ancestor from — had no `position` rule at all, anywhere in `consultation.css`, `components.css` or `tokens.css`. `position: absolute` with no positioned ancestor resolves against the initial containing block, which behaves like the viewport. This is not new to ticket #10: the wall-chip buttons (#7) and the wash itself (#6) have had this same latent bug since they shipped.

**Why it was hard:** nothing about it shows up in code review, a type check, or any of the existing tests — `overlayVisible`/`chipPosition` are pure functions and correctly compute *percentages*; what those percentages are relative to is a pure-CSS question neither seam reaches (conventions.md §6: the render engine and the REST contract are the two seams, and this is neither). It also does not show up by *running* the app carelessly: on a single full-bleed photo roughly filling the window, a wash covering the whole viewport and a wash covering just the photo look nearly identical, because there is barely any window left over outside the photo to notice the difference in. It took deliberately building something (the tap-layer) whose *misalignment* was checkable by screenshot — and actually opening the screenshot instead of assuming the CSS was fine — to see it at all.

Fixing the containing block was not the whole fix. Once `.consultation__picture` had `position: relative`, the wash aligned with the *whole flex box* — image plus the caption paragraph beneath it — rather than the image alone, because the caption is a sibling inside the same flex container and the absolutely-positioned children still measure against that combined box. A `position: absolute; inset: 0` sibling can only ever match the box of its *containing block*, never the letterboxed rectangle an `object-fit: contain` image renders inside that box — those are only the same rectangle when the two aspect ratios agree exactly.

**Where it stands:** resolved two ways together — a dedicated `.consultation__frame` wraps only the image and the three absolutely-positioned layers (never the caption), and its `aspect-ratio` is set inline from the displayed image's own `naturalWidth`/`naturalHeight`, read via `onLoad`. Matching the frame's ratio to the photo's own is what removes the letterboxing gap without measuring rendered pixels on every resize. Verified against the real running app (Vite dev server + a scripted Chromium session, `playwright-core` driving `google-chrome-stable` headless — Playwright itself is not installed, `playwright-core` alone was enough since it drives an existing browser rather than downloading one), not just reasoned about: `.consultation__frame`'s and the tap-layer's bounding boxes were measured and confirmed pixel-identical at the same instant, a tap at a known fraction across the rendered element produced the exact expected photo-space coordinate, and the wash's presence while a tool is armed was confirmed by sampling pixel colour rather than trusting a screenshot by eye (see decision #43). Recorded here rather than only fixed silently because the wall-chip buttons have been shipped, unnoticed, in this state since ticket #7 — worth knowing if anyone is asked why a chip or the wash ever looked slightly off on a real photo.

---

## 24. `add_wall` loaded SAM 2 before checking whether the tap even needed it, so CI's model-free lane failed on a precondition test

**Ticket:** #10 · **Contributor:** Aniket Ghorpade (hit by an agent) · **Date:** 2026-09-07 · **Status:** resolved

**What happened:** after the `main` merge, PR #40's CI ("Service tests", `pytest -m "not models"`, which runs with no model weights fetched at all) failed on `test_add_refuses_a_point_already_covered_by_an_existing_plane`: `ModelsMissing`, raised from `runtime.location.resolve_models_dir`, out of `load_graphs()`. It had passed locally throughout development because this checkout happens to have real weights under `models/` — the same shape of gap difficulty 21 already named for a different route.

**Why it was hard:** `segmentation.corrections.add_plane` already checked "is this point already covered" (`_plane_containing`) before doing anything else *inside itself* — the precondition looked correctly ordered by construction. What actually ran first was the route handler, `api/planes.py:add_wall`, which called `load_graphs()` unconditionally before ever calling `add_plane` at all, to have a `Graphs` ready to pass in. So the real order was: load the encoder and decoder graphs, *then* check the precondition, *then* possibly refuse — the opposite of what `test_corrections.py`'s own module docstring already promised: "only what runs *before* any model call — a tap that is already covered, a tap outside the photo — is covered here." Nothing in the fast-lane suite caught it earlier because this machine's `models/` directory made `load_graphs()` succeed even when its result was about to go unused.

**Where it stands:** resolved — the already-covered check is now `corrections.check_addable`, called from `add_wall` before `load_graphs()` (and before the encode-on-demand path difficulty 21 added), with `add_plane` itself calling the same function rather than repeating the check inline. Reproduced the CI failure locally first (`SPECTRAPAINT_MODELS_DIR=/nonexistent-path uv run pytest -m "not models" tests/api/test_corrections.py`) to confirm the fix actually closes the gap a passing local run could not see. Worth naming for the next correction endpoint: a precondition function checking its inputs in the right order is not the same claim as the *route* checking them in the right order — only the outermost caller's sequencing is what a client (or CI) ever observes.

---

## 25. The full-resolution export test could not tell full-res from preview at 256 px

**Ticket:** #12 · **Contributor:** Aniket Ghorpade (hit by an agent) · **Date:** 2026-09-08 · **Status:** resolved

**What happened:** the first `test_export_is_full_res_while_browsing_stays_preview` uploaded a 256×192 fixture — below the `MAX_PREPARED_DIMENSION` 1280 cap — so the browsing render and the export came back at identical pixel sizes, and the test could only assert JPEG-vs-PNG plus headers. The headline acceptance criterion, "export triggers a full-resolution render", had no test actually measuring it; the test's own comment showed the confusion, concluding that the content-type split "proves the export path was taken" when it proves no such thing about resolution.

**Why it was hard:** the stub preparation genuinely caps like production (`decode_photo` downscales above 1280), so any small fixture exercises both paths identically and the difference is invisible — a green test guaranteed nothing about the criterion. A review pass caught what the passing test hid.

**Where it stands:** resolved — the fixture is 1600×1200, above the cap: the browsing render is asserted at `MAX_PREPARED_DIMENSION` and the export at the photo's own size, so the criterion is measured rather than inferred. The same review caught a real bug in the export bridge: the `finally` deleted the temp file on every path, including the dialog-throw fallback that returns the temp file *as* the deliverable — the Dealer would be shown a file that vanished. Cleanup is now conditional on the temp copy not being the file just revealed (recorded in implementation-decisions.md #39).

---

## 26. Better negative prompts make the matte worse, because the labels they come from are wrong across half the frame

**Ticket:** #31 · **Contributor:** Aniket Ghorpade (found by an agent) · **Date:** 2026-09-15 ·
**Status:** resolved — approach abandoned, and it should not be tried again without new evidence

Follow-up to [difficulty 12](#12-the-photographs-arrived-and-the-pipeline-is-less-accurate-than-the-thresholds-it-was-given).

**What happened:** #31 listed "SAM 2 prompting: the spill originates in the refined mask, so better
negative prompts on the named exclusions may contain it" as a candidate direction, and it is the
best-reasoned one on the list. `prompts.py` draws negative points only from the four excluded
classes, so on `corner-with-clothesline` SAM 2 receives *no* negative evidence at all about the
clothes it then paints — while SegFormer does correctly label some of those pixels `apparel` and
`towel`. Adding a second tier of classes as negative points looked like free containment at the
place the leak starts.

It measures worse. Leakage on that photograph rose from 0.338 to 0.369 and wall IoU fell from 0.771
to 0.752 — both moving the wrong way at once.

**Why it was hard:** the failure is invisible from the semantic map's confusion table, which is
where the idea came from and where the labels look useful. Counting how much of the *frame* each
class claims is what explains it: the checkpoint calls 17.8% of `corner-with-clothesline` and 48.3%
of `windows-with-curtains` a curtain, apparel, towel or mirror — several times what those objects
actually occupy. So the negative points land on real wall, SAM 2 believes them, and it pulls its
boundary off wall it previously had right. Leakage and IoU degrade together, which is the signature
of a mask that moved rather than one that shrank.

Two plausible explanations were ruled out before accepting that. Gating the points to pixels where
wall confidence is under 0.5, 0.3 or 0.1 changes nothing — the grid sampler already picks
low-confidence pixels, so the gate mostly reselects the same points. Budget displacement is not it
either: negatives grew from 4 points to 10 and the fear was that floor and ceiling lost their slots,
but sampling the exclusions first and giving the distractors only the remainder still loses (0.354
against 0.338), as does widening the negative share from 0.625 to 0.50 or 0.40.

**Where it stands:** abandoned, and the plumbing reverted — `tools/export_onnx.py`, `semantic.py`
and `prompts.py` are back to the four-class tier, and the graphs re-exported so `runtime.json`
matches the exporter that wrote it. The finding worth keeping is the general one, because it applies
to every future idea that reads more classes out of this checkpoint: its labels are not reliable
enough to be **evidence**, not merely not reliable enough to be **rules**. An approach that feeds
them to SAM 2 needs a reason to believe they are right about *where* the object is, not only about
*what* it is. The same classes used for outright removal, with prompts untouched, are worth 0.005 —
measured, and rejected on cost in implementation decision 49.

---

## 27. The frame fitted the tap layer but not the stage, and a greyscale matte has no alpha to read

**Ticket:** #49 · **Contributor:** Prasad K (hit by an agent) · **Date:** 2026-10-03 · **Status:**
resolved

Follow-up to [difficulty 23](#23-the-wall-overlay-never-actually-aligned-with-the-photo--consultationpicture-had-no-positioning-context).

**What happened:** two defects that only a browser could see, both of which the whole test suite
called green.

The first is a direct consequence of fixing #23. The frame was given an inline `aspect-ratio` from
the photo's own dimensions and `height: auto`, inside a flex column stage — and nothing bounded its
*width*. A photo taller than the free space therefore made the frame grow past the stage, which
clips it: a 3:4 portrait lost roughly half itself, a 4:3 lost its top and bottom. Nothing about
#23's check could catch this, because #23's check measured the frame against the tap layer, and both
were wrong together — they agreed perfectly on a box that was simply too tall. An alignment check
proves two elements match; it says nothing about whether the thing they agree on fits.

The second was in the replacement for the wash (see decision #51): the chosen wall is now marked by
an outline, and `matteOutline` decided which pixels belonged to the wall by thresholding the
**alpha** byte of the matte's `ImageData`. The Alpha Matte is served as an 8-bit mode-L greyscale
PNG (`planes.py` `_encode_matte`), so a decoded matte carries coverage in R, G and B and is **alpha
opaque on every pixel**. Thresholding alpha read 255 everywhere, saw a single wall covering the
entire photograph, and outlined the photo's frame — a rectangle around the room — instead of the
wall's edge. The outline would have drawn something, it would have been perfectly aligned, and it
would have been completely wrong.

**Why it was hard:** the first defect is invisible to any test that compares elements to each other,
and the unit tests for `matteOutline` passed because their synthetic matte was built to match the
implementation's assumption rather than the service's actual output. Difficulty 11 records the same
class of bug arriving from the other direction — a CSS mask on a greyscale PNG failing *open* and
brightening the whole photo. A greyscale PNG is the recurring hazard in this codebase: two features
have now read the wrong channel off one, and each looked correct in isolation.

Neither bug is reachable by seam 1 or seam 2 (conventions.md §6) — this is browser layout and image
decoding. So the check had to be built rather than found: a temporary harness mounting the real
`ConsultationSurface` and `useConsultation` against a scripted `window.spectrapaint`, driving the
whole Dealer flow in-page and asserting real `getBoundingClientRect()` geometry, run across
1280×720 and 1920×1080 × photo ratios 0.5, 0.75, 1.33 and 1.78.

**Where it stands:** resolved. The stage's free space is now a size container
(`.consultation__frame-slot`) and the frame is the largest box of the photo's ratio that fits it —
`width: min(100cqw, calc(100cqh * var(--photo-ratio, 1)))`, height derived — so it is bounded on both
axes and #23's invariant still holds. All 8 cells measured the frame inside the slot with overlays,
chips and tap layer pixel-identical to it: portrait ratios height-limited (272×544 at ratio 0.5),
landscape ratios width-limited (821×461 at ratio 1.78), nothing clipped at any size. `matteOutline`
now thresholds the **grey level** at 128, the halfway point of the coverage range the service
encodes, matching the `mask-mode: luminance` the wash has always used on the same bytes.

The harness was first run once and deleted. Review then asked for the layout check to stay, so it is
now `apps/ui/src/consultation/layout.test.ts` with `layoutHarness.tsx`: the same real components over
a scripted bridge, in headless Chromium, part of `npm run check` (the one named exception in
design-decisions.md §9d). It was confirmed to fail against the old width-only frame rule (7 of 12
cases), and a second case — an EXIF-rotated photo whose placeholder is landscape and whose prepared
photo is portrait — confirmed to fail without the guard that keeps the walls off the screen until the
frame has the new image's ratio. Also kept: the four `walls.test.ts` cases that fail against the
alpha-thresholding version — confirmed by re-introducing it — plus the measurements above. Note the
original harness also had its own bug of the same family, worth recording
because it is easy to repeat: it read `window.__consultation` into a local before each click, and
`useConsultation` returns a fresh object every render, so every assertion after a click was reading
the answer to the previous question. **A snapshot taken before a state change reports the old state,
however carefully it was captured.**

## 28. Issue #50 wanted hook-level tests, and the repo has no DOM/React-testing packages

**Ticket:** #50 · **Contributor:** Chauhan Anamika Abhimanu (hit by an agent) · **Date:** 2026-10-02 · **Status:** resolved by factoring, then by the browser harness

**What happened:** the issue's testing plan asks for **hook-level** coverage — "apply Shade A then
Shade B, then undo; `assignments` equal the post-A snapshot and exactly one render request is made; a
split clears the history." The repo's vitest suite runs in the `node` environment and contains no
`jsdom`/`happy-dom`, no `@testing-library/*`, and no `react-test-renderer`; the `react-hooks` ESLint
plugin is the only React-aware tooling. Rendering `useConsultation` in a test would have required
adding devDependencies and touching `package-lock.json`.

**Why it was hard:** `package-lock.json` carries a peer's uncommitted change on this branch, so any
lockfile churn (even a devDependency-only install) would have mixed someone else's work into this
ticket's diff — exactly what isolated fresh contexts are not supposed to do to each other. And
`docs/conventions.md` §6 restricts the vitest suite to *pure functions* anyway; a hook test needs a
DOM, which the conventions file explicitly routes to seam 1.

**Where it stands:** resolved twice over. First the way `applyRenderEvent` and `applyProgressEvent`
were resolved before it: every decision the hook makes during undo/redo was factored into pure
functions — `history.ts` (`record`/`undo`/`redo`, the cap, the future-clearing), `shadeCodeOf` (what
a restored repaint pins its reply to) and `restorePlan` (original photo, repaint, or keep what is on
screen) — and `useConsultation.test.ts` states the scenarios against those.

That left the sequences themselves untested, and review found a bug in exactly that glue: choosing a
wall before any Shade, then Undo, then Redo, asked the service to paint nothing and showed a failed
repaint — `redoPaint` lacked the empty-snapshot guard `undoPaint` had, and the pure layer could not
see it. By then the repo had a real-browser harness (design-decisions.md §9d, technical difficulty
#27), and it renders the real `useConsultation`. So `undo.test.ts` runs the issue's scenarios as true
hook tests: two Shades then Undo leaves the post-A paint with exactly one more render request; a
split clears the history; Undo in the Catalogue search box acts on the text; and the wall-choice
round trip makes no request at all. The scripted bridge answers an empty paint the way the service
does (`malformed_request`), so that bug fails the test rather than hiding behind a lenient mock.
Confirmed by reintroducing it: two cases fail. One trap worth recording: a test that fires a menu
command straight after a state change races React's commit and hits the previous render's handler —
tests wait for the published `canUndo` first, which is what a real menu click is ordered after.

## 29. The matte's edges were the semantic grid's edges, and every layer above it preserved them faithfully

**What it looked like.** Square, stair-stepped paint edges and square holes on pages 2, 4, 5, 6 and 7
of the bug report's PDF, with 75–84% of razor edges sitting exactly on 128-grid lines. A Door's eye
reads it as an artefact of image processing; what it actually was is arithmetic — a value that was
quantised early and then carefully preserved by four layers that had no reason to suspect it.

**The mechanism, in four parts.**

1. SegFormer returns logits at stride 4. The pipeline argmaxed them on that 128×128 grid and
   upsampled the resulting **labels** nearest-neighbour, so every boundary became a staircase of
   10-px steps. `semantic.py`'s docstring called this "expected" and assigned it to SAM 2 and the
   refinement pass.
2. That claim was checkable and did not hold. On the photographs in the bug report, SAM 2's
   single-mask logits are within ±2 of a constant on 77–100% of pixels and its `iou_scores` are
   0.00–0.04 (on the six labelled fixtures the score runs 0.043–0.841 — the range
   `REFINER_TRUST_FLOOR` was measured against) — the refiner barely shapes the matte on those
   photographs, so the semantic grid is what actually sets its edge.
3. The grid masks were then written into the matte as hard 0/1, and the exclusion was **re-imposed
   after softening** (`matte.py`), which overwrote every soft edge the softening had just produced.
4. The softening added squares of its own: 3×3 rank-filter morphology, and a three-zone
   `np.where` that put a full 1.0 step where the band met the core and a full 0.0 step where it met
   the exterior.

Each layer is individually defensible. That is the difficulty: nothing here looks like a mistake in
isolation, and every one of them preserved the artefact faithfully enough that fixing only one
produced no visible change.

**Deciding at photo resolution instead.** The fix is to upsample the *probabilities* bilinearly and
take the argmax at the photo's own resolution, so the boundary follows a smooth contour. An average
of two probabilities is still a probability; an average of two class indices is a class that does not
exist.

**Where it stood:** the first attempt argmaxed the five relevant planes outright, and the models lane
answered in the negative three times over — each time with a number rather than an opinion, which is
what made the next attempt a different one rather than a larger one.

| gate | what the lane said |
| --- | --- |
| flat five-way argmax | `corner-with-clothesline` leakage 0.338 → 0.391, `windows-with-curtains` shadowed-wall recall −0.034, and the Add tool could no longer grow a plane at a wall pixel the matte had missed |
| gate on `1 − Σ relevant` | shadowed-wall recall back to 0.769 — 145 classes collectively own the softmax tail, so a shadowed wall at 0.3 is beaten 145 times over by a total of 0.7, comes back *unclaimed*, and stops being exempt from the confidence floor |
| gate on the best *single* other class, at photo resolution | two failures, and for a reason worth keeping: it smooths the wall↔unclaimed boundary, which nothing quantises anyway, while flipping a few wall→exclusion pixels that the grid decision had called wall — and exclusion is absolute, so those become unpaintable by a correction tap |
| coarse claim, fine winner (kept) | 38 passed, no regression |

The last row is not a compromise; it is the documented behaviour from the start. A pixel of sofa is
*unclaimed* — the module has always said so — and argmaxing five planes outright forces every pixel
of every unlisted class onto the nearest of them, which is the first row. The residual grid-shaped
boundary is the claimed↔unclaimed one, and it is left on the grid on purpose, because an unclaimed
pixel is neither restored, nor zeroed, nor deleted: it keeps SAM 2's own soft value.

**Two ways the obvious fix was wrong in its own turn, both caught by measuring rather than reading.**

- Round morphology is meant to stop a band's square corners, and `erode_round` first shipped erasing
  by *nothing*. Pillow's `GaussianBlur(radius)` takes the radius as the standard deviation, so a
  half-plane blurs to exactly 0.5 on its own edge and thresholding there removes no pixels at all. It
  was also written with the comparison inverted, and it survived a full models-lane run: on straight
  edges — which is most of what a room photograph contains — "erodes by nearly zero" is
  indistinguishable from "round erosion barely matters". It cost 0.031 of `windows-with-curtains`'
  shadowed-wall recall. The threshold is now `Φ(1)`, chosen because it is the level one sigma inside a
  straight edge, which is the only definition that makes it match `erode`.
- A disc kernel is blind to small features in a way a square is not. Blurring with sigma 26 gives an
  **isolated** mask pixel 10px away a weight of about 1e-4, which rounds to zero in 8-bit and
  disappears. `soften_boundary`'s outer band is therefore bounded with square morphology — which is
  also the honest shape, because the thing being bounded is a guided filter's square window — while
  the core uses the round version, where the corners are what matters. Switching that one call deleted
  the Add tool's correction on `patterned-wallpaper-with-curtain` outright.

**And one place the issue's own prescription did not survive contact.** `REFINER_TRUST_FLOOR` was
specified as 0.3, on the reasoning that SAM 2's `iou_scores` are low everywhere. They are not: they
run from 0.043 to 0.841 across the six fixtures, so 0.3 is a line through the middle of the range
rather than a floor, and it lands on the one fixture where the fallback is *worse*. Measured both ways
on every labelled fixture, the fallback wins on four of five and loses on one — so the score does not
predict which matte is better and no threshold on it separates them. What it can do is catch a
degenerate decode, which is where 0.1 sits.

**Where it stands:** resolved. The matte's boundary is decided at photo resolution from upsampled
probabilities, the exclusion fades out instead of being re-imposed, the band blends continuously
instead of stepping, and the seam between two planes takes the union rather than the higher claim. The
`synthetic diagonal` unit test measures `edge_on_grid_fraction` on the matte and finds **no razor edge
at all** along the boundary, against a nearest-neighbour control on the same input that scores 0.70.
