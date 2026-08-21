# SpectraPaint — Implementation Decisions

**Status:** Living document · Append-only, newest entry last

Every major decision taken **while implementing** a ticket, why it was taken, and who took it.

This is not [design-decisions.md](./design-decisions.md). That document records the decisions made
*before* code existed, during the design grilling session. This one records the decisions the code
forced — the ones nobody could have made from the spec alone, because they only became visible once
a real file, a real library or a real failure was in front of somebody.

**Why this file exists.** V1 is worked ticket by ticket in isolated fresh contexts. Nobody working
ticket #9 was present for the argument that settled ticket #5, and the code alone records *what* was
chosen while losing *why* — which is exactly the half a later contributor needs in order to change
it safely. Without this file, every such decision gets silently re-argued, or worse, quietly
reversed by somebody who assumed it was arbitrary.

**Who** is recorded for the same reason a commit records an author: a decision has somebody who can
be asked about it. Name the person who owns the change — the human on the pull request — and note
where an agent wrote the code, since the reasoning was still a human's to accept.

---

## When to write an entry

Write one when any of these is true:

- You chose between genuine alternatives and the spec did not settle it
- You deviated from what a document said, for a reason
- You made a choice a later contributor could reasonably assume was arbitrary — and undo
- You bounded something: a limit, a timeout, a threshold, a page size
- Somebody reviewing the pull request asked "why is it done this way?"

Do **not** write one for: routine choices with an obvious default, anything already recorded in
`design-decisions.md`, or anything the code says plainly by itself.

If the decision is **hard to reverse**, it is an [ADR](./adr/) instead — see the test in
[README.md](./README.md). If it blocked you rather than being decided,
[technical-difficulties.md](./technical-difficulties.md) is the right file.

## Entry format

Copy this. Keep it short — a decision nobody reads is not recorded.

```markdown
## <n>. <What was decided, as a statement>

**Ticket:** #<number> · **Contributor:** <name> · **Date:** YYYY-MM-DD

**Decided:** what is now true in the code.

**Why:** the reasoning, including the alternatives rejected and what they would have cost.

**Consequence:** what this makes harder, and what would have to change to reverse it. Omit if
genuinely nothing.
```

Number entries sequentially and never renumber — a reference to entry 12 must stay pointing at
entry 12. Append; do not edit a past entry to say something different. If a decision is later
reversed, write a new entry that says so and links back to the one it replaces.

---

## 1. The Catalogue data file is JSON, with a pinned colour space in its header

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-19

**Decided:** one JSON file per Catalogue version, `<catalogue_id>-<version>.json`, carrying a header
(`catalogue_id`, `catalogue_name`, `version`, optional `source`, and a required `colour_space`) plus a
`shades` array of `shade_code` / `name` / `shade_family` / `lab` / optional `finishes`. Field names
are `snake_case`, matching the HTTP contract. The schema is documented in
[`data/catalogue/README.md`](../data/catalogue/README.md).

**Why:** the spec fixed the *contents* per Shade (design-decisions §7) but not the file format, and
three candidates were real. **CSV** is the natural shape for a thousand flat rows and is what a
manufacturer is most likely to send — but it has nowhere to put the header, so `catalogue_id` and
`version` would have to live in the filename or a sidecar file, and the one field we must record on
every Render would be the easiest one to lose. **TOML** reads well by hand and needs no dependency in
3.12, but a thousand-entry array of tables is not a format anyone enjoys either reading or
generating. **JSON** takes the header naturally, needs only `json` from the standard library, is what
every tool that might produce this data can already emit, and is the same shape the contract serves
to the UI — so no field is renamed on the way through.

`colour_space` is required, and a value other than CIELAB / D65 / 2° is rejected at load. The spec
pins the reference white because D50 and D65 disagree on every conversion; without the field a file
measured against the wrong white would load cleanly and render subtly wrong colours for the rest of
its life, which is the worst possible failure for this application. One required field turns an
invisible fault into a loud one.

**Consequence:** a manufacturer sending CSV needs a conversion step. That is a small script and the
right place for the argument about what their columns mean — it does not belong in the loader. Note
also that JSON commits us to loading the whole file in memory to parse it; at a thousand-plus Shades
that is trivial, but a Catalogue two orders of magnitude larger would want a streaming format.

---

## 2. Two Catalogue files in the data directory is an error, not a choice

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-19

**Decided:** the Catalogue path comes from `SPECTRAPAINT_CATALOGUE_FILE` when set, otherwise from
`data/catalogue/` — which must contain **exactly one** JSON file. More than one, none, or a named
file that does not exist all raise `CatalogueFileMissing` at launch. There is no bundled default and
no fallback to an empty Catalogue. See `spectrapaint/catalogue/location.py`.

**Why:** the obvious alternative was to pick the newest file, or the highest `version`, so a
contributor could drop a new Catalogue beside the old one and have it just work. That convenience
buys a fault that is invisible in exactly the situation it occurs in: a stale file left in the
directory silently decides which Shades the Dealer sells, the two files differ in a handful of Lab
values, and nobody finds out until a saved Consultation disagrees with what is on screen. The whole
reason the Catalogue identity and version are stamped onto every Render (design-decisions §7) is that
this class of mismatch is expensive — resolving it by guessing would undercut that.

Failing at launch rather than at first search is the same argument as model load failure surfacing at
boot: the Dealer finds out before a Customer is standing at the counter, not during.

**Consequence:** swapping Catalogues in development means replacing the file or setting the
environment variable — one extra step, taken rarely. Note this also fixes what the packaged app must
do: Electron has to pass the installed path explicitly, since a packaged build has no
`data/catalogue/` to fall back to.

---

## 3. A bad Catalogue file is refused outright, and the SQLite index is in memory

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-19

**Decided:** two things, both in `spectrapaint/catalogue/`.

`loader.py` validates the **whole** file before anything is served, and the first problem stops the
load: missing or blank header fields, a `colour_space` other than CIELAB / D65 / 2°, a Lab value
outside the space, a non-numeric axis, a repeated Shade Code (compared case-folded), a blank finish, a
Catalogue with no Shades. No partial load, no skipping the bad rows.

`database.py` builds an **in-memory** SQLite database at launch and never writes to it again. Search
text is stored in `*_folded` columns, case-folded in Python at load, alongside the original for
display.

**Why refuse rather than proceed:** conventions §5 says do not refuse work that can proceed
imperfectly — and that rule is about a poor *photograph*, whose flaws the Dealer can see on screen.
Reference data is the opposite: a Catalogue missing a Shade Family, or carrying one Lab value out of
range, loads cleanly and works, and the only symptom is a Dealer telling a Customer the wrong colour.
Skipping bad rows would be worse than either — the Catalogue would be quietly incomplete, and a Shade
the Customer is pointing at in the Fandeck would simply not be there.

