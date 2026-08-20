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
