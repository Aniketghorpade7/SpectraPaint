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

## 30. Fixture labels are polygons in a tool, and a plane is coloured only where the wall is certain

**Ticket:** #30 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-21

**Decided:** the three room fixtures are labelled by polygons held in
`tools/fixtures/label_rooms.py`, which renders `<name>.wall.png` and `<name>.planes.png`. The tool
grows a seven-pixel "do not count this pixel" band along every traced boundary, and occlusions too
tangled to trace — hanging clothes, a suitcase, bedding — are marked uncertain wholesale.
`<name>.planes.png` colours a plane only where `<name>.wall.png` is white, and planes are ordered
left to right by centroid, matching the order the service numbers `wall_plane_N` in.

**Why:** the README suggests painting the mask in an editor, which is fine and was not forbidden —
polygons were chosen because a diff of them says what somebody decided about a photograph, where a
diff of a PNG says nothing at all, and these labels will be argued about as the segmentation tickets
land. The automatic band is the honest part: a line drawn by eye over a curtain fold is not accurate
to the pixel, and the README is right that a wrong label is worse than an absent one. Colouring
planes only inside certain wall follows from the same rule — a pixel nobody can call wall cannot be
assigned to a plane either.

`windows-with-curtains.jpg` is labelled as **one** plane, though a return wall is arguably visible at
the left edge: it is a sliver perhaps 90 px wide and almost entirely behind a curtain, so calling it
a plane would assert something the photograph cannot support. Recorded in
`data/fixtures/rooms/origin.md` beside the consent rows.

**Consequence:** the labels are cheap to correct — edit a polygon, re-run the tool — and expensive to
correct silently, which is the right way round. A fourth photograph was left out because its
provenance was unknown; the licence gate and `origin.md` both need an answer that "found on the
internet" does not give.

---

## 31. The wall IoU counts only the pixels the label claims

**Ticket:** #30 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-21

**Decided:** `test_the_wall_found_is_the_wall_that_is_there` now restricts both sides of the IoU to
pixels the label calls wall or not-wall, ignoring the mid-grey "unsure" ones. The two accuracy tests
also union every Wall Plane's matte instead of taking `planes[0]`, and `rooms()` no longer collects
`*.planes.png` as though it were a photograph.

**Why:** the README promises mid-grey means "do not count this pixel" and the IoU kept half of that
promise — an unsure pixel could never enter the intersection, but a matte covering one still grew the
union. That is backwards: an honest grey band cost IoU, so a careful labeller scored worse than one
who guessed a hard edge and got it wrong. Worth 0.07–0.14 of IoU on these fixtures (0.88 → 0.95,
0.66 → 0.77, 0.23 → 0.37). It changes what the test measures, not how hard it is to pass: the
leakage assertion still counts every labelled non-wall pixel, so a matte that paints a door is caught
there, where it belongs.

Unioning the planes is not a preference. `<name>.wall.png` labels *the wall*, and one plane of three
cannot overlap the whole of it — the test would have failed for a reason unrelated to whether the
wall was found, the moment #7 lands.

**Consequence:** the plane-count and seam-position assertions that `<name>.planes.png` exists for are
**not** in this ticket. They fail on `main` today because splitting is #7's unmerged work, and a test
asserting a feature that does not exist does not belong on the default branch; they land with #29,
which is where the behaviour lands. `plane_labelled_rooms()` and `planes_label_path()` are here
waiting for them.

---

## 32. The accuracy tests assert what was measured, and ratchet towards what was wanted

**Ticket:** #30 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-21

**Decided:** `MINIMUM_WALL_IOU` (0.60) and `MAXIMUM_NON_WALL_COVERAGE` (0.20) are read as **targets**.
Each fixture is held to the value recorded in `data/fixtures/rooms/measured.toml` until it reaches
its target, with 0.02 of slack for a graph rebuild or a Pillow resize. Only shortfalls are recorded:
a metric that meets its target has no entry, and three things fail the lane — a value going the wrong
way, a value crossing its target with an entry still present, and a value improving by more than 0.05
past its entry. The ratchet turns one way only, and the file is meant to empty as #31 closes.

**Why:** the floors were written before a real photograph existed and the first three say the
pipeline does not clear two of them (difficulty 12). Four ways out were weighed. Fixing the cause
first is right and is not available: the leakage is a checkpoint that labels a door `wall` at 0.97
confidence, so it needs the handoff document's custom model, not this ticket. Merging red would put
the fixtures on `main` at the cost of a permanently red lane, which would mean #29's own slow lane
inherits three failures and new breakage becomes indistinguishable from old — spending most of the
value of landing fixtures early. `xfail` would go green while noticing nothing if the numbers got
worse. Relaxing the constants to fit would delete the record of what was wanted.

This is deliberately not the thing `conventions.md` §7b forbids. That forbids **re-recording** a
baseline to get past a regression it detected; here no baseline existed, this is the first
measurement, and the shortfall is recorded in the file, in difficulty 12 and in #31 rather than
smoothed away. The honesty rests on the ratchet: without it, a baseline file is just a floor nobody
raises.

**Consequence:** the lane is green and means something — twelve tests, and a matte that starts
painting more of a door than it does today fails. What it does *not* say is that wall detection is
good enough; `measured.toml` is the standing record that on two of three real rooms it is not.

---

## 33. Wall Planes are a hard vertical partition of the wall matte, found by shading valley + vertical edge

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

---

## 34. A seam is where two cues agree, and one seam is the most a photograph is allowed

**Ticket:** #7 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-21

**Decided:** `_find_seams` computes three cue signals over the columns of the eroded wall interior —
edge energy, valley depth, and shading-gradient **reversal** (the smoothed median's slope to the
right of a column minus its slope to the left) — takes the strongest few non-maximum-suppressed
peaks of each, groups peaks that land within 3% of the width of one another, and calls a group a
corner when **two or more distinct cues** are in it. The seam is placed at the group's energy peak
where it has one. `_MAX_SEAMS` drops from 2 to **1**.

This supersedes the valley-primary ranking in decision 33, which superseded the energy-primary one
in the first version of this ticket. The partition, the merge of sliver planes and the area/width
viability rules from decision 33 are unchanged.

**Why:** decision 33's version did not split a real corner — not the unoccluded one either — and the
cause was not a threshold. Its guard against striped wallpaper rejects a photograph outright above
four valley candidates, and a real median-luminance profile has ten or twenty local minima because
nothing suppressed non-maximal ones before the count (difficulty 15). Suppression alone was not
enough: measured on the fixtures, **no single cue survives a photograph**. On `empty-corner` the
strongest column energy in the whole wall is 2 px from the corner while no column near it is a clean
median minimum; on `corner-with-clothesline` the deepest valley is the corner but the strongest
reversal is a curtain fold 300 px away; on `windows-with-curtains` all three cues have a confident
strongest column and they disagree.

Agreement is what the ticket asked for in the first place — "three things that coincide" — and it is
the only rule of the several tried that lands on both labelled corners (9 px and 22 px, against a
tolerance of 2% of the width) while leaving a wall with no second plane alone. Reversal is measured
as slopes over a window rather than as a single dark column because a corner's valley is rounded
over tens of pixels: the darkest column moves photo to photo, the slopes either side do not.

