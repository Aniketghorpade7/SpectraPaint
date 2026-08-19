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