**Why in memory:** loading and indexing all 1,159 stand-in Shades measures **17 ms**, so persisting
the index buys nothing and costs a real risk — a cached copy on disk can disagree with the file beside
it, which is the same mismatch that made us stamp Catalogue identity and version onto every Render
(design-decisions §7). Rebuilding from the file every launch means the file cannot be wrong about
itself. Note this is deliberately *not* the database in `storage/`: Bundles and Renders must survive a
restart, and the Catalogue index must not.

**Why fold in Python rather than use `COLLATE NOCASE`:** SQLite's NOCASE folds ASCII only. A Shade
named "Café Crème" would be findable by "café" but not "CAFÉ", and manufacturer data is exactly where
accented names appear. `str.casefold()` covers Unicode, and doing it once at load costs nothing per
query.

**Consequence:** `check_same_thread=False` on the connection, which is safe only because nothing
writes after the build — if anything ever needs to write to this database, that assumption has to be
revisited rather than worked around. Finish is stored as JSON in one column rather than a finishes
table, which is right while nothing filters on it and wrong the moment something does.

---

## 4. Name search is a `LIKE` scan, not FTS5 — measured, not assumed

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-19

**Decided:** three indexes, one per access pattern, and **no FTS5 table**. Partial-name search is a
plain `LIKE '%typed%'` scan. See `_CREATE_INDEXES` in `spectrapaint/catalogue/database.py`.

**Measured** on the 1,159-Shade stand-in Catalogue, median of 200 runs, in-memory SQLite:

| Query | Scanned | Indexed |
|---|---|---|
| Exact Shade Code | 0.058 ms | **0.004 ms** |
| Shade Family browse, in Fandeck order | 0.206 ms | **0.158 ms** |
| Substring name, `LIKE '%lin%'` | **0.107 ms** | not indexable |
| Prefix name, range seek on the folded column | 0.071 ms | **0.005 ms** |
| Substring name at 50,000 rows | **5.7 ms** | not indexable |

**Why no FTS5:** a substring match cannot use an ordinary index — an index is ordered by the start of
a value, so `LIKE '%lin%'` reads every row no matter what exists. FTS5 is the standard answer to that,
and it is genuinely faster at scale. It is also a **compile-time option**. Our shipping target is
Windows with a PyInstaller-bundled Python, and a search that works on a contributor's Linux box and
silently fails on the Dealer's machine is the worst failure this project can buy — the whole app is
one counter-side interaction with a Customer watching. Against that risk, the scan costs 0.107 ms
today and 5.7 ms at fifty thousand Shades, both far inside a keystroke. Paying a portability risk for
a tenth of a millisecond is not a trade; it is a mistake with a benchmark attached. Revisit if a
Catalogue ever reaches six figures, which no fandeck does.

**A finding worth recording:** SQLite will **not** use an index for `LIKE` unless
`case_sensitive_like` is on, so the obvious `LIKE 'lin%'` for prefix ranking scans (0.071 ms) rather
than seeks. The `name_folded` column is already lowercase, so an ordinary comparison —
`name_folded >= 'lin' AND name_folded < 'lin' || char(0x10ffff)` — is both correct and seekable, and
lands at 0.005 ms. The prefix half of search in the query layer must be written that way rather than
with `LIKE`, or the index is decorative. `GLOB` also seeks, but its pattern syntax has no escape for
`*`, `?` and `[`, which a Dealer can type — so the range comparison is the safer of the two.

**Consequence:** the substring scan is linear in Catalogue size, and that is now a known, measured
property rather than a surprise. The unique index on the folded Shade Code also makes the loader's
uniqueness rule true in the database, so a future writer cannot reintroduce a duplicate and make a
Shade unreachable.

---

## 5. Search is tiered, not scored

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-19

**Decided:** `Catalogue.search` answers in four ordered tiers — the exact Shade Code, then Shade Codes
beginning with what was typed, then names beginning with it, then names containing it anywhere —
with Fandeck order inside each tier and each Shade appearing once, in its best tier. No relevance
score. `find_by_code` stays a separate method returning one Shade or `None`. See
`spectrapaint/catalogue/queries.py`.

**Why:** the obvious alternative is one query with a computed score, which is less code and reads
more cleverly. It also occasionally puts a name match above the exact code the Dealer just typed,
because scores blend evidence — and that code is the one thing at the counter nobody is uncertain
about. The Customer read it off a chip; the Dealer typed it; putting anything above it is the search
telling the Dealer they were wrong, in front of the Customer. Tiers cannot do that, and they are
explainable to whoever changes them next: each tier is one query, and the order of the tiers *is* the
ranking policy.

The tiers also cost less than they look. The first three are index seeks; only the last is a scan,
which is 0.1 ms at Fandeck size (entry 4). Each tier stops at the caller's limit.

**Consequence:** a Shade whose name matches strongly but whose code matches weakly cannot overtake a
weak code-prefix match. That is the intended trade, but it is a trade — if Dealers turn out to search
by name far more than by code, the tier order is the thing to revisit, not the mechanism.

**Also settled here:** `%` and `_` are escaped before reaching `LIKE`, so a Dealer searching for a
Shade called "50% Harbour" finds it instead of matching the whole Catalogue. An empty search box
returns nothing rather than everything — the Dealer has typed nothing, they have not asked for all
1,159 Shades.

---

## 6. Search and browse share one endpoint, and paging a search is refused

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-19

**Decided:** three read-only endpoints — `GET /catalogue`, `GET /catalogue/shades`,
`GET /catalogue/shades/{shade_code}` — with search and browse both answered by `/catalogue/shades`:
`q` searches, its absence browses. Browsing is paged and reports the true `total`; searching returns a
ranked shortlist whose `total` is what came back, flagged by `searched` in the response. `q` combined
with a non-zero `offset` is a `422`, not a silently ignored parameter. An unknown Shade Code is a
`404` carrying the new `shade_not_found` code. See `spectrapaint/api/catalogue.py`.

**Why one endpoint:** to the Dealer these are one thing — the panel showing Shades — and the panel
switches between them on every keystroke. Two paths would mean every caller reimplements that switch,
and the UI would hold two loading states for one visible list.

**Why refuse `q` with `offset`:** a caller that paged a search would receive a *ranking* where it
expected a page, and nothing in the response would tell it so. Silently ignoring `offset` has the
same effect and hides the mistake; the `searched` flag plus a hard refusal makes the difference
impossible to miss. This is the one place the two behaviours genuinely differ, so it is the one place
the contract is strict.

