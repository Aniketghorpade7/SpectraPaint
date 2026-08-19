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
| Python | **3.12** | 3.14 lacks reliable ML wheels — established during the latency spike. `pyenv` has 3.12.10; on Windows use the python.org installer or `uv` — the version is the constraint, not how it is installed |
| Service | **FastAPI** | Native streaming responses for the progress stream, and the contract is small |
| Python lint/format | **ruff** | One tool for both |
| Python tests | **pytest** | |
| UI | **TypeScript + React** | Types matter more than usual with agents writing across isolated contexts |
| Build | **Vite** | |
| UI lint/format | **eslint + prettier** | |
| Models at runtime | **ONNX Runtime** | PyTorch stays in the export toolchain only — see [ADR-0001](./adr/0001-local-first-inference-over-localhost-rest.md) |

Assume a **CPU-only** build until the packaging question in `design-decisions.md` §12 is settled.

**The target is Windows; contributors develop on Linux or Windows** (`design-decisions.md` §9c).
Anything a contributor is expected to run must work on both — no bash-only scripts, no `rm -rf` or
bare `VAR=x cmd` in npm scripts, no hardcoded path separators. Paths come from `app.getPath()` and
`platformdirs`, never from string concatenation.

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

Two seams, and both are described fully in
[specs/v1-spectrapaint.md](./specs/v1-spectrapaint.md).

- **Seam 1 — the REST contract.** Integration. Behaviour and lifecycle. Slow; keep it few.
- **Seam 2 — the render engine.** Pure function, synthetic inputs with analytically known answers.
  Fast; keep it thorough.

Plus a **small `vitest` suite for shell logic neither seam can reach** — pure functions only, and
only where a silent regression would be expensive and invisible (`design-decisions.md` §9d). If a
test there needs a DOM, a mock or a running Electron, it belongs in seam 1 instead.

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

## 7b. Branch per ticket

`main` is protected. Nobody pushes to it — not humans, not agents, not administrators. Every change
arrives as a pull request.

```bash
git switch main
git pull
git switch -c 12-shade-catalogue-import   # <ticket number>-<short-slug>
# ... work, commit ...
git push -u origin 12-shade-catalogue-import
gh pr create --fill
```

**To merge, a pull request needs two things:**

1. **A green pipeline.** The fast lane on Linux and Windows, the performance gate, the licence gate,
   and the slow lane's contract tests. These are required checks — the merge button stays disabled
   until they pass.
2. **A human review.** Approval from someone who is not the author.

Why both, stated plainly: V1 is worked in isolated fresh contexts, so **CI is the only integration
memory this project has** — nothing else notices when one ticket breaks another. And the pull
request is the **only point where a human reads agent-written code before it lands**.

The risk worth naming is rubber-stamping. An approval clicked without reading turns the gate into
decoration, and a decorative gate is worse than none, because it is trusted. Read the diff.

The required checks, by the exact names the merge gate matches on:

```
Checks (ubuntu-latest)
Checks (windows-latest)
Performance gate
Seam 1 — REST contract, with models
```

**Administrators are not enforced, deliberately.** GitHub will not let an author approve their own
pull request, so on a repository with one human that rule would make merging impossible rather than
careful. The admin bypass is the escape hatch that keeps the requirement honest for everyone else.
It is a hatch, not a habit: the reason the human review exists is that the pull request is the only
place agent-written code gets read before it lands, and merging past a red pipeline throws away the
only integration memory the project has.

**When CI fails, fix the cause.** Do not add a licence to `tools/approved-licences.toml`, re-record
`spikes/latency/perf-baseline.json`, or mark a test skipped to get to green. Each of those is a
legitimate change when the reasoning is sound and stated in the commit — and a quiet way to disable
the project's only integration memory when it is not.

## 7c. Write down what you decided, and what fought you

Two living documents in `docs/`, and **every contributor keeps both up to date as part of the
ticket** — not afterwards, and not only when it went badly.

| Document | What goes in it |
|---|---|
| [implementation-decisions.md](./implementation-decisions.md) | Every major decision taken while implementing, **why** it was taken, and **who** took it |
| [technical-difficulties.md](./technical-difficulties.md) | The technical difficulties you hit — solved, worked around, or still open |

Each file states when an entry is warranted and the format to copy. Both are append-only: number
entries sequentially, never renumber, and never edit history — a reversal is a new entry that links
back to the one it replaces.

Record the **contributor** as the human who owns the change, and note where an agent wrote the code;
the reasoning was still a human's to accept. A decision needs somebody who can be asked about it.

Why this is a rule and not a nicety: V1 is worked ticket by ticket in **isolated fresh contexts**.
Nobody working a later ticket was present for the argument that settled an earlier one. The code
records *what* was chosen and loses *why*, which is the half a later contributor needs in order to
change it safely — so an unrecorded decision gets silently re-argued, or quietly reversed by someone
who assumed it was arbitrary. The same holds for difficulties: a dead end nobody wrote down is a
dead end the next person walks into at full speed.

Note the boundaries. `design-decisions.md` holds the decisions made *before* the code existed;
implementation decisions are the ones the code forced. A decision that is **hard to reverse** is an
[ADR](./adr/) instead — the test is in [README.md](./README.md).

## 8. Before opening a PR

- [ ] Ticket acceptance criteria all met
- [ ] Glossary vocabulary used throughout
- [ ] Lint and format clean
- [ ] Tests pass, and new behaviour is covered at the right seam
- [ ] No new decision made silently — every major implementation decision recorded in
      `implementation-decisions.md` with its reasoning and your name (§7c)
- [ ] Difficulties hit — solved, worked around or still open — recorded in `technical-difficulties.md`
      (§7c)