**One seam, not two,** because on all three fixtures the second-ranked group is a curtain fold or a
stretch of wall the matte wrongly claimed (#31), never a third wall. Rooms with three visible walls
exist and this is the number to raise — after there are fixtures with three labelled planes to raise
it against. Raising it on this evidence would split a two-wall room into three.

**Consequence:** three of the four plane tests in `tests/api/test_walls.py` went from failing to
passing, and `test_a_real_photo_yields_one_wall_plane_with_a_soft_matte` had to be renamed and
loosened: its `len(described) == 1` was correct only while #6 owned the answer, and the count now
belongs to the labels. The floors kept (`_ENERGY_FLOOR`, `_VALLEY_DEPTH_FLOOR`, `_REVERSAL_FLOOR`)
exist for the flat wall, whose signals are all zero and which must stay one plane.

Worth naming plainly: these numbers are tuned against **two** labelled corners. That is enough to
stop the algorithm being obviously wrong and not enough to call it right. #30's fixture set is the
thing to grow before trusting any of them further.

---

## 35. An Accent Wall costs one extra tap, and painting the whole room still costs none

**Ticket:** #7 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-22

**Decided:** with more than one Wall Plane on screen, each wall carries a chooser chip. Tapping a
wall selects it and the next Shade lands only there; tapping the selected wall again goes back to
painting every wall. Tapping a Shade with nothing selected paints them all, which is what the surface
did before. The state — which wall is selected, and the Shade each wall carries — lives in
`apps/ui/src/consultation/accent.ts` as pure functions, and the request carries a bare Shade Code
while every wall matches and a per-plane map once they differ.

**Why:** the ticket's last criterion is two planes carrying two Shades at once, and until now the
service and the Electron bridge could both express it while the renderer could not — so the Dealer,
who the criterion is about, could not produce an Accent Wall. The tap budget is three
(ui-guidelines.md), so the common case had to stay where it was: one Shade over the whole room is
still a single tap, and the accent case is two. A toggle rather than a separate "all walls" control
because deselecting is then the same gesture as selecting, and a confirmation step is a tap the
budget cannot afford.

The chooser is a chip over each wall rather than the wash itself, and that is not cosmetic: a CSS
mask clips what is *painted*, not what is *clickable*, so two full-size masked buttons would overlap
and the upper one would swallow every tap meant for the lower. The chip is a real `<button>` with
`aria-pressed`, positioned from the plane's own bounding box, at the 44px minimum.

A bare Shade Code is sent while the walls match, rather than always sending a map: the bridge then
discovers the plane ids itself, so a photo whose walls were re-split between two taps cannot produce
a request naming a plane that no longer exists. Only walls the Dealer has actually chosen a Shade for
appear in the map — an unpainted wall stays as photographed rather than being quietly given
somebody else's Shade.

**Consequence:** the logic is tested where conventions §6 puts it. `accent.ts` is pure, so it is
vitest's (14 tests); the wire shape is the bridge's own test ("posts a per-plane map for an Accent
Wall"); and two Shades over two planes in one request is seam 1's, against a two-plane stub added to
`tests/api/conftest.py`. Nothing needed a DOM test.


## 37. A Consultation is saved the moment its photo is uploaded, and preparation is stored on first use

**Ticket:** #11 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-08-22

**Decided:** persistence is a `Store` (`spectrapaint/storage/`) — one SQLite database plus the images
as files beside it, in the per-user application data directory (`platformdirs`, overridable with
`SPECTRAPAINT_STORAGE_DIR`). `create_app(store=...)` takes it as an argument like every other
dependency; production builds one at boot in `service.py`. Uploading writes the Consultation row and
the original photo bytes immediately, so there is no save button to forget. The prepared photo (at
preview scale, lossless PNG) and one Alpha Matte PNG per Wall Plane are written the first time any
request reads the photo — the gate every render passes through — because that pair is exactly what a
reopened Consultation needs in order to skip preparation. Every render is saved before its response
is sent: the PNG bytes plus execution profile, mode, assignments, resolved Lab values, and Catalogue
identity *and* version. The consultation id is the first session id; reopening mints a fresh live
session id mapped back onto it.

**Why:** auto-save has to be structural, not a UI habit — "the Dealer cannot lose work by forgetting
to press something" is only true if saving happens below the point where forgetting lives. Storing
the prepared artifacts rather than re-running preparation on reopen is what makes the "try another
Shade skips preparation" criterion honest: the pipeline runs once per photo, ever. Recording resolved
Lab values alongside shade codes means a saved render can still be interpreted after a Catalogue
swap, which is the same reason identity and version are stamped.

Two deliberate scope notes. The stored photo is at preview scale, not camera resolution — full-
resolution rendering does not exist yet (preparation caps at 1280px), so "full-resolution" today
means *lossless at the resolution actually rendered*; the original upload bytes are kept untouched
for when that ticket lands. And "execution profile" is recorded but fixed to `preview` — V1 has no
faster-vs-better-quality choice, so inventing one here would be a feature smuggled into a storage
ticket; the column exists so renders saved before profiles arrive still say what made them.

The default Bundle is structural — `bundles.is_default` (migrated from the legacy name match;
if the legacy default was renamed, the oldest bundle is promoted), with server-side 409
`default_bundle_protected` on rename/delete and an `RLock` around the shared sqlite connection
(WAL + `PRAGMA foreign_keys=ON`, reparent before delete). Deleting a Bundle moves its
Consultations to that default Bundle rather than deleting them: nothing is deleted automatically,
and even the Dealer's explicit delete of a grouping is not a decision that the work inside stops
existing. The wire carries `is_default` as `0`/`1` (not a bool/string), and the UI files new
Consultations into the open Bundle via `POST /bundles/{id}/consultations` and offers Move/Undo
(undo-by-recreate, with per-consultation error handling).

**Consequence:** seam 1 covers the whole surface against a throwaway store (`test_library.py`,
15 tests): auto-save on upload, bundle CRUD without data loss, byte-for-byte replay of stored
renders, metadata completeness, reopen skipping preparation (counted by how often a photo enters the
pipeline), and the clean 409 for a Consultation closed before preparation finished. The contract test
in `test_sessions.py` pins the new endpoints so none can appear silently.
---

## 36. Base Colour is grouped by paint, and the room's light tints the Shade

**Ticket:** #8 · **Contributor:** Prasad Kathe (code written by an agent) · **Date:** 2026-08-22

**Decided:** `spectrapaint/render/engine.py` estimates one Base Colour per **group** of Wall Planes sharing the same existing paint, never per plane. Grouping is by chromatic **tint** (`base / luma`, BT.709) distance `< _GROUP_TINT_THRESHOLD 0.08` — brightness removed so two whites at different brightness (same paint, different shading) keep the same tint and share one base, while an off-white vs pink Accent Wall (`corner-with-clothesline.jpg`) splits at `0.32`. A group of one reuses its single `estimate_base_colour` (fully-opaque `>=0.99` eroded `1%` of shorter side, ranked by luminance `90th±5th` percentile, `mean RGB` over whole pixels); a group of several merges its plane mattes (`clip(sum(alphas),0,1)`) and estimates once, so the wall-to-wall seam stays interior rather than eroded. `render_many` then derives one Light Map per group and composites in linear RGB in left-to-right order, single `encode_srgb` at the end.

Realistic mode multiplies `light_tint = median(interior)/luma` (`estimate_light_tint`, 5% edge band excluded, luma-normalised so grey is `(1,1,1)`); True Colour uses `_NEUTRAL_TINT`. `POST /sessions/{id}/renders` defaults `mode=realistic`, validates `"realistic" | "true_colour"` as `422`, and returns `X-SpectraPaint-Render-Mode` on every `201 PNG` so a reopened Consultation can reproduce what was shown and the realism measurement can select `true_colour`. `apps/ui/src/consultation/useConsultation.ts` holds `renderMode` (`realistic` default) and `toggleRenderMode` — repainting the current `assignments` in the new mode without a new Shade tap — and `ConsultationSurface` exposes it as `True Colour mode / Realistic mode` (`aria-pressed`).

**Why:** the earlier `render_many` divided each plane by its own base, so `light_map` peaked at `1.0` per plane and the room flattened — the exact failure §4 exists to prevent. Comparing raw bases would repeat it: two planes of the same white at `0.8` vs `0.5` shading yield bases `0.44` vs `0.27` (distance `0.22`) and would split. Tint removes shading scale, so same paint groups and different paint splits on the three fixtures: `empty-corner.jpg` tint distance `0.015` → group, `corner-with-clothesline.jpg` `0.324` → split, `windows-with-curtains.jpg` (single plane, blown band at top avoided by `85–90` band, not `100%`) → neutral tint. Per-channel percentiles were rejected for the same reason the spec states: three different pixel sets would neutralise the wall's cast, which is the one thing the estimate must capture.

**Consequence:** the threshold is a tuned constant against two labelled corners — enough to stop the algorithm being obviously wrong, not enough to call it right; growing `data/fixtures/rooms/` is the lever to tighten it. A mis-group is silent (wrong brightness ratio or a two-toned room rendered as one), so `measured.toml` remains the place to catch it. The header satisfies "recorded on every render" for the HTTP contract; the persisted stamp belongs to storage (`#11` `Bundle → Render`), where the same field will be written alongside catalogue identity and execution profile.


---

## 37. The Light Map blends toward brightness as the wall saturates and is quieted by measured noise

**Ticket:** #9 · **Contributor:** Prasad Kathe (code written by an agent) · **Date:** 2026-08-25

**Decided:** `spectrapaint/render/engine.py:light_map_of` now takes an optional `alpha` matte and carries three refinements that all degrade to the plain `linear / base` division on clean, neutral input. (a) **Saturation blend** — saturation `(max-min)/max` mapped through `[_SATURATION_BLEND_START 0.20, _SATURATION_BLEND_END 0.60]` to a weight that blends the three-channel division toward a single-brightness `luma(photo)/luma(base)` division. (b) **Ceiling** — `clip(0, _LIGHT_MAP_CEILING 4.0)`. (c) **Noise-proportional smoothing where the wall is dark** — a global MAD high-pass sigma gates whether smoothing runs at all (`_measured_noise_sigma`); if it exceeds `_NOISE_FLOOR 0.008`, a per-region noise map (`_local_noise_sigma`) scales the global sigma by local high-frequency energy ratio, then `strength = (sigma-floor)/(0.12-floor)` is ramped by luma through `[_SMOOTHING_DARK_LUMA 0.30, _SMOOTHING_LIT_LUMA 1.15]` and folded with `alpha`, and a normalised convolution gives the local mean. `box_mean`/`guided_filter` moved from `segmentation/matte.py` to `spectrapaint/imaging.py` (engine already imported `erode` from there; the opposite direction would be a dependency in the wrong direction, conventions §3). `render_many` computes the Light Map **once per photo per Base Colour group** (not per tap), so a Shade tap is multiply–composite–encode. `spikes/latency/bench_render_loop.py` now measures the per-tap path only (Light Map is precomputed), and the import is authoritative — the gate fails loudly if the package is unavailable. Tuned against the three fixtures measured through `light_map_of` with the hand-labelled wall matte: `empty-corner` wall-wide `0.0047` sits well below the floor, `windows-with-curtains` `0.0040` naturally below (phone night-denoise), `corner-with-clothesline` neutral plane `0.0058` below, pink plane `0.017` above — the busy textured plane is the only one that crosses. Pinned by `tests/render/test_light_map_fixtures.py`.

**Why:** a saturated Base Colour has a channel near zero and division there is pure amplified noise (speckle, review item 2's runaway values); blending toward luma keeps shading while discarding the poisoned channels. The probe was `0.01` (19×19) and read shading gradients as grain, so it was narrowed to `0.004` (7×7 at fixture res) — small enough to probe grain, not shadows. The floor was `0.01` and sat above the noise real photos carry; `0.008` puts the flat-daylight control well below with margin while genuinely busy regions still cross. `LIT` was `1.00` so a pixel at 65% of full light already took half the smoothing once the floor was crossed; `1.15` gives lit texture 15% margin above `1.0` where grain rides. Alternatives rejected: measuring noise on the whole frame (curtains/windows drove the only crossing, `0.0221` off-wall vs `0.0088` wall on `corner-with-clothesline`), smoothing without a darkness ramp (would quiet well-lit stains), absolute pixel radii (fraction keeps the same physical grain size across preview vs full-res). The initial local MAD approach mistook wall texture for noise; the variance-ratio modulation preserves the global floor while allowing spatial variation.

**Consequence:** the per-tap recomputation is eliminated — Light Map is now computed once per photo per Base Colour group during preparation, so a Shade tap is back to multiply–composite–encode (~36 ms at 1280×720 vs 50–150 ms before). The gate measures this fast path and fails honestly if the package is missing. `box_mean` accumulates in float32 (integral ~5e6 on 2 MP) and hardcodes `.astype(np.float32)` — a float64 caller is downcast; pre-existing from `matte.py`. `_NOISE_MINIMUM_PIXELS 1000` guards the MAD of a sliver matte. The fixture corpus may not exercise the dark-wall criterion (night mode denoises the night fixture); see technical-difficulties.md #18.

## 38. Review fixes for #11: default Bundle flag, silent failures, and migration

**Ticket:** #11 · **Contributor:** Anamika Chauhan (code written by an agent) · **Date:** 2026-08-25

**Decided:** after review `c16f770` → `a56267f`, the library surface was made honest:
`window.prompt` replaced by inline rename; `POST /bundles/{id}/consultations` now called from
`useLibrary.placeConsultation` and from `App:startInBundle` (so a non-2xx surfaces a message, not a
silent drop), with `BundleDetail` offering New consultation in-bundle and per-consultation Move;
`openConsultation` leaves `renders` at `null` on history failure and `ConsultationHistory`'s Try
again retries the consultation rather than refetching bundles; `bundles.is_default` migrated with a
fallback that promotes the oldest bundle when the legacy default was renamed; `create_bundle`
returns `is_default` as `0`/`1`; `delete_bundle` guards only via `is_default` (reparent before
delete, `RLock` on reads+writes, `foreign_keys=ON`, dead `read_image` removed);
`SessionRegistry.delete` now clears the live mapping and keeps the persisted set per consultation;
`PreparationJob.completed` constructed via `cls([])` rather than `__new__` hand-sets; bundle delete
undo re-creates and moves back with per-call error handling and a retained `lastDeleted` on partial
failure. `storage/location.py` no longer claims the packaged Electron already sets
`SPECTRAPAINT_STORAGE_DIR` — it notes the wiring is expected in `apps/desktop` and the default is
for dev/tests. Tests: `default_bundle_protected` 409 covered, default located by `is_default`.

**Why:** the blocking points were silent failures on the exact surface the ticket exists for —
filing into a job and retrying a failed history — and a migration that preserved the name-matching
bug it was meant to fix. The wire-type and lock/read notes were integrity invariants the review
probed directly.

**Consequence:** seam 1 now asserts the invariant (`default_bundle_protected`), the migration is
idempotent and handles a renamed default, `is_default: number` is consistent across `GET`/`POST`,
and undo is best-effort with a message rather than a silent half-restore.

---

## 39. Wall corrections are three armed single-tap tools, not a second tap vocabulary layered on the photo

**Ticket:** #10 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-04

**Decided:** three explicit, mutually exclusive tools — Add, Merge, Split — each entered by tapping its own `<button>` in the consultation bar (Add always available on a ready photo; Merge only once ≥2 planes exist; Split only once ≥1 plane exists). Arming a tool suppresses the existing wall-target chips and swaps in a full-photo tap layer; the very next tap on the photo performs the correction and disarms the tool immediately — no confirmation step. Tapping an already-armed tool again disarms it, the same toggle idiom `toggleWalls`/`toggleTarget`/`toggleRenderMode` already use. When a photo has zero Wall Planes — automatic detection found none, or #10's backend change turns that from a hard failure into a soft, empty result — Add is auto-armed, so the first thing the Dealer sees is "tap where a wall is" with no extra tap to reach it. This is what makes the fallback criterion and the correction criteria one surface rather than two.

**Why:** the alternative was a bare tap on the photo meaning different things by context — empty area adds, near a plane boundary merges, inside a plane splits — which needs no arming step and is fewer taps in the common case. It was rejected on two counts. First, design-decisions.md §2: "every correction is a moment where the dealer looks incompetent in front of a customer" — an ambiguous gesture makes an accidental tap costly in exactly the setting that can least afford it. Second, a bare tap on the photo already means something: `ConsultationSurface.tsx`'s wall-chooser chips use a tap to choose which plane the next Shade paints, and overloading that same gesture with add/merge/split would make the two features indistinguishable to the code and to the Dealer's finger. An explicit tool costs one extra tap, but only while correcting — never while just browsing Shades — and it reuses a toggle the surface already teaches in three other places, so it is not a new interaction to learn, only a familiar one applied a fourth time.

**Consequence:** `ConsultationSurface.tsx` gains one small piece of state — which tool, if any, is armed — alongside `paint.target`; while a tool is armed the wall-chooser chips must not receive taps. A Dealer fixing a mistake pays one tap over the theoretical minimum, accepted because the mistake already cost the moment named above; the everyday flow — browse Shades, optionally pick an Accent Wall — is untouched by any of this.

---

## 40. Corrections are three POSTs under `/planes`, all taking the same `{x, y}` tap point, replacing the whole plane list

**Ticket:** #10 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-04

**Decided:** three endpoints join the existing `planes.py` router, all keyed off which tool (decision #39) armed the tap, and all taking the same body — `{"x": int, "y": int}`, in the prepared photo's own pixel space, the coordinate system `GET /planes`'s `photo_width`/`photo_height` already describe and the wall-chip placement math already uses:

- `POST /sessions/{id}/planes` — add. `201`, body `{"planes": [...]}` — the whole current list, one plane longer.
- `POST /sessions/{id}/planes/split` — the point must fall inside an existing plane's matte; the server resolves *which* plane by containment (the partition guarantee means it is under exactly one), retires that plane's id, and mints two. `201`.
- `POST /sessions/{id}/planes/merge` — the point must land near an inter-plane seam; the server resolves which two planes it separates and unions their already-disjoint mattes into one, keeping the id of whichever source plane had the larger coverage. `200` — nothing is minted, one id is retired.

A point that fails its endpoint's precondition (already-covered for add, not-covered for split, not-near-a-seam for merge) is `422 malformed_request` naming the right tool instead — "That's already part of a wall — try Split instead," and its mirror — never a silent no-op.

**Why one body shape:** the Dealer's gesture is the same tap point regardless of tool; the armed tool already supplies the intent (decision #39), so asking the client to also resolve and send a `plane_id` would duplicate geometry the server holds authoritatively (the real matte arrays) using only what the client has (a decoded PNG it would have to re-inspect to derive the same answer). **Why three routes rather than one discriminated body:** `renders.py`'s `mode` field is a precedent for a discriminator, but it distinguishes two views of the same action; add/merge/split are three mutations with different preconditions and different response codes, and this codebase already separates concerns by file (`planes.py` / `renders.py` / `sessions.py`) rather than by field — three small request models cost less than one union type plus per-arm validation messages. **Why plane ids are stable across corrections, unlike the automatic splitter's `wall_plane_1..N` renumbering:** `useConsultation.ts` keys `Assignments` by plane id. Renumbering every plane after each correction — the way `walls.planes_from` renumbers the whole set after computing it in one pass — would silently move a Shade the Dealer already chose onto a different wall. Only the plane(s) an operation actually changes get a new id; merge keeps a *source* id rather than minting a third precisely so a Shade already assigned to the surviving id keeps working with no special case in `useConsultation.ts`.

**Consequence:** `renders.py` and `planes.py` must both read a session's *current* plane list rather than `PreparedPhoto.planes` directly, which is the mutable-state piece the backend work still has to add. A merge dropping one of two ids leaves any assignment keyed to the retired id as inert dead data — harmless, since `isTargeted`/`toggleTarget` simply stop matching an id no longer present in `walls.planes`, the same tolerance `nextAssignments` already has for an unpainted wall. The one real coupling to watch: the `{x, y}` space is tied to `photo_width`/`photo_height` as prepared today; if a later ticket changes what those mean (full-resolution export), all three endpoints and `ConsultationSurface.tsx`'s chip-placement math have to move together.

---

## 41. The three backend foundations for #10: a non-fatal `NoWallFound`, a split SAM 2 encode/decode, and current-planes read through `require_photo`

**Ticket:** #10 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-04

**Decided:** three pieces, landed together because each is small and the third depends on reading through a `PreparedPhoto` the first two changed the meaning of.

1. **`NoWallFound` no longer fails the session.** `build_preparation_stages`'s `look_at_the_room` and `find_the_edges` each catch it locally and record `workspace.note`; the job still reaches `done` with `PreparedPhoto.planes == ()`. `MESSAGE_NO_WALL_FOUND` (`segmentation/walls.py`) is reworded to name the Add tool rather than dead-end on "try another photo," since it is now the note on a ready, tappable consultation rather than a terminal failure message. `GET /sessions/{id}/planes` gained a `note` field alongside `planes`, `null` except in this case.
2. **`matte.refiner_alpha` is split into `encode_photo` (the SAM 2 encoder, run once) and `decode_alpha` (the decoder, cheap, rerunnable against the same `RefinerFeatures`)**, exactly the seam `runtime/graphs.py`'s own docstring anticipated for "ticket #7" and #7 never used. `refiner_alpha` itself is kept, now a thin composition of the two, for the one caller (a future direct test, or a caller with nothing to hold onto) that has no reason to keep the features. `walls.planes_from` takes `features` as a parameter instead of computing it, so preparation can hold onto what it already paid for.
3. **`PreparationJob` treats its own cached `PreparedPhoto` as the session's live record, not a frozen snapshot.** `replace_planes()`/`cache_features()` mutate it in place — `self._result = dataclasses.replace(self._result, ...)`, under the job's existing lock — so `job.photo()` (and therefore `require_photo`) always returns the *current* state with no second field to keep in sync with it. `sessions.py` also gained `require_job()`, the same session lookup `require_photo` already does, exposed on its own for a route that needs to write afterwards. Nothing calls `replace_planes`/`cache_features` yet in this step — no correction endpoint existed until #42 — but `planes.py` and `renders.py` needed no further change when one arrived, because both already read planes through `require_photo`.

**Why:** each is exactly what decisions #39 and #40 already committed to building; this entry is the implementation record, not a new argument. One thing decision #40 did *not* settle and this step had to: whether `encode_photo` runs unconditionally during preparation, so every session — including a fully empty one — has cached features ready for an eventual Add tap. It does not. See difficulty 21: encoding unconditionally fed SAM 2's exported graph a genuinely degenerate photo whenever the semantic pass found nothing at all, and crashed ONNX Runtime hard enough to abort the process, not just fail a test. `find_the_edges` now encodes only when `wall_regions` succeeded — the same condition that already gated calling SAM 2 at all before this ticket — and a session where the semantic pass found nothing leaves `PreparedPhoto.features` as `None`. This is a real, narrower claim than #40 implied: the Add tap on such a session pays a ~2s encode itself, once, on demand, rather than never paying it during preparation. Every other correction path (merge, split, and Add on a session that *does* have a cached wall region) still gets the zero-cost reuse #40 described.

**Consequence:** `PreparedPhoto.features` is `Optional`, and any correction endpoint reading it must encode on demand when it is `None` rather than assume it is always present — the exact assumption difficulty 21 shows is unsafe. The dead `PreparedPhoto.wall_alpha` property (`self.planes[0].alpha`, superseded by #7 per its own docstring, and never called from anywhere in the tree) was deleted rather than left as a latent crash on an empty `planes` tuple. New fast-lane coverage lives in `tests/api/test_planes.py`, using a `no_wall_found_preparation_stages` helper in `tests/api/conftest.py` that constructs the empty-planes, noted `PreparedPhoto` directly — the real pipeline's own path into that state (`wall_regions`/`planes_from` actually raising `NoWallFound`) still has no fixture to exercise it against, the same gap the ticket names for `data/fixtures/rooms/`.

---

## 42. Add, Split and Merge, as `segmentation/corrections.py` and three routes on `planes.py`

**Ticket:** #10 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-04

**Decided:** `segmentation/corrections.py` implements decisions #39/#40 exactly as specified there — `add_plane`, `split_plane`, `merge_planes`, a `CorrectionRefused` exception hierarchy carrying the Dealer-facing message per precondition, `_next_plane_id` (tracks the highest `wall_plane_N` suffix in use, so retired-and-reminted ids never collide), and `order_left_to_right` (re-establishes the left-to-right list order a correction disturbs, since `apps/ui/src/consultation/accent.ts`'s `describeWall` names a wall purely from its position in the list). `matte.wall_alpha` is split further: `soften_boundary` — the luminance-guided edge sharpening, minus the semantic restore/exclusion steps that need a `SemanticRegions` Add does not have — is now its own function, shared by the automatic pipeline and the Add tool, so a manually-added plane gets the same soft-edge treatment (CONTEXT.md, "Alpha Matte") as an automatically-found one. `prompts.py` gained `single_point_prompt`, sharing `prompts_for`'s photo-to-graph-space scaling so a coordinate bug cannot exist in one and not the other. `planes.py` gained a `TapPoint` model (`{x, y}`, both `≥0`, in the prepared photo's pixel space) and the three routes decision #40 named, each: fetch the photo, bound-check the point against the photo's actual dimensions, call the domain function, catch `CorrectionRefused` into `422 malformed_request`, `order_left_to_right` the result, `replace_planes` it onto the job, and answer with the same `{planes, note}` shape `GET .../planes` already returns.

Two decisions #40 left open, resolved here because implementation forced an answer:

**Where a plane's exclusivity is resolved, resolved by the *stronger claim per pixel*, not by which plane arrived first or second.** See difficulty 22 in full — the first two attempts (subtract the old plane from the new one; subtract the new plane from the old ones) each looked reasonable and each measurably made a real photograph worse in a way no unit-level reasoning would have caught, only a slow-lane test against real fixtures did. The shipped rule: wherever the new plane's decoded alpha is `≥` an existing plane's alpha at the same pixel, the new one keeps it and the existing one is zeroed there; otherwise the reverse. This makes the union of every plane's coverage `max(new, existing)` everywhere, by construction — the property "a correction never makes an already-correct pixel worse" needs, not merely tends toward.

**Split and Merge reuse `walls.MINIMUM_WALL_FRACTION` as their own viability floor**, rather than a separate manual-correction constant: Split refuses a cut that would leave either half below it (of the *whole photo*, matching how the automatic splitter already judges a plane worth offering), and Add refuses a grown plane whose resolved coverage falls below it. One threshold for "worth offering as a paintable surface," used by both the automatic pass and every manual correction, rather than two numbers that could quietly drift apart.

**Why Add's coverage check runs *after* exclusivity resolution, not before:** `add_plane`'s original draft measured the raw decoded matte's coverage, then resolved exclusivity, then returned — meaning a marginal add could clear `MINIMUM_WALL_FRACTION` on paper and then lose most of that area to an existing plane's stronger claim, or (worse, pre-difficulty-22) get silently trimmed by a wrong subtraction. Measuring the *resolved* plane's own coverage is the honest number: what is this correction actually contributing, after every pixel has exactly one owner.

**Consequence:** fast-lane coverage (`tests/api/test_corrections.py`) covers everything Split and Merge do — both are pure array operations, no model, so their full logic is fast-lane testable — plus every precondition Add checks *before* touching SAM 2 (already-covered, out-of-bounds). Add's actual decode is slow-lane only (`tests/api/test_walls.py`, `test_the_add_tool_grows_a_plane_from_a_missed_wall`), against all three real fixtures, deriving its tap point from the hand label rather than a hardcoded pixel so it keeps working if the automatic pipeline's precision changes under it — this follows conventions.md §6 exactly, the same "do not mock the model adapters" rule `test_walls.py` was already built around. One property that test does *not* assert, deliberately: that the exact tapped pixel reaches full confidence. `corner-with-clothesline.jpg`'s missed region sits behind hanging clothes, genuinely occluding the wall from a single point prompt with no other context — the test asserts the honest claim instead (coverage over the labelled wall never regresses, and the tapped point itself measurably improves), not a guarantee SAM 2 cannot make from one point in a hard photograph.

---

## 43. The frontend for #10: three armed tools, one IPC channel, and a plane list handled exactly like a fresh load

**Ticket:** #10 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-05

**Decided:** every layer decision #39 named, built:

- **`GET`/every correction response gained top-level `photo_width`/`photo_height`** (`api/planes.py`, `_planes_response`), alongside the per-plane copies `_describe` already sent. A photo can have zero planes — automatic detection found nothing, or a merge just collapsed the list — and the Add tool needs the photo's own pixel space to turn a tap into a point in it precisely in that case, when there is no plane object left to read it from.
- **`bridge-types.ts`** gained `CorrectionTool` (`'add' | 'split' | 'merge'`), `TapPoint` (`{x, y}`), and widened `WallsResult`'s `ready` variant with `note`/`photoWidth`/`photoHeight` — the same fields the backend now always sends, previously silently dropped by `walls-bridge.ts`.
- **`corrections-bridge.ts`** is one IPC channel for all three tools, on the `render-bridge.ts` model (a Shade Code or an assignments map, one channel there; a tool and a point, one channel here) rather than three — the service already separates them by route (decision #40); the bridge layer has its own, different idiom. `walls-bridge.ts` had its matte-fetch loop extracted into an exported `overlaysFrom`, since a correction's response is the identical shape `GET .../planes` is and both bridges resolve it the same way.
- **`apps/ui/src/consultation/corrections.ts`** holds the pure state transitions, on the `accent.ts`/`render.ts` model: `effectiveArmedTool` (derives what is actually armed from what was explicitly chosen plus the plane count, so Add auto-arming on a zero-plane photo can never drift out of sync with reality the way a separately-set flag could), `toggleArmedTool` (the same toggle `toggleWalls`/`toggleTarget`/`toggleRenderMode` already use), `describeArmedTool`, and `tapPointFromFraction` (a fraction across the rendered element to a pixel in the photo's space — pure, so the geometry is unit-tested without a browser; the one line that reads `getBoundingClientRect` stays in the component).
- **`walls.ts`** widened `found` to carry `note`/`photoWidth`/`photoHeight` — the same `message` field already used for "why is there no overlay" now also carries the backend's "no wall found automatically" note, since both are the same kind of thing to the Dealer (a plain-language reason, shown the same way), and a `found` event with `note: null` clears a stale one from a previous state.
- **`useConsultation.ts`** gained `armedTool`, `armTool`, `correctWallsAt`, `correctionMessage`. A correction's success replays through the exact same `applyWallsEvent({type: 'found', ...})` `loadWalls` already uses — decision #40's "handled exactly like a fresh load" made literal in the reducer, not just the wire shape. A refusal never touches `walls` at all (only `correctionMessage`), so a rejected tap cannot blank the plane list the way `'unavailable'` does for a genuine fetch failure. Success also reconciles `target`/`assignments`: a split or merge can retire a plane id the Dealer had targeted or already assigned a Shade to, and the fallback is `ALL_WALLS` plus dropping the stale assignment, never a reference to a plane that no longer exists.
- **`ConsultationSurface.tsx`** adds three toolbar buttons (Add always available, Split once ≥1 plane exists, Merge once ≥2 do) and a tap-capturing `<button>` — a real element, not a `div` with a click handler, for the same keyboard/screen-reader reason the wall-chip buttons already are one — shown only while a tool is armed, in place of the wall-chip buttons (which choose a target for the next Shade; the two gestures must never both be live over the same photo). The instruction text ("Tap where a wall is to add it.") replaces the "SpectraPaint found N walls" caption while a tool is armed, and `armedTool !== null` also forces the wash overlay on regardless of the Dealer's earlier hide/show choice — correcting walls that are not visible is not a thing to build.

**Also forced by building this, not decided ahead of it:** the wash overlay, the wall-chip buttons and the new tap-layer all needed a common positioned ancestor sized to the photo's own rendered box, which `.consultation__picture` had never actually had — see difficulty 23 in full. The fix is a `.consultation__frame` wrapping only the image and the three overlaid layers (never the caption below it), `position: relative`, with an `aspect-ratio` set inline from the displayed image's own `naturalWidth`/`naturalHeight` read via `onLoad` — matching the frame's ratio to the photo's own is what removes the letterboxing gap an `object-fit: contain` image can otherwise leave between its own rendered edges and the box around it. This is a real, if latent, fix to code ticket #6/#7 shipped, not new-for-#10 scope.

**Consequence:** verified against the real running app, not only against vitest — `npm run dev` for `apps/ui` alone, driven with `playwright-core` (installed standalone; Playwright's own browser download is not needed since it can drive an already-installed `google-chrome-stable`) against a scripted `window.spectrapaint` mock. Confirmed: the frame's and the tap-layer's bounding boxes are pixel-identical at the same instant; a tap at a known fraction across the rendered element produces the exact expected photo-space point (verified for all three tools); Split/Merge appear and disappear correctly as the mocked plane count changes across an Add → Split → Merge sequence; the wash overlay is present while a tool is armed, confirmed by sampling pixel colour rather than trusting a screenshot by eye, since the difference is too subtle to be sure of otherwise; no console errors. New tests: `corrections.test.ts` (12, the pure functions), `corrections-bridge.test.ts` (16, on the `render-bridge.test.ts` model — a faked `ipcMain` and `fetch`, never a real service), and `walls.test.ts` gained cases for the widened `found` event. `apps/ui/src/consultation/render.ts` needed no change at all. `accent.ts` was believed to need none either; #44, found the next day by a Dealer actually using the correction surface, says otherwise.

---

## 44. `renderPayload` needed the plane count all along — a one-wall Accent Wall tap was painting the whole room

**Ticket:** #10 (found during manual acceptance testing) · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-07

**Decided:** `renderPayload` now takes the photo's current plane list as a second argument, and only collapses `assignments` into a bare Shade Code when the map's size equals the plane count — not merely when every *assigned* code happens to agree with itself. Both call sites (`applyShade`, `toggleRenderMode` in `useConsultation.ts`) now pass `walls.planes` through.

**Why:** `codes.every((code) => code === first)` is true of a one-entry array unconditionally — an array cannot disagree with its own only element. So the moment a Dealer targeted a single wall (`selectWall`) and tapped a Shade for the first time, `assignments` held exactly one entry, `renderPayload` read that as "every wall wants this Shade," and sent the bare Shade Code the render-bridge already treats as "paint every plane the photo has" (implementation-decisions.md §20) — repainting the *other* wall too, though nothing had ever assigned it anything. Tapping a second wall with a second colour then produced a genuine two-entry, two-code map, which correctly stayed a map — so the bug was invisible exactly in the case anyone would test first (one wall, one Shade) and only showed up once a Dealer built a real Accent Wall one tap at a time, which is precisely how it was found: by using the shipped feature, not by reading `accent.ts` or its own tests. `accent.test.ts` had a passing assertion for the buggy input (`renderPayload({wall_plane_2: 'PS-6010'})` expected to equal `'PS-6010'`) under a test named "names only the walls a Shade was chosen for" — the name and the assertion contradicted each other, and nothing caught it because `render-bridge.ts`'s own handling of a bare Shade Code is only exercised in isolation (`render-bridge.test.ts`), never chained to what a *partial* Accent Wall assignment actually produces.

**Consequence:** the wrong assertion is replaced with the regression it should have been from the start (`accent.test.ts`, "never collapses a single targeted wall into 'paint every plane'"), plus a case for three planes and one for an empty map. Nothing about the wire shape changed — `renderPayload` still returns a bare code or a map, and the bridge still discovers plane ids for a bare code the same way — only the *rule for choosing between them* got the information it needed to be right rather than accidentally right. Worth naming for the next person reading this function: "every value in this map agrees with itself" is a different claim from "every wall has this value," and the two are indistinguishable at exactly one map size.

---

## 45. A photo's own quality is judged once, at decode, as a note independent of `note` — issue #15's "poor photo → proceed with a note" criterion

**Ticket:** #15 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-08

**Decided:** a new module, `spectrapaint/quality.py`, sitting beside `imaging.py` rather than inside `segmentation/` — it knows nothing about walls, only about the photo as a whole, and is a pure function of the decoded sRGB pixels: no model, no I/O. `assess_quality(srgb) -> str | None` runs three cheap checks in the order a Dealer would actually notice the problem — mean luminance below a threshold (dark), a fraction of near-black/near-white pixels above a threshold (heavily clipped — "heavy HDR" in design-decisions.md's failure table), then a dependency-free Laplacian-variance blur score (out of focus) — and returns the first message that fires, never more than one, so the Dealer hears the single most obvious problem rather than a stack of them.

`api/preparation.py`'s decode stage calls it once, right after `decode_photo`, and stores the result on `_Workspace.quality_note` alongside the existing `workspace.note` (the *wall* note ticket #10 added). `PreparedPhoto` gained a `quality_note` field, deliberately separate from `note`: the two describe different things — whether a wall was found, versus whether the photo itself is any good — and a dark photo can still have a perfectly findable wall, so conflating them into one field would make "no wall found" and "photo is dark" mutually exclusive in the API when they are not. `api/planes.py`'s `_planes_response` always reads `prepared.quality_note` directly (unlike `note`, which is passed in explicitly per call site so a correction's answer never carries forward a stale empty-planes note) — `quality_note` is invariant across a correction, since tapping the wall never changes what the camera captured.

**Why never a refusal, by construction rather than by discipline:** `assess_quality` has no way to raise into preparation — it is called for its return value only, inside the same stage that already cannot fail preparation, so there is no code path where a poor photo becomes a `failed` job. This mirrors how ticket #10 made `NoWallFound` non-fatal (`implementation-decisions.md` §41): the "never dead-end" rule is enforced by the shape of the code, not by a comment promising nobody will add a `raise`.

**Consequence:** thresholds are picked plausibly, not measured — the same position design-decisions.md §12 takes for the render engine's own tunable constants, stated explicitly in the module docstring, because this project has no labelled corpus of bad photos yet. Issue #15 itself names the same gap for `NoWallFound` (`data/fixtures/rooms/` has no photo that legitimately triggers "no wall found," so that path has only ever run against synthetic input) and it applies here too, for the same reason: nothing in the current fixtures is dark, blurred or clipped enough to exercise this against a real photograph rather than a synthetic one. `tests/render/test_quality.py` (Seam 2 — pure function, synthetic images, on the `test_split.py` model) covers the heuristic's behaviour directly; `tests/api/test_planes.py` and `tests/api/conftest.py`'s new `poor_quality_preparation_stages` cover only that the note reaches the Dealer through the contract, the same division ticket #10's own quality-note-adjacent work drew between "does the heuristic work" and "does the wire carry what it decides." Threading `quality_note` through the desktop bridge (`walls-bridge.ts`, `bridge-types.ts`) and the UI (`walls.ts`, `useConsultation.ts`, `ConsultationSurface.tsx`) followed the exact shape `note` already has end to end, reusing the existing `.consultation__wall-note` paragraph style rather than a new component — ui-guidelines.md's component list is deliberately short, and this is a plain-language caption, not a new kind of surface.

---

## 46. `EmptyState` and `Toast`, the two components ui-guidelines.md always listed but nothing had built yet, plus two real gaps they exposed

**Ticket:** #15 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-08

**Decided:** two new components in `apps/ui/src/components/`, on the exact model `ErrorState`/`ProgressMessage` already set: `EmptyState` (a message plus an *optional* action — unlike `ErrorState`, whose action is required, because an empty state sometimes has nowhere better to send the Dealer than back to what they were already doing) and `Toast` (a message plus an optional action, `role="status"`, deliberately with **no auto-dismiss timer** — the Dealer is at a counter with a Customer waiting, and a timed toast could take the one way to undo a mistake with it before anyone notices it was there).

Auditing every surface against ui-guidelines.md's "every surface needs its loading, empty and error state" turned up:

- **Catalogue's search-empty-result block already existed** (`CataloguePanel.tsx`, from an earlier ticket) as bespoke markup (`catalogue__empty`/`catalogue__empty-message`) rather than a shared component — the exact "build once, reuse" gap `EmptyState` closes. Refactored to use it; the bespoke CSS rules are deleted, not kept alongside the new component.
- **`LibraryScreen.tsx`'s "Bundle deleted — Undo" banner** (`BundleList` and `BundleDetail`) was the same bespoke-markup gap for `Toast`: hand-rolled `library__undo` divs, one per screen, doing exactly what a shared `Toast` does. Both replaced; `.library__undo` deleted.
- **`BundleList` had no loading state at all.** `useLibrary`'s `bundles` starts as `[]`, so a slow first fetch (a large SQLite file, a cold disk) and "this Dealer genuinely has zero bundles" were visually identical — nothing, then the list. Since a default, undeletable bundle always exists (`storage/store.py`'s `DEFAULT_BUNDLE_NAME`, created and migrated-in at every boot, `default_bundle_protected` refusing its deletion), the empty case can never actually arise once loaded — so the real gap was the missing *loading* state, not a missing empty one. `useLibrary` gained `bundlesLoaded` (true once the first fetch has settled, success or failure, and never reset by a later `loadBundles()` call — a rename or delete must not flicker the whole list away while it quietly re-fetches); `BundleList` shows `ProgressMessage` while it is false.
- **`BundleDetail`'s and `ConsultationHistory`'s existing "nothing here yet" text** (`library__hint` paragraphs) were plain text with no defined loading state alongside them — `ConsultationHistory` in particular showed nothing at all while `library.renders` was still `null`. Both replaced with `EmptyState`, and `ConsultationHistory` gained a `ProgressMessage` for the `renders === null` case; `library__hint` is deleted, nothing else used it.
- **Found while fixing the above, not by design: `BundleDetail`'s error retry called the wrong function.** Its `ErrorState`'s `onAction` was wired to `library.refreshBundles()` — which re-fetches the top-level *bundle list*, not this screen's *consultations* — so a failed consultations fetch, once retried, cleared the error message (because the bundles fetch itself succeeded) while leaving `library.consultations` stuck at `null` and the screen rendering nothing: an error that clears itself into a silent dead end, the exact thing issue #15 exists to close. Fixed to call `library.openBundle(openId)`, the function that actually re-fetches what this screen shows.

**Consequence:** no new test file — this project keeps no component-level UI tests by design (docs/specs/v1-spectrapaint.md, "Deliberately not seams: The React UI"), and neither new component nor any of this wiring is a pure function of the kind that exclusion carves back out. Verified instead against the real running app: `apps/ui` alone under `vite`, driven by `playwright-core` against `google-chrome-stable` with a scripted `window.spectrapaint` mock (the same tool and method decision #43 used, reinstalled fresh for this ticket) — confirmed live: the Bundles screen reaches the default bundle and shows `EmptyState`'s "No consultations in this bundle yet." with no action button; creating then deleting a bundle shows the `Toast` with a working Undo action; and — only reachable by holding the mocked `/bundles` fetch open past the two-second boot floor, since in the ordinary case boot's own minimum wait outlasts a local SQLite read — `BundleList`'s `ProgressMessage` genuinely appears rather than existing only on paper. No console errors beyond expected artifacts of the mock harness itself (a benign CSP meta-tag warning, one 404 for a favicon).

---

## 47. "Sidecar death restarts quietly and the Consultation resumes" was true of the screen, not of the Consultation — verifying #3 found the gap, and closed it with a guided recovery rather than a silent one

**Ticket:** #15 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-08

**What was found, tracing the path rather than assuming it:** `BootStatusHub` (`apps/desktop/src/boot-status.ts`) broadcasts on one channel regardless of whether the Dealer is at Boot or mid-Consultation, and `App.tsx` unconditionally renders `<BootScreen>` whenever `useBoot().finished` is false — so a mid-consultation sidecar restart genuinely does pull the Dealer's screen to "Just a moment — reconnecting…" and back on its own, automatically, with `consultation`'s own React state never touched. That much matches the spec's "restarts quietly and resume" wording. But the Python service's session registry is in-memory only, by design (`api/sessions.py`'s own docstring: "a live session dies with the process, which is correct") — so the restarted process has forgotten every live session, while the renderer is still holding the old `sessionId`. The screen resumes; the Consultation does not. The next Shade tap, mode toggle or wall correction sends that dead id to the new process and gets back `404 session_not_found`, forever, with no code path that ever recovers on its own — a quiet, permanent failure loop dressed as a working screen, which is arguably worse than an obvious error, since nothing tells the Dealer to do anything differently.

**Decided, after asking rather than assuming which of two designs the criterion meant:** guided recovery over silent reconnection. A silent auto-reconnect (thread a `consultationId` through `useConsultation`/`App.tsx`, detect the restart, `POST /consultations/{id}/reopen` behind the scenes, swap the session transparently) was the other option and is not built — it is materially bigger (new state the whole surface has to carry correctly, more places a silent swap can disagree with what is on screen) for a criterion that reads as satisfied either way. What ships: `session_not_found` is now a code every failure path already receives (it was already on the wire; nothing recognised it) and reacts to distinctly from an ordinary failure. `RenderState` gained a `code` field (`render.ts`, alongside the existing `message`), and `useConsultation`'s correction path gained the equivalent `correctionCode`. Wherever that code is `session_not_found`, `MESSAGE_SESSION_LOST` — "SpectraPaint had to restart. Please reopen this consultation from Bundles to continue — nothing has been lost." — replaces the service's own wording, and `ConsultationSurface.tsx` renders an `ErrorState` whose action is "Go to Bundles" wired to the existing `discard()`, rather than the ordinary "Choose another Shade"/`dismissRender`. Every other failure code is untouched — this is a targeted branch, not a new state machine.

**Why the service's own message is actively worse here, not just less specific:** `_MESSAGE_SESSION_NOT_FOUND` (`api/sessions.py`) reads "This consultation is no longer available. Please start a new one." — true of the *live session*, but the Consultation itself was never lost: issue #11's auto-save writes the photo and, once `require_photo` runs once, the Alpha Mattes too, before a Dealer has done anything but look at the walls. "Start a new one" tells the Dealer to re-photograph and re-run preparation on a room that is still fully recoverable one tap away. Overriding it is not cosmetic wording — it is the difference between the recovery that actually exists (reopen) and one that throws away intact work.

**Why `discard()` already does the right thing for this button with no change of its own:** it ends the session (`DELETE /sessions/{id}`, already tolerant of a 404 — logged, never thrown, per its own existing comment) and resets to the `idle` phase, which is exactly what lands the Dealer on Bundles; the Consultation itself was auto-saved at upload and needs nothing from this button to still exist there.

**Consequence:** `render.test.ts` gained one case asserting `applyRenderEvent` retains `code` through a `'failed'` event (the property the surface's branch depends on); the correction path and the `MESSAGE_SESSION_LOST` override are UI-shell logic this project deliberately does not unit-test (see #46's "Consequence" — same exclusion, same reasoning) and were verified against the real running app instead: a scripted `window.spectrapaint.render` returning `{status: 'failed', code: 'session_not_found', ...}` produces the "Go to Bundles" `ErrorState` and clicking it lands back on Bundles; the same script returning an ordinary `shade_not_found` failure confirmed the existing "Choose another Shade" path is untouched. Worth naming for whoever eventually decides silent reconnection is worth building: the missing piece is not detecting the restart (the boot-status channel already fires) but that no part of the renderer currently knows a live session's *Consultation* id apart from its *session* id — `useConsultation`'s `adopt()` and `start()` both discard that distinction today, and a transparent reconnect cannot exist until something keeps it.
## 45. Export re-renders from the original upload bytes, and the JPEG leaves through a save dialog

**Ticket:** #12 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-08

**Decided:** `POST /sessions/{id}/exports` (`spectrapaint/api/exports.py`) re-renders the request's
`assignments` at the photo's **original resolution** and returns a **JPEG** (quality 92, 4:4:4 so
the matte edge does not smear, no EXIF). The full-resolution photo comes from the original upload
bytes: the `SessionRegistry` keeps them in memory per live session (`_originals`, dropped on
delete), with a `Store.original_bytes` fallback through `original_path` so a **reopened**
Consultation exports full-res too — `restore` mints a session that has no originals in memory, but
the store kept the upload (decision #37). The Alpha Mattes are the preview-scale ones upscaled
bilinearly; the full-res boundary-band refinement pass is **not** re-run, so the export's wall
edges are exactly as soft as the preview's — accepted for V1, and the known softness is stated
here rather than hidden. The stored PNG archive is never handed out: a fresh JPEG is always
rendered (design-decisions §9). The filename carries the Shade Code and name
(`AP-2140-Almond-Cream.jpg`); an Accent Wall joins every Shade with `+`, the human name is
sanitised for all three OSes while the code is kept verbatim, and the result is capped at 120
characters. The endpoint does **not** file a Render into the store: a library Render is what a
reopened Consultation must show unchanged, and the exported JPEG is a Customer artifact the app
does not own.

In the shell, a **dedicated export bridge** (`apps/desktop/src/export-bridge.ts`) — the pattern
technical-difficulties #7 predicted — fetches the JPEG with the secret in main, writes it to a
temp file, then opens the native save dialog and copies to the chosen path, revealing it with
`shell.showItemInFolder`. On Windows there is no system share sheet to hand a file to, so
**save dialog + reveal-in-folder is the share-sheet interpretation**: WhatsApp, email and print
all consume a file from Explorer, and the dialog is the "choosing an export destination" native
dialog the spec already assigns to main. The bridge returns `ready | cancelled | failed` with the
service's plain-language message passed through, and the temp file is deleted unless it *is* the
deliverable (the dialog-throw fallback returns the temp path itself). In the UI, export is its own
state slice (`apps/ui/src/consultation/export.ts`, pure reducer, vitest-covered) driven fire-and-
forget, so the Export button's in-flight state never blocks browsing — the acceptance criterion
the slice exists for.

**Why:** rendering from the original bytes rather than upscaling the stored preview PNG is the
difference between a full-resolution render and an enlarged one — the Light Map, Base Colour and
tint are re-derived at full res, so shadows and brightness behave exactly as a preview render
would at that size. Keeping originals in memory per live session is bounded (auto-save already
keeps them on disk) and avoids a second encode. JPEG rather than PNG is the design decision, not
a new one — WhatsApp and email compress or reject nothing about a JPEG, and the customer's phone
is where the file is going.

**Consequence:** seam 1 covers every acceptance criterion against a 1600×1200 fixture — the
browsing render is asserted capped at `MAX_PREPARED_DIMENSION` while the export is asserted at
the photo's own size (the criterion is measured, not inferred from content types), JPEG magic and
media type, filename carrying code and name, the archive never leaving as PNG, and a render
succeeding straight after an export. The contract test in `test_sessions.py` pins the new route.
Reopened Consultations export full-res through the store fallback, and `SPECTRAPAINT_STORAGE_DIR`
tests that predate originals get preview-scale exports rather than a failure — degrade, never
dead-end (conventions §5).

---

## 46. Storage view lists Bundles by bytes, and the warning is well before critical (issue #13)

**Ticket:** #13 · **Contributor:** Chauhan Anamika Abhimanu (code written by an agent) · **Date:** 2026-09-09

**Decided:** `Store` gained `bundle_bytes`/`consultation_bytes`/`storage_overview` (summing file sizes on disk, largest first) and `delete_consultation` (deletes photos, mattes, renders and rows). `GET /storage` returns bundles with `bytes` plus a `disk {free_bytes,total_bytes,low,warning}` probe via `shutil.disk_usage`; `GET /storage/disk` is the same probe alone for the global banner. `DELETE /consultations/{id}` deletes one Consultation. Low is `free < 2 GB` or `free/total < 10 %` — the same threshold checked in the Electron shell via `fs.statfsSync(app.getPath('userData'))` so the warning survives a down service. The UI's `StorageView` shows bundles by consumption and lets the Dealer delete Bundles and Consultations there; `App` shows a plain-language banner ("Your disk is getting full. Open Storage to delete old Bundles — otherwise new photos may fail to save.") well before critical, with an action to Storage, so the app never fails mid-Consultation without having warned first.

**Why:** the spec's "no automatic deletion" only works paired with an informed manual path — bytes per Bundle is that information. The same file-size sum the Store already writes is the source of truth, not a cached counter that can drift. The threshold is deliberately generous (design-decisions §9, ~15 GB/month, floor-tier PC fills in ~2 years) so the Dealer has weeks, not minutes, to act.

**Consequence:** the contract test pins the three new routes. A cached bytes column was rejected — it would need invalidation on every write and save nothing on a library of thousands, not millions, of files.

---

## 47. The ceiling is its own paintable surface, selectable and independently coloured, with the same realism

**Ticket:** #39 · **Contributor:** anamikachauhan26 (code written by an agent) · **Date:** 2026-09-09

**Decided:** the four open questions on the ticket were settled and built together:

1. **Vocabulary.** CONTEXT.md gains **Ceiling Plane** ("one visible flat ceiling face, typically one per photo, coloured independently with its own base colour, light map and alpha matte") and **Paintable Plane** as the generic term for any paintable surface — a wall plane or a ceiling plane — carrying a `surface` of `wall` or `ceiling`. Used consistently in code (`surface` field on every plane, `WallPlane.surface`) and in the REST contract `GET /sessions/{id}/planes` (`surface` on each plane).
2. **Automatic detection, and manual.** The semantic pass already classifies ceiling pixels (one of the five ADE20K classes, kept only as an exclusion for walls). Automatic detection runs that existing mask through the same SAM 2 refine + soft-matte treatment `segmentation/matte.py` already has — `encode_photo` is cached per photo so a ceiling decode costs the cheap ~120 ms (implementation-decisions.md #23), not a second ~2 s encode — almost certainly **without** `split.py`'s plane splitting (a ceiling in one photo is essentially always one region, unlike a wall). Manual is via the correction surface's new **Add ceiling** tool (see 4).
3. **Where it lives in the contract.** `GET /sessions/{id}/planes` grows a `surface` field (`"wall" | "ceiling"`) on each plane and reuses the existing `assignments` shape as-is (`{ plane_id: shade_code }`). The render engine's maths (`light_map`/`new_wall` in `render/engine.py`) does not care what surface it is painting — the one change that **does** matter is base-colour grouping: `render/engine.py:_GROUP_TINT_THRESHOLD` now partitions by surface, so a ceiling is never grouped with a wall's base colour even when the two happen to be a similar pale colour, or the room's light modelling breaks silently.
4. **How the correction surface treats it.** "Add a wall" stays wall-only, with a separate **Add ceiling** tool. Tapping the ceiling with today's Add wall already *works* mechanically (SAM 2's point prompt does not know what it is segmenting) but comes back mislabelled as a wall with the tint-grouping risk above; separate tools keep the two gestures unambiguous and make the surface the Dealer's explicit intent rather than a guess from the tap point.

Automatic detection is `segmentation/walls.py:ceiling_from` (no split, `MINIMUM_CEILING_FRACTION 0.02`, `CEILING_PLANE_ID`), called from `api/preparation.py:find_the_edges` after walls, sharing the cached `RefinerFeatures`. `segmentation/semantic.py` now exposes `ceiling` and `ceiling_confidence` on `SemanticRegions` (kept separately from `excluded`, which for walls still contains ceiling as an exclusion, and must keep doing so), `segmentation/prompts.py:prompts_for_ceiling` samples eroded ceiling plus wall-as-negative, and `segmentation/matte.py:ceiling_alpha` mirrors `wall_alpha` with the ceiling's own exclusion set and `soften_boundary`. Exclusivity between wall and ceiling, where both mattes confidently claim the same pixel, is resolved by stronger alpha wins (same max-wins rule as `corrections.py:add_plane`), so no pixel is composited twice.

`api/planes.py` now describes `surface` and offers `POST /sessions/{id}/planes/ceiling` (single ceiling per photo enforced, second add refused). `api/renders.py` and `api/exports.py` carry `surfaces` through to `render_many`, which partitions grouping by surface. Storage (`storage/store.py:save_preparation`/`preparation_of`) now persists `surface` per matte so a reopened ceiling restores with the right grouping. `GET /planes` and every `POST .../planes*` answer with `surface`; the contract test in `tests/api/test_sessions.py` pins the new route.

**Why:** the four alternatives were weighed exactly as the ticket frames them. Vocabulary had to be settled before code could name anything — `CONTEXT.md` §1 demands it — and generalising to Paintable Plane keeps the contract honest (one list, one assignments map) rather than minting a second resource for the ceiling that would duplicate every render and storage path. Automatic detection was judged worth standing up now because the mask and the refine path already exist and the cost is a decode, not an encode — manual-only would have been a save for a follow-up ticket, not a saving. Keeping the contract flat (surface on each plane) means an accent wall and a ceiling accent are the same shape to the UI and to the store, and the grouping partition is the one place the surface actually changes the maths, so it is the one place the code branches. Separate Add tools were chosen over a single Add that auto-labels by asking the semantic map, because a single tool would need the semantic regions held through to correction time (and would silently mislabel a tap near the wall-ceiling edge), while two tools make the Dealer's intent the source of truth — one extra tap only while correcting, never while browsing.

**Consequence:** `WallPlane` is now a Paintable Plane with `surface="wall" | "ceiling"` (default wall for backward compat with tests). `GET /planes` and every `POST .../planes*` answer with `surface`; the contract test in `tests/api/test_sessions.py` pins the new route. The frontend carries `surface` in `WallPlaneOverlay`, `CorrectionTool` gains `add-ceiling`, and `ConsultationSurface.tsx` shows **Add ceiling** (only when no ceiling exists) and labels the ceiling as "the ceiling" via `accent.ts:describePlane`. The fixture tool `tools/fixtures/label_rooms.py` now writes an optional `<name>.ceiling.png` (white ceiling, black elsewhere, mid-grey uncertain band) so a ceiling accuracy claim can be measured rather than asserted once a fixture with a usable ceiling is labelled; the three real fixtures currently carry no ceiling regions, but the lane no longer needs one to pass. Every state wall planes already define — loading, empty, error — is extended to the ceiling by virtue of being the same plane list, not bypassed for it.

---

## 48. The execution profile: detection, override, persistence, tier variants, and the stamp (issue #14)

**Ticket:** #14 · **Contributor:** Aniketghorpade7 (code written by an agent) · **Date:** 2026-09-15

**Decided:** the machine adapts, the Dealer can override, and every result records what produced it — built as five decisions:

1. **Detection is a heuristic, not an SDK.** The hardware profile is auto-detected once at boot by running `nvidia-smi` (`execution-profile.ts:detectDefaultHardwareProfile`): it succeeds on a machine with a GPU driver, fails anywhere else. No CUDA SDK, no GPU probe library, no Electron API — a one-shot `execFileSync` in the main process at boot, which is the only moment hardware can change.

2. **The profile travels as two environment variables, not one composite.** `SPECTRAPAINT_HARDWARE_PROFILE` (`cpu | gpu`) and `SPECTRAPAINT_QUALITY_TIER` (`faster | better`) are set by the sidecar launcher (`sidecar.ts`) at spawn; the composite string (`cpu-better`, `gpu-faster`) is *derived* from them (`spectrapaint/execution_profile.py`, `execution-profile.ts`). An earlier draft used a single `SPECTRAPAINT_EXECUTION_PROFILE` variable — renamed, because the Dealer overrides only the tier while the hardware is detected, and one variable would have forced the shell to parse its own setting back apart.

3. **The tier selects a config file, and the inference call site never branches.** `graphs.py:_read_config` reads `runtime-fast.json` when the tier is `faster`, `runtime.json` otherwise; the config names the graphs and the input sizes that belong to them, and `_load_graph` loads whatever the config names — identical call site either way (the issue's "loading a different file into an identical call site" criterion). The `-fast` naming convention is: `<base>-fast.onnx` beside `runtime-fast.json`, produced by `tools/export_onnx.py --fast`. Concretely the faster tier is the same SegFormer weights at 384×384 instead of 512×512; SAM 2 has no smaller variant — its positional embeddings and neck are pinned to 1024×1024 and refuse every other input — so the refiner's `runtime-fast.json` is deliberately the same graphs, written anyway so the tier's meaning stays inspectable in one place (models/README.md). A model with no exported faster variant serves the base model and logs a warning: a quiet fallback would hide exactly the difference the tier exists to make.

4. **The GPU/ADR-0001 tension is made non-silent.** The shipped ONNX Runtime is the CPU-only wheel (`pyproject.toml`), so a `gpu-*` profile cannot actually reach CUDA until the packaging decision (design-decisions.md §3) lands. Rather than letting detection report `gpu-*` while inference quietly runs on CPU, `graphs.py:get_execution_providers` falls back to `CPUExecutionProvider` with a logged warning naming the missing package — the disagreement between what a machine reports and what it runs is the exact thing the profile stamp exists to catch, so it is never allowed to be silent.

5. **Only the tier persists; the stamp is one shared helper.** The Dealer's tier choice survives restarts in a tiny `settings.json` under `app.getPath('userData')` (the directory the shell already owns — no new dependency), restored at the top of `whenReady` before the sidecar starts; the hardware profile is re-detected every boot, so a Dealer who moves machines does not drag a GPU choice into a CPU-only one. The stamp is `spectrapaint/execution_profile.py:execution_profile()` — one standard-library-only helper read by the API endpoint (`GET /execution-profile`, registered in `app.py`), the Store's render stamp (`renders.py`), and the benchmark (`bench_render_loop.py`, `perf-baseline.json`), so what the Dealer saw, what the Store saved and what a benchmark measured can never disagree.

**Why:** each alternative was rejected for a measured reason. An SDK-based detection (pynvml, `wmic`) would add a dependency to answer a question `nvidia-smi` already answers on every machine with a GPU; a single composite env var would make the shell parse its own setting; branching on the tier inside the graph-loading call site would put a decision where the config already names the answer, and would have been the second place a variant's shape could disagree with the code feeding it (the original suffix-try logic fed a `-fast` graph with base-size inputs — a latent shape mismatch the config-per-tier design removes by construction); persisting the hardware choice would contradict AC1's "auto-detected at boot"; and per-site profile reads would repeat the two-sources-of-truth bug the hardcoded `"preview"` stamp had.

**Consequence:** the profile is stamped on every render and export, appears in the benchmark gate output and baseline, and the Settings modal's choice survives restarts. `GET /execution-profile` is registered and pinned in the contract-surface test. The bridge tests no longer import `main`'s boot chain — profile state lives in `apps/desktop/src/execution-profile.ts`, so a bridge test reads a string without starting the window, the boot-status hub, or (on a dev machine with a synced venv) a real service process. The faster tier is real: `semantic-fast.onnx` is exported and parity-verified against PyTorch at 384×384, and both tiers were verified loading from the real models. The GPU limitation is documented on the dependency and logged, not silent.

---

## 49. The wall matte gets a confidence floor, and #31's other three directions are closed as measured dead ends

**Ticket:** #31 · **Contributor:** Aniket Ghorpade (code written by an agent) · **Date:** 2026-09-15

**Decided:** one change to the pipeline — a `WALL_CONFIDENCE_FLOOR` of 0.9 in `matte.py`, applied by
`_unvouched()`. A pixel SAM 2 claims is wall is dropped when the semantic pass will not vouch for it,
with two exemptions: pixels the restore step already forced to 1.0, and **anything SegFormer's own
argmax called `wall`, however unsure**. The thresholds in `tests/api/test_walls.py` are unchanged at
IoU 0.60 and leakage 0.20, and `measured.toml` keeps the ratchet of decision 32. The other three
candidate directions in #31 are closed, each with numbers rather than an opinion.

Measured on the three fixtures, before and after:

| Photograph | Leakage | Wall IoU | Shadowed-wall recall |
|---|---|---|---|
| `empty-corner` | 0.209 → 0.209 | 0.946 → 0.944 | 0.993 |
| `corner-with-clothesline` | 0.348 → **0.338** | 0.768 → 0.771 | 0.971 |
| `windows-with-curtains` | 0.239 → **0.185** ✓ | 0.369 → **0.389** | 0.910 → **0.801** |

**Why:** the floor is the only one of the four directions that pays. It retires one failing metric
outright — `windows-with-curtains` leakage now clears its 0.20 target and its entry is gone from
`measured.toml` — and moves `empty-corner` by nothing at all, exactly as #31 predicted: a floor can
only remove what the checkpoint was unsure of, and on that door it is 0.97 sure.

The argmax exemption is the whole of why the floor is shippable. Without it the same floor scores
0.765 shadowed-wall recall on `windows-with-curtains` against a floor of 0.80 — it deletes wall in
shadow, which is the single failure `design-decisions.md` §5 calls the most damaging one. Two
weaker forms were measured and rejected: reading the confidence through a box mean first changes no
metric on any fixture to three decimal places, because the band-and-core step already resolves the
matte spatially; and holding argmax-wall pixels to a *lower* floor instead of exempting them is back
to 0.776 recall at 0.35, because that shadowed wall is labelled `wall` at only 0.2 to 0.35
confidence.

**Negative prompts from a second tier of classes were built, measured and reverted.** The reasoning
for trying was sound — the over-claim originates in SAM 2's mask, `prompts.py` draws negatives only
from the four exclusions, and SegFormer *does* correctly call some of the clothes `apparel` and
`towel` — so the full path was implemented: a `DISTRACTOR_CLASSES` tier in `tools/export_onnx.py`
(curtain, apparel, towel, mirror), written to `runtime.json` under its own key, carried as a third
map on `SemanticRegions`, and sampled as negative points. It makes the matte **worse**: leakage on
`corner-with-clothesline` rises from 0.338 to 0.369 while IoU falls from 0.771 to 0.752. Five
variants were measured — gating the points to low wall-confidence (0.5, 0.3, 0.1), guaranteeing the
exclusions their points before the distractors get any, and widening the negative share to 0.50 and
0.40 — and every one of them is worse than exclusions alone on that photograph. The cause is the
same domain gap seen from a new angle: the checkpoint labels 17.8% of that photograph and 48.3% of
`windows-with-curtains` as a distractor, far more than those objects occupy, so the negative points
land on real wall and SAM 2 pulls its boundary off wall it had right. The labels are not reliable
enough to be *evidence*, not merely not reliable enough to be *rules*.

**Promoting those classes to real exclusions was measured too, and is not worth its cost.** With
prompts left alone, removing `curtain` and `mirror` from the matte scores 0.336 / 0.180 / 0.390
against the shipped 0.338 / 0.185 / 0.389 — better on every metric, worse on none, and worth at most
0.005. That is too little to buy a design commitment: it makes an absolute rule
(`design-decisions.md` §5: a pixel leaves the wall because the model named it, and nothing brings it
back) out of labels we have just watched misfire across half a frame.

**The thresholds are left where they are.** #31 offered revising them as a fourth direction, and the
case against is that the one photograph that fails them is not a threshold problem. `empty-corner`
misses 0.20 by 0.009 with everything else about it correct, and `windows-with-curtains` misses IoU
0.60 by 0.21 — no honest number covers both, and a threshold moved to accommodate a door painted at
0.97 confidence would be a number chosen to make a known defect read as a pass. The ratchet in
`measured.toml` already does the job a revised threshold would: the lane is green, a regression still
fails it, and the shortfall stays visible.

**Consequence:** the shadowed-wall margin on `windows-with-curtains` is now **0.001** — 0.801 against
a floor of 0.800, down from 0.910. That is the floor's real price and it is thin: a Pillow release
that resizes a label by one pixel could trip it. It is recorded in `measured.toml`'s header as the
number to watch, and a future change that needs room should reconsider the floor rather than lower
that test. Two of the three fixtures still fail their leakage target and `windows-with-curtains`
still misses IoU 0.60 by a wide margin; with this checkpoint fixed, nothing in this entry changes
that, and the remaining route is the one
[`docs/handoff/custom-wall-segmentation-model.md`](./handoff/custom-wall-segmentation-model.md)
describes. Reversing the floor means deleting `_unvouched()` and re-recording three baselines.