**Why read-only:** there is deliberately no endpoint that adds, edits or deletes a Shade. The file is
the source of truth and swapping it is how the Catalogue changes (entry 1) — a write endpoint would
make the in-memory index and the file disagree, which is precisely the mismatch entry 3 removed.

**Consequence:** page sizes are bounded (500 browsing, 200 searching), so a client cannot ask the
service to serialise the whole Catalogue in one response. If the UI ever wants a full Catalogue dump
— to cache it locally, say — that is a new decision and probably a new endpoint, not a raised ceiling.

---

## 7. The recently-used row lives in `localStorage`, not in the service

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-19

**Decided:** the recently-used Shades are kept in the renderer's `localStorage`, capped at eight, and
keyed by Catalogue identity. See `apps/ui/src/catalogue/recentShades.ts`.

**Why:** the alternative is the service, and ticket #11's SQLite database — which owns Bundles,
Consultations and Renders, all things a Dealer would be upset to lose. This is not that. It is a
scratch list worth something for the length of one Consultation and nothing the next morning, and
putting it in the Bundle schema would mean a table, a migration and a contract endpoint for
convenience nobody would miss if it vanished. It also has no business being saved *into* a
Consultation: reopening a saved Consultation must show what the Customer saw, and a list of Shades
the Dealer skimmed past is not that.

Keyed by Catalogue identity because a code from another manufacturer's file would otherwise sit in
the row as a dead entry — the Dealer taps it and nothing is there.

**Consequence:** the row does not follow a Dealer to a second machine, and clearing browser storage
clears it. Both are acceptable for something that is stale within the hour. Storage can also fail —
it is wrapped, logged, and degrades to an empty row rather than taking the panel down with it.

---

## 8. The virtualised list is hand-rolled, with a fixed row height

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-19

**Decided:** no virtualisation library. `visibleWindow` computes which rows to draw from the scroll
position and a **fixed** row height; the rest of the list is two blocks of padding. Pages of 200
Shades are fetched as the window reaches them. See `apps/ui/src/catalogue/virtualise.ts` and
`ShadeList.tsx`.

**Why:** `docs/ui-guidelines.md` rules out a component library for V1, and the case for one here is
weaker than usual: the list has one column, uniform rows and no grouping inside its scroll area,
which is the exact case where windowing is thirty lines of arithmetic. That arithmetic is pure and
tested, where a dependency would be neither.

Fixed row height is the load-bearing simplification. Variable heights need measurement, a cache and a
correction pass when an estimate turns out wrong — most of the weight of a real library — and buy
nothing here, because every Shade shows the same three lines.

**Consequence:** `ROW_HEIGHT` in `ShadeList.tsx` and `--shade-row-height` in `catalogue.css` must
agree; if they drift, the padding is wrong and the scrollbar lies. Both carry a comment saying so.
A future swatch that wraps to two lines is not a CSS change — it is a change to this decision.

---

## 9. The UI converts Lab to sRGB; the service serves Lab only

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-19

**Decided:** `GET /catalogue/shades` returns each Shade's **Lab** value and nothing else about its
colour. The renderer converts to sRGB for the swatch, in `apps/ui/src/catalogue/colour.ts`, pinned to
D65 / 2° and the piecewise sRGB transfer function.

**Why:** the tempting alternative — have the service send a ready-made hex colour — would put two
answers to "what colour is this Shade?" into the system, and the render pipeline needs the Lab value
regardless. The moment a hex string exists in the contract, something downstream will use it for
maths it is not fit for: sRGB is not linear, and ΔE00 over hex is meaningless. Keeping the contract in
Lab means the only conversion is at the screen, which is where the spec puts it.

**Consequence:** the conversion is now in two places overall — here for swatches, and later in the
render engine for walls — and the two must stay pinned to the same reference white or a swatch and a
rendered wall will disagree. That is a real risk, and the reason `colour.ts` states its pinning in
the module docstring and is tested against reference values for the sRGB primaries rather than
against itself.

---

## 10. The renderer's request whitelist now permits a query string

**Ticket:** #5 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-19

**Decided:** `apps/desktop/src/contract-path.ts` accepts a single `?` followed by characters from
exactly the set `URLSearchParams` emits — unreserved characters, `*`, `%`, `=`, `&`, `+`. A second
`?`, a `#`, and `..` anywhere in the *path* are still refused.

**Why:** the Catalogue endpoints take parameters, and the whitelist rejected every `?`, so search and
paging were unreachable from the renderer. Widening a security check to make a feature work is
exactly the change that deserves recording, so: the property being protected is that the renderer
cannot make the main process fetch an arbitrary host, and that lives in the *path* half, which is
unchanged. The query half is restricted to what an encoder produces, so anything a Dealer types —
spaces, accents, `#`, a slash — arrives percent-encoded and passes as `%` plus hex, while a
hand-built URL does not.

`#` stays refused deliberately: a fragment would let a caller hide the tail of a URL from this check
while `fetch` still sees it. `..` is now checked in the path only, because a Dealer searching the
Catalogue for ".." is asking a question, not climbing a directory tree.

**Consequence:** callers must build query strings with `URLSearchParams`, not by concatenation. The
tests state that as a rule rather than an accident, including the case of each character a Dealer can
type.

---

## 11. Preparation runs on a worker thread, and progress is a replayed per-session log

**Ticket:** #4 · **Contributor:** Prasad Kathe (code written by an agent) · **Date:** 2026-08-19

**Decided:** Photo preparation is a `PreparationJob` that runs its stages on a daemon worker thread
and records one event per stage into a per-session log. The events endpoint replays the log to each
reader, then streams live events, then ends with exactly one terminal event (`done` or `failed`).

**Why:** The thread was forced by testability, and the replay by the acceptance criteria. An
`asyncio.create_task` scheduled during the upload request never runs after that request returns under
FastAPI's TestClient (see technical-difficulties.md #5), so an event-loop job would never progress in
test; a thread is independent of any request's loop and also keeps CPU-bound Pillow decoding off
uvicorn's event loop. Replay is how "opening the stream slightly after work has started still yields
sensible progress" is met in the strong case — a reader connecting after the job already finished
still receives the whole log instead of waiting forever for a terminal event already sent.

**Consequence:** A session deleted mid-preparation abandons at most a few milliseconds of work (the
thread is daemonic and short-lived); there is no way to cancel it. The log lives in memory and dies
with the process, consistent with the deliberately in-memory session registry. Reversing this to an
event-loop job would mean first solving the TestClient problem the thread exists to avoid.

## 12. Ticket #4 runs only real preparation stages; the model stages join later, same list

**Ticket:** #4 · **Contributor:** Prasad Kathe (code written by an agent) · **Date:** 2026-08-19

