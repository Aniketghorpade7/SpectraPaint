# Coding Conventions

Rules for anyone — human or agent — working a ticket in this repository.

Read [../CONTEXT.md](../CONTEXT.md) first. This document assumes its vocabulary.

---

## 1. Use the glossary in the code

**The single most important rule here.** [CONTEXT.md](../CONTEXT.md) defines the project's
vocabulary. Code must use those exact words.

| Use | Not |
|---|---|
| `wall_plane` | `region`, `segment`, `area` |
| `shade` / `shade_code` | `color`, `colour_id`, `paint` |
| `base_colour` | `avg`, `mean_color`, `ref` |
| `light_map` | `shading`, `ratio`, `illum` |
| `alpha_matte` | `mask` (a mask is hard; a matte is soft — the distinction matters) |
| `consultation` | `session` in user-facing terms; `session_id` is fine at the HTTP layer |
| `bundle` | `customer`, `folder`, `project` |
| `catalogue` | `palette`, `swatches` (the **fandeck** is the physical book, never the data) |

Synonyms are how a codebase quietly becomes unreadable. If three files call the same thing a
`mask`, a `region` and a `plane`, nobody can tell whether they are the same thing — and with
tickets worked in isolated contexts, that drift happens fast.

**If you need a concept the glossary lacks, add it to `CONTEXT.md` in the same change.**

Spelling: **`colour`** in prose and domain names, **`color`** only where a library or CSS forces it.

## 2. Language and tooling

| | Choice | Why |
|---|---|---|
| Python | **3.12** | 3.14 lacks reliable ML wheels — established during the latency spike. `pyenv` already has 3.12.10 |
| Service | **FastAPI** | Native streaming responses for the progress stream, and the contract is small |
| Python lint/format | **ruff** | One tool for both |
| Python tests | **pytest** | |
| UI | **TypeScript + React** | Types matter more than usual with agents writing across isolated contexts |
| Build | **Vite** | |
| UI lint/format | **eslint + prettier** | |
| Models at runtime | **ONNX Runtime** | PyTorch stays in the export toolchain only — see [ADR-0001](./adr/0001-local-first-inference-over-localhost-rest.md) |

Assume a **CPU-only** build until the packaging question in `design-decisions.md` §12 is settled.

## 3. Where code goes

Each directory in the scaffold has a `README.md` stating what belongs there. Read it before adding
files. The important boundary:

**`render/` is a pure function.** No I/O, no logging, no config reads, no model calls. It is test
seam 2 precisely because it is pure — anything impure that leaks in destroys that.

## 4. Naming

- Python: `snake_case`; modules lowercase; classes `PascalCase`
- TypeScript: `camelCase` for values, `PascalCase` for components and types
- HTTP: lowercase plural resources (`/sessions`), `snake_case` JSON fields
- Constants that exist to be tuned against real photographs — blend curves, thresholds, percentiles
  — go in one named place per module, not inline. See `design-decisions.md` §12 items 7, 19, 20.

## 5. Errors

**Never dead-end** (`design-decisions.md` §13). Every failure leaves the Dealer something to do.

- Service returns a machine-readable code plus a message the UI may show as-is
- Messages are plain language and **name no model or technique** — "Finding the walls in your
  photo…", never "SAM 2 inference failed"
- Never swallow an exception silently. Quiet recovery is fine; quiet recovery *without a log* hides
  a recurring fault
- Do not refuse work that can proceed imperfectly — warn and continue

## 6. Tests

Two seams only, and both are described fully in
[specs/v1-spectrapaint.md](./specs/v1-spectrapaint.md).

- **Seam 1 — the REST contract.** Integration. Behaviour and lifecycle. Slow; keep it few.
- **Seam 2 — the render engine.** Pure function, synthetic inputs with analytically known answers.
  Fast; keep it thorough.

**Test external behaviour, never implementation.** A test must survive swapping the semantic model,
retuning the smoothing curve, or restructuring internals. The light map, base colour grouping and
boundary refinement are *implementation*. What the contract returns is *behaviour*.

Do not mock the model adapters. They are covered through seam 1; mocking them would assert only
that the mocks work.

## 7. Commits

- Present tense, describing what changed and **why**
- Reference the ticket: `Closes #7`
- **No `Co-Authored-By` or attribution trailers**
- Keep a commit to one ticket where you can

## 8. Before opening a PR

- [ ] Ticket acceptance criteria all met
- [ ] Glossary vocabulary used throughout
- [ ] Lint and format clean
- [ ] Tests pass, and new behaviour is covered at the right seam
- [ ] No new decision made silently — if you decided something the docs did not cover, record it in
      `design-decisions.md`