**Decided:** `build_preparation_stages` is the single stage list. For #4 it contains one real stage —
decode the photo's pixels ("Reading your photo…"). Tickets #6/#7/#8 add their stages (walls, light,
edges) to the same list; nothing about the buffering, streaming or termination machinery changes.

**Why:** The upload's structural check (`verify()`) does not decode — a JPEG with its EOI marker
stripped passes it — so decoding is the first genuinely real preparation step and it closes that
gap by failing a photo cleanly in the background rather than somewhere downstream. Fake stages were
rejected: the stream must report only work that actually ran, so the Dealer is never told "Finding
the walls in your photo…" when nothing found anything. The acceptance criteria need the *streaming
infrastructure* to exist and terminate; they do not require segmentation work that belongs to #6.

**Consequence:** `create_app` takes `preparation_stages` as an argument (like the secret), so tests
inject deterministic stages instead of timing the real pipeline. The stage list is the seam a later
ticket reads to know where to plug in.

## 13. The progress stream is a separate fetch-based bridge in main, not part of the request bridge

**Ticket:** #4 · **Contributor:** Prasad Kathe (code written by an agent) · **Date:** 2026-08-19

**Decided:** A dedicated IPC bridge (`registerProgressStreamBridge`) opens `fetch` against
`GET /sessions/{id}/events` in the Electron main process with the secret in the `Authorization`
header, parses SSE frames, and forwards each event to the renderer. The preload exposes
`onProgress(sessionId, listener)` returning an unsubscribe function.

**Why:** The generic request bridge reads a single JSON body, which an SSE stream is not. The secret
must travel in a header, and the browser's `EventSource` cannot set headers — so the stream cannot
live in the renderer at all. The session id is validated against `^[0-9a-f]{32}$` (uuid4 hex) before
it reaches a path, so the renderer cannot name a route outside the contract. A stream that ends
without a terminal event is synthesised as a `failed` event in main, so a dropped connection or a
service death can never leave the Dealer staring at an endless "working…".

**Consequence:** The renderer holds a fifth bridge method. A later web target gets the same behaviour
by implementing the same `onProgress` contract against the same SSE endpoint.

---

## 14. The Room Photo appears only when preparation finishes, not when the upload returns

**Ticket:** #4 · **Contributor:** Prasad Kathe (code written by an agent) · **Date:** 2026-08-19

**Decided:** Issue #2 shipped the photo appearing as soon as the upload response returned. Ticket #4
changes that deliberately: `applyProgressEvent` reaches `ready` only on the stream's `done`, and
`ConsultationSurface` renders the photo only at `ready`. The photo bytes are already held in the
renderer from the upload — this is purely a change in *when it is revealed*, never a re-fetch.

**Why:** the whole point of the stream is that the Dealer sees what is happening instead of a silent
spinner. Revealing the photo at upload would cut the stream's last frame off — the Dealer would be
looking at the room while "Reading your photo…" was still the honest state. Making the terminal
event the single gate on the photo also turns a missing terminal into the one failure the UI must
defend against, which is why main synthesises a `failed` event when a stream dies early, and why the
START bridge refuses with an event rather than silently (see difficulty 5 and the fix to the three
silent returns). This is the reveal-timing design the segmentation tickets inherit.

**Consequence:** a session whose stream never reaches `done` never shows the photo — correct, because
"never" is exactly the dead-end the never-dead-end rule forbids. Worth knowing, and the reason the
review asked for this entry: the photo's bytes now live for the session's whole life *on the service*
too — captured in the preparation job's stage closure (up to 25 MB) instead of being discarded after
the upload gate. Later tickets need the photo anyway, so this is the right direction, but it is a
memory profile change over what issue #2 shipped; session deletion (UI discard, or the failed-cleanup
in the hook) is what releases it.

---

## 15. The render engine is a pure function in linear RGB, and the service owns every encode

**Ticket:** #3 · **Contributor:** Chauhan Anamika Abhimanu (code written by an agent) · **Date:** 2026-08-19

**Decided:** `engine.render(linear_photo, alpha, light_map, target_shade, light_tint)` takes
linear-light arrays and returns one sRGB `uint8` composite. No I/O, no file formats, no state — the
API layer decodes the upload and encodes the PNG, and `render/` never learns either exists. Both
gamma directions go through lookup tables in `render/luts.py`: 256 entries for linearising 8-bit
input, which is exact because a byte has 256 values, and 4096 for encoding.

**Why:** purity is what makes this test seam 2 rather than an integration test. A photo built as
`known_shading × known_base` has an analytically known answer, so correctness is *provable* before
either model exists — and every impurity that leaks in (a log line, a config read, a model call)
destroys that. The linear-space requirement is physical: reflectances multiply, and the light map is
the per-pixel ratio of the photo to the existing wall colour. Compositing those ratios in encoded
space is measurably too dark at matte edges, which is the dark fringing the ticket names. The encode
happens exactly once, on the final composite.

The LUTs are not an optimisation added on spec: the latency spike (`design-decisions.md` §13)
measured the encode at 241 ms via a 256-entry table against 507 ms with a per-pixel `pow`, and
linearisation at 139 ms against 457 ms. On the Dealer's per-tap loop that is the difference between
immediate and waiting. Encoding gets the larger table because its input is a continuous float rather
than a byte, so table size is the only thing bounding quantisation error there.

**Consequence:** anything that wants to render must linearise first, which is why preparation
produces `PreparedPhoto` rather than raw pixels (§18). A later ticket that needs logging inside the
engine has to put it in the caller instead — that is the constraint working, not a problem.

---

## 16. Shades cross from CIELAB to linear RGB inside the colour module, under D65 with no adaptation

**Ticket:** #3 · **Contributor:** Chauhan Anamika Abhimanu (code written by an agent) · **Date:** 2026-08-19

**Decided:** the Catalogue stores each Shade's colour in CIELAB, and `colour.lab_to_linear_rgb`
converts it to linear RGB: Lab → XYZ under the D65 white point, XYZ → linear sRGB via the IEC
61966-2-1 primaries, clamped to `[0, 1]`. **No chromatic adaptation is performed**, because the
Catalogue's reference white and the render pipeline's are the same one — the loader enforces
`{"space": "CIELAB", "reference_white": "D65", "observer": "2"}` on the file
(`catalogue/loader.REQUIRED_COLOUR_SPACE`) and refuses to start otherwise.

**Why here:** the composite happens in linear RGB, so a Shade defined in Lab has to cross somewhere.
Putting the crossing in the colour module gives it one home, keeps the engine purely linear, and
leaves the Catalogue exact at the source. The piecewise sRGB transfer function is used in both
directions, never a 2.2 power curve; the two are visibly different in the shadows, which is exactly
where a repainted wall is judged.

**Why no adaptation, stated explicitly:** an earlier draft of this entry claimed a D50→D65 Bradford
adaptation, which the code never performed and must not — the Catalogue is D65 by contract. Adapting
a D65 value as though it were D50 would shift every Shade in the Catalogue by an amount too small to
see on one chip and far too large to accept across a fandeck. The loader's check is what makes the
absence of adaptation safe rather than merely convenient.

**Consequence:** a Catalogue file in any other colour space is a boot failure, not a silent
mis-render. If one ever has to be supported, the adaptation goes in this module and this entry gets
a successor — not a quiet edit.

---

## 17. Scene estimates are interior medians, with a floor on the base colour and a luma-normalised tint

**Ticket:** #3 · **Contributor:** Chauhan Anamika Abhimanu (code written by an agent) · **Date:** 2026-08-19

**Decided:** until the segmentation tickets produce real Wall Planes, both scene inputs are estimated
from the photo itself, over its **interior** — a band of 5% of the shorter side excluded on every
edge (`engine._EDGE_BAND_FRACTION`):

- **Base colour:** the per-channel median of the interior, floored at **0.02 in linear light**
  (`engine._BASE_COLOUR_FLOOR`).
- **Light tint:** the same interior median, divided by its own **ITU-R BT.709 luma**.

**Why medians:** a window or a lamp clips a channel and drags a mean toward white; a median survives
it. **Why an interior band:** the edge of a phone photo routinely holds a door frame, furniture or
lens vignette, none of which is wall. **Why the floor:** the light map divides by the base colour, so
a zero channel would put `inf`/`nan` into every pixel downstream. 0.02 rather than a value near
`1/255` because a channel that dark carries no recoverable wall colour at all — flooring at the
smallest representable value would technically avoid the division but would produce a light map of
absurd gain, which is a poisoned render with extra steps. **Why luma, not a channel average:** the
tint must carry the light's *cast* and none of its brightness, so multiplying a Shade by it changes
the hue and not how light the Shade reads. Dividing by BT.709 luma makes neutral light come back as
exactly `(1, 1, 1)`; a plain average would weight a saturated blue as heavily as a saturated green
and tint away from the very cast it measured.

**Explicit limitation, recorded:** both estimates assume the interior is predominantly one wall.
A multi-wall room biases them toward the largest wall. Accepted for now — it matches the stub matte's
"largest plane wins" behaviour, and `design-decisions.md` §12 tracks the wall-splitting questions.

**Consequence:** these are the two functions the segmentation tickets replace first, and the only
places in the render path that guess. The constants live at module scope so they can be retuned
against real photographs (`conventions.md` §4).

---

## 18. The render contract takes `assignments`, returns a PNG, and reads what preparation produced

**Ticket:** #3 · **Contributor:** Chauhan Anamika Abhimanu (code written by an agent) · **Date:** 2026-08-19

**Decided:** `POST /sessions/{id}/renders` takes `{ "assignments": { "<wall_plane_id>":
"<shade_code>" }, "mode": "realistic" | "true_colour" }` and responds `201` with `image/png`.
Today the only accepted key is `renders.STUB_WALL_PLANE_ID`; the wall itself is a centred,
soft-edged rectangle covering 60% × 55% of the photo, built during preparation. The prepared photo
is capped at 1280 px on its long side.

Error statuses, chosen to match what the rest of the contract already means:

| | |
|---|---|
| Unknown session | `404 session_not_found` |
| Preparation failed for that photo | `422 unsupported_image` |
| Shade Code not in the Catalogue | `404 shade_not_found` |
| An assignment naming a plane the photo does not have, or none at all | `422 malformed_request` |
| Unrecognised mode | `422 malformed_request` |

**Why `assignments` and not a bare `shade_code`:** there is exactly one plane today, so a map looks
like ceremony. It is not — the Accent Wall is two planes with two Shades in one request, which is
what the shape exists for (`design-decisions.md` §7, spec "Testing Decisions"). A caller written
against a single-Shade body would have to be rewritten to gain it, and the ticket that gains it is
the next one. **Why an unknown plane id is refused:** nothing in a returned PNG reveals that an
assignment was ignored, so a Dealer who assigned a Shade to the wrong wall would be shown a picture
answering a question they did not ask. **Why `404` for an unknown Shade Code:** `GET
/catalogue/shades/{shade_code}` already returns `404 shade_not_found`; one machine-readable code
meaning two statuses would leave a caller unable to treat it as one thing. **Why PNG:** the composite
is already quantised to 8-bit by the sRGB encode, so a lossy format would degrade it for nothing.

**Why the render reads `PreparedPhoto` rather than re-deriving anything:** encode-once is structural
here. There is no endpoint that accepts an image alongside a Shade, so the render *cannot* re-encode
even if someone wanted it to, and the linearisation is paid once per photo instead of once per tap.
`require_photo` waits for preparation's terminal event rather than returning "not ready", so a render
requested while the stream is still running is served when the photo exists.

**Consequence, and it is a real one:** the upload bytes are **not** released after preparation. They
stay captured in the preparation stage's closure for the life of the session, exactly as decision
§14 records — up to the 25 MB upload cap, on top of the preview-scale linear array. This is the
current cost of preparing on a worker thread that can be replayed; ending the consultation is what
frees it, and ticket #11 is where the photo gets a home on disk instead.

---

## 19. Preparation keeps the prepared photo by type, never by position in the stage list

**Ticket:** #3 · **Contributor:** Chauhan Anamika Abhimanu (code written by an agent) · **Date:** 2026-08-19

**Decided:** `Stage.run` may return a value, and `PreparationJob` keeps it only when it is a
`PreparedPhoto`. A stage returning anything else — including `None`, which most stages do — leaves
the kept photo untouched. An earlier draft kept "the last value returned", which read as simpler.

**Why:** decisions §11 and §12 make the stage list the seam tickets #6–#8 plug into. Under
last-value-wins, the first of those tickets to append a stage that returns nothing would silently
empty the job's result, and every render would answer `422 unsupported_image` for a photo that
prepared perfectly. The failure would appear in a ticket that touched neither the render endpoint nor
this module, which is the worst possible place to debug it. Keying on the type makes appending a
stage safe by default, which is the property the seam was supposed to have.

**Consequence:** two stages both producing a `PreparedPhoto` would have the later one win, and
nothing warns about it. That is the right trade while there is one producer; a second producer is a
reason to revisit this entry, not to work around it.

---

## 20. The repaint goes through a dedicated render bridge, because the generic one reads JSON

**Ticket:** #3 · **Contributor:** Chauhan Anamika Abhimanu (code written by an agent) · **Date:** 2026-08-20

**Decided:** a third IPC bridge (`registerRenderBridge`) performs `POST
/sessions/{id}/renders` from the Electron main process and hands the renderer a data URL. The
renderer calls `window.spectrapaint.render(sessionId, shadeCode)` and gets back a `RenderResult`
discriminated union — `ready` with the image, or `failed` with the service's own code and message.
Main builds the wire body, including the stub Wall Plane id (`wall_plane_1`), which the renderer
never sees.

**Why:** the generic request bridge ends in `body: await response.json().catch(() => null)`, so an
`image/png` response arrives in the renderer as `ok: true, body: null` — a request that succeeds and
delivers nothing. Making that bridge polymorphic to carry bytes is the same temptation decision #13
rejected for the progress stream; a dedicated bridge keeps the generic one honest and puts the byte
handling where the secret already lives. The session id is validated against `^[0-9a-f]{32}$` before
it reaches a path, and an untrusted sender is refused, exactly as the other bridges do. The UI
speaks in Shade Codes (the glossary's word) and never in Wall Plane ids, because the wire shape is
this package's job.

**The stub plane id is written twice, and that is the one thing to watch here.** It is a bare literal
in `apps/desktop/src/render-bridge.ts` and in `services/inference/spectrapaint/api/renders.py`, on
opposite sides of a language boundary that nothing type-checks across. Each side's tests pin it to
its own copy, so changing one alone leaves both suites green while every repaint answers
`422 malformed_request` at runtime. The segmentation tickets must change **both**. This is the same
shape as the error-code strings already duplicated between `errors.py` and `service-bridge.ts`, and
it is accepted for the same reason — a generated shared constant is machinery this project does not
otherwise have — but a reader deserves to know the seam is two places, not one.

**Consequence:** the renderer-facing signature `render(sessionId, shadeCode)` survives the two-modes
ticket cheaply — #8's realistic/true_colour toggle adds one scalar argument — but **not** the
segmentation tickets. Naming no plane is only tenable while there is exactly one; once #6 produces
real Wall Planes the renderer has to say which wall it is painting, so the signature grows a plane
id and the Accent Wall grows a map. That is the `assignments` shape the service already speaks
(§18), arriving in the renderer one ticket later. `contract-path.ts` needed no change — its
whitelist already admits `POST /sessions/{id}/renders`.

---

## 21. A repaint replaces the photo on screen, with an explicit before/after toggle; a failure returns to the original

**Ticket:** #3 · **Contributor:** Chauhan Anamika Abhimanu (code written by an agent) · **Date:** 2026-08-20

**Decided:** tapping a Shade repaints the Wall Plane and the render replaces the photo on screen. A
"Show original photo / Show repaint" toggle in the bar flips between the two (spec user story 39:
before/after matters), and a repaint in flight is a visible "Repainting the wall…" state rather than
a frozen swatch. A failed repaint shows the service's message over the original photo with a way
back, so the Dealer is never dead-ended (conventions.md §5). The whole state machine is a pure
reducer (`applyRenderEvent` in `apps/ui/src/consultation/render.ts`) tested in vitest like
`applyProgressEvent`, and the surface renders the visible image from it.

**Why:** replace-versus-toggle had to be decided explicitly and recorded, because the ticket's
narrative ("taps a colour and part of the photo repaints") and its criterion ("a render can be
requested through the contract and returns an image") each answer only half the question. Replacing
with a toggle answers both of the questions a Dealer and Customer actually ask — "what does my room
look like painted" and "compare against what it was" — for the cost of one button. The reducer
drops a reply for a Shade the Dealer has since replaced (it checks the requested `shadeCode` before
applying `ready` or `failed`), so a fast sequence of taps cannot be overwritten by an older reply.
Selection is wired from the event (`CataloguePanel.onShadeSelected`), not from an effect watching
`selectedShadeCode`, for the same reason difficulty 3 records: an effect that sets state in response
is the signal to find the event that caused it.

**Consequence:** every later repaint feature hangs off this reducer rather than off the surface —
the two-modes toggle (#8) is another event, and per-plane Shades (#6) widen `shadeCode` into a
selection, neither of which touches `ConsultationSurface`. The render state resets with the
consultation (discard or start), and a reply arriving after a discard is dropped by the same
shade-code guard, so the reducer is the only protection the async boundary needs.


---

## 22. A model is a set of files, and the licence gate judges by what ships

**Ticket:** #6 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-20

**Decided:** a `[[model]]` entry in `models/manifest.toml` pins a **list of files** rather than one,
and the Actions cache key folds in every file's hash. PyTorch and transformers live in a new
`export` dependency group, ONNX Runtime in the service's real dependencies. `tools/licence_gate.py`
now derives the **shipped** Python set from the service's own `pyproject.toml` — `dependencies`
ship, dependency groups do not — and holds shipped packages to the commercial bar while holding
build-time tooling to the looser `development_only` one. If it cannot work out what ships, it treats
everything as shipped.

**Why:** the export needs the checkpoint's `config.json` for the ADE20K label map and its
`preprocessor_config.json` for the normalisation constants. Reading those instead of transcribing
them is what stops the five class indices being folklore in our source — but only if they are pinned
at the same reviewed revision as the weights, which the single-`file` schema could not express.
Listing them as separate `[[model]]` entries was the alternative and was rejected: it duplicates the
licence fields and makes the gate report configuration files as though they were weights.

Adding torch then failed the gate, and the failure was correct in form and wrong in substance: the
gate inspects whichever environment it runs in, so it judged a converter that never leaves a
developer's machine by the standard for a binary shipped to dealerships. It already drew exactly
that distinction for weights via `shipped`. Two of the four failures turned out not to be policy at
all — protobuf writes BSD-3-Clause as "3-Clause BSD License", transformers writes Apache-2.0 as
"Apache 2.0 License" — and those are now spellings the normaliser knows, which mattered because
protobuf arrives through onnxruntime and genuinely ships.

**Consequence:** `python tools/fetch_models.py` fetches six files, not two. Anything added to
`dependencies` is held to the shipping bar automatically, so the way to make a licence question go
away is still to move the dependency, not to widen the policy. BSL-1.0 and CNRI-Python are listed
`development_only`; if either ever needs to ship, that is a deliberate second decision.

---

## 23. SAM 2 is exported as two graphs, and every export is checked against PyTorch

**Ticket:** #6 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-20

**Decided:** `tools/export_onnx.py` writes three graphs — `semantic.onnx`, `sam2-encoder.onnx`,
`sam2-decoder.onnx` — with the opset pinned at 18, a fixed 32-slot prompt input padded with SAM's
`-1` label, and a `runtime.json` sidecar per model carrying the input size, normalisation constants
and (for the semantic model) the class indices. Every graph is run against its PyTorch original on a
seeded pseudo-photo and must match within a tolerance.

**Why:** splitting SAM 2 at the encoder/decoder seam follows the cost. The encode depends only on
the photo and is the expensive half — measured at 2.0 s against 120 ms for a decode — so a design
that re-encoded per prompt set would have made trying prompts unaffordable, and #7 has to decode
once per Wall Plane against the same features. A fixed prompt width was chosen over a dynamic axis
because a static graph is faster in ONNX Runtime and SAM's padding convention already expresses "a
variable number of prompts" inside a fixed slot.

The parity check earns its place twice over. It is the only thing standing between us and an export
that runs while computing something else, which would surface as inexplicably poor mattes rather
than as an error. And the *input* to that check matters: the first version fed zeros, which takes
the same path through every branch and can make a broken export look faithful. It now feeds a seeded
pseudo-photo, and the decoder's two trace prompts are off-centre with one negative, so a transposed
coordinate or an ignored second point cannot pass.

**Consequence:** the shipped runtime needs `onnxruntime` and the sidecars, never transformers. The
slow lane runs the export only on a cache miss and includes the exporter's hash in the cache key,
because the graphs live in the same directory as the weights and a key tracking only the weights
would restore graphs built by an older exporter.

---

## 24. Model files are checked at boot when packaged, warmed after the handshake, on one CPU path

**Ticket:** #6 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-20

**Decided:** `service.main()` verifies the model files before announcing the port, but a missing set
is fatal **only when `SPECTRAPAINT_MODELS_DIR` is set**. Warming then runs on a daemon thread after
the handshake. Sessions are loaded once per process behind a lock, with `CPUExecutionProvider` named
explicitly.

**Why:** the spec is clear that model failures should surface at boot rather than mid-consultation,
and the Catalogue already sets that pattern. Applied literally it would have broken the fast lane:
`test_launch` spawns the real service on both operating systems and there are no weights there,
so every launch test would have had to move to the slow lane — losing exactly the Windows
process-teardown coverage that matrix exists for (§9c). The environment variable is the honest
discriminator: Electron sets it in a packaged app, so absence there is a broken install and the
service stops, while a source checkout that has not run the export yet still boots and fails
per-photo in plain language.

Warming after the handshake rather than before it means the load overlaps the boot screen Electron
is already showing, instead of delaying the port announcement — and the thirty-second per-photo
budget never contains a model load. Loading a session is not the whole cost: ONNX Runtime picks
kernels on the first run, so warming runs one throwaway inference through each graph.

**Consequence:** the tier table design-decisions.md §3 leaves open is still open, and this ticket
does not close it. One CPU path is implemented, which is what "assume a CPU-only shipping build"
asks for; the measurements now in `spikes/latency/RESULTS.md` are the input the tier table needs.

---

## 25. SAM 2 is constrained by eroded positives and exclusion-only negatives, sampled on a grid

**Ticket:** #6 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-20

**Decided:** positive prompts are sampled from the semantic wall region **after eroding it** by 1.5%
of the photo's shorter side; negatives come **only** from the four named exclusion classes, never
from "everywhere that is not wall"; and both are sampled on a deterministic grid, 20 positive and up
to 12 negative.

**Why:** each rule is a failure avoided. The semantic boundary is a quarter-resolution staircase
upsampled, so a point sampled near it may be sitting on ceiling — and one positive point in the
wrong region makes SAM 2 grow the mask into that region, which nothing downstream can undo. Marking
everything non-wall as negative would include the unlabelled furniture that ADE20K has no class
for, teaching SAM 2 that the wall stops at the sofa's top edge rather than continuing behind it;
leaving it unclaimed says the truthful thing, which is that we do not know. And a deterministic grid
rather than random sampling means the same photo yields the same matte, without which the slow
lane's accuracy tests could not exist at all.

**Consequence:** `MAX_PROMPT_POINTS` in the exporter and the `_POSITIVE_SHARE` split here are the
two numbers to revisit if mattes come back poor; both are named constants for that reason. #7 will
prompt per plane against the same encoder output.

---

## 26. Alpha means coverage, and softness is confined to a spatial band

**Ticket:** #6 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-20

**Decided:** the finished matte has three zones. Where the semantic pass is confident (≥ 0.75) the
pixel is wall, restored to alpha **1.0**; where it named an exclusion the pixel is **0.0**; and only
a ring around the matte's own 0.5 crossing — found by dilating and eroding, not by inspecting alpha
values — carries a fractional value, produced by a guided filter using the photo's luminance as the
guide.

**Why:** two bugs found by running the pipeline rather than by reading it, both worth recording
because both looked reasonable in code.

The first: the shadow restore originally set alpha to the model's *confidence*. Confidence and
coverage are different quantities — a pixel the model is 90% sure about is all wall, not
nine-tenths of a wall — and spending one as the other left a matte whose maximum was 0.904, so the
render could never fully paint the wall it had found.

The second: the boundary band was originally "pixels whose alpha looks intermediate". For a mask the
refiner is unsure about everywhere, that selects the whole photo, hands the guided filter the
interior, and lets the photo's texture modulate coverage — painting faint shadows of the furniture
into the alpha itself. A spatial ring cannot do that. Confining softness to where a wall meets a
non-wall is also what the spec's corner rule asks for, and it is what makes the matte usable when
the refiner returns a mask it is unsure of everywhere.

**Consequence:** the interior is exactly 1.0, which is what lets the Base Colour estimate look for
"fully-opaque pixels" and mean it. #7 inherits the rule that a wall-to-wall corner is crisp: two
planes meeting must not both put a soft edge on the same pixels, or the composite runs twice and
leaves a dark seam.

---

## 27. The Base Colour is measured inside the matte, near the 90th luminance percentile

**Ticket:** #6 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-20

**Decided:** `estimate_base_colour` now **requires** a matte, and implements the spec's derivation:
fully-opaque pixels eroded inward by 1% of the shorter side, ranked by luminance, taken from an
85th–90th percentile band, averaged as whole RGB pixels. It falls back to un-eroded opaque pixels,
then to the most-covered pixels, when a matte has no interior.

**Why:** this replaces the interior-median stub §17 recorded, and the alternative — leaving `alpha`
optional so old callers kept working — was rejected: a caller with no matte does not have a wall,
and a quiet fallback to a whole-photo statistic would render the sofa's colour while looking exactly
like a working render. The percentile band rather than a single percentile is because a single one
selects a handful of pixels on a small matte, and a mean of five pixels is noise. The fallbacks exist
because a wall visible only in slivers between furniture is a poor wall, not a reason to refuse a
render the Dealer asked for (conventions.md §5).

**Consequence:** three tests that pinned the interior median were replaced by six that pin the
derivation — measured inside the matte, ignoring the matte's own edge, the wall in full light rather
than its average, and the cast preserved. Per-*group* Base Colour, for planes sharing existing
paint, is #7's; with one plane the distinction cannot yet be expressed.

---

## 28. The planes endpoint lists geometry; the matte is a second route, as a PNG

**Ticket:** #6 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-20

**Decided:** `GET /sessions/{id}/planes` returns JSON — plane ids, coverage, bounding box, photo
dimensions — and `GET /sessions/{id}/planes/{plane_id}/matte` returns the Alpha Matte as an 8-bit
greyscale PNG. A fourth Electron bridge (`walls-bridge.ts`) fetches both and hands the renderer a
data URL.

**Why:** the spec's contract lists `/planes` and says nothing about how a matte crosses the wire,
so this was ours to settle. Inlining it as base64 would add roughly a third of a megabyte per plane,
make the cheap question ("what planes are there?") pay for the expensive answer, and force the UI to
unpack a string before it could draw. Greyscale rather than RGBA because the matte *is* one channel
and what colour to draw it in is the UI's decision (ui-guidelines.md). The bridge exists for the
same reason §20's did: the generic request bridge reads a JSON body, so a PNG reaches it as
`body: null`.

**Consequence:** renders now look a plane up by id against the planes *this photo has* rather than
against a constant, so the check keeps working when #7 finds three. The id value is unchanged, so the
copy in `render-bridge.ts` that §20 warns about still matches — but that duplication is still there
and #7 should remove it by having the renderer name the plane.

---

## 29. The fast lane keeps the contract tests, with preparation injected

**Ticket:** #6 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-20

**Decided:** the seam 1 tests that need a prepared photo supply their own preparation through
`create_app(preparation_stages=...)`, with the centred-rectangle matte that used to be production's
stub now living in `tests/api/conftest.py`. The real pipeline is exercised over the same contract by
`tests/api/test_walls.py`, marked `models`, against hand-labelled photographs in
`data/fixtures/rooms/` — and when those photographs are absent, those tests **skip with a reason**.

**Why:** conventions.md §6 says not to mock the model adapters, and this does not: nothing stands in
for the pipeline's interface, so its absence cannot go unnoticed. What is replaced is the *input* —
"assume a photo was prepared and this is its matte" — through the injection point `preparation.py`
already documented and #4's stream tests already used. The alternative was to mark every
upload-and-render test `models`, which would have moved the render contract's coverage out of the
fast lane and off Windows entirely. Skipping rather than passing when fixtures are absent is the
other half: a green lane that checked nothing is worse than a red one, because it is believed.

**Consequence:** the accuracy thresholds (IoU ≥ 0.60, shadowed-wall recall ≥ 0.80, non-wall coverage
≤ 0.20) are regression floors, not the measured evaluation §10 requires — and they are unverified
against real rooms until the fixtures exist, which is difficulty 9.

---

## 30. Wall Planes are a hard vertical partition of the wall matte, found by shading valley + vertical edge

**Ticket:** #7 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-21

**Decided:** `spectrapaint/segmentation/split.py` turns the single wall Alpha Matte from `matte.wall_alpha` into
one to three Wall Planes by a hard vertical cut. The detector is deliberately **valley-primary**:

* per-column median luminance `valley[x] = median(L[interior[:,x]])` — a corner is a dark valley where each
  wall darkens toward it (shading-gradient reversal, spec). A valley is a local minimum whose depth
  `max_median(neighbourhood) - valley` exceeds `0.030`.
* per-column vertical-edge energy `energy[x] = mean |dL/dx| over interior rows` — the corner's line and the
  vanishing-line cue. Energy is measured on **raw** (unsmoothed) columns; a 2%-width box smooth would dilute a
  1-2 px corner 25× (Room 2: raw 0.0238 → smoothed 0.0070, below the old `_ENERGY_FLOOR 0.015`).

A column becomes a seam only when a valley **and** a supporting edge coincide, or when a strong step
(`|median_left - median_right| ≥ 0.09`) coincides with an edge. The strongest valleys/edges are ranked by
`depth*2.0` (valley) or `energy + depth*0.5 + step*0.3` and suppressed by `0.18·wall_width` separation. Striped
wallpaper (many repeating valleys/edges) is rejected when valley count would otherwise be >4.

Partition is hard: `plane_alpha = original_coverage * hard_mask[:, left:right]` — soft only where wall meets
non-wall (the original matte's feather), crisp where wall meets wall. Every wall pixel belongs to exactly one
plane, so `sum(planes) == original` and no pixel is composited twice (no dark seam). Degenerate slivers
(`coverage < 0.005` or `< height*2` interior pixels) are **merged** into a neighbour rather than deleted, so no
wall pixels are lost; a sliver below `MINIMUM_WALL_FRACTION 0.02` is merged and the partition check in
`walls.planes_from` degrades to a single plane with a warning rather than an `assert` (which is stripped under
`-O` and would surface as a 500).

`walls.planes_from` now validates the partition and re-normalises ids to `wall_plane_1..N` left-to-right.
`render.engine.render_many` keeps the maths in `render/` (conventions §3): per-plane `Base Colour` measured
inside each plane's matte, per-plane Light Map, composite in linear RGB in left-to-right order, single
`sRGB` encode at the end. `api/renders.py` builds `plane_targets = [(alpha, target_shade)]` and calls it; the
`assignments` map already expressed an Accent Wall, now with 2-3 keys. `apps/desktop/src/render-bridge.ts`
discovers plane ids via `GET /planes` and assigns the Shade to every plane (single-Shade tap) or posts a
per-plane map (Accent Wall); the `wall_plane_1` literal is now a fallback only.

**Why:** the first implementation measured only `mean |dL/dx|` and compared a heavily smoothed absolute to
`0.015`, with a `15%` side-fraction margin. On two real rooms (678×452 three-plane studio, 1280×720 phone
photo with corner at x≈80) it returned one plane: the smoothing diluted the true corner below the floor, and
the margin excluded return walls that are `≈4%` of width by construction — photographing a room *is* narrow
strips at the frame edge. Lowering the floor to `0.003` produced wardrobe and curtain edges (Room 1: 138, 348;
Room 2: 218, 701) because `|dL/dx|` alone cannot tell a corner from a curtain. The valley is what separates them,
so it was promoted from veto to primary. The side-fraction was replaced by a minimum plane **area**
(`0.04` of wall area and `0.03` width) — a texture line near the edge leaves no material wall on one side,
a real corner does.

**Consequence:** seams are full-height vertical cuts only; a corner that stops at a doorway head is not
representable — acceptable for V1 and stated as a limit. `PreparedPhoto.wall_alpha` (single-plane convenience)
is now dead and will be removed when callers have migrated. `_MAX_SEAMS = 2` caps at three planes, the
typical 2-3 the spec names; more would be further slivers, not walls.
