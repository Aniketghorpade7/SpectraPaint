# SpectraPaint

Paint visualisation for dealers, on the Customer's own room photo — not a stock template room.

An Electron desktop app with a React UI, talking to a Python inference service on localhost. All
image and model work runs on the Dealer's machine; nothing leaves the premises.

**New here?** Read [CONTEXT.md](./CONTEXT.md) first — it is the domain glossary, and everything else
assumes its vocabulary. Then [docs/README.md](./docs/README.md) for the reading order.

---

## Prerequisites

| | Version | Notes |
|---|---|---|
| Node.js | 22 or later | Ships with npm 10+; the repo uses npm workspaces |
| Python | **3.12 exactly** | 3.14 lacks reliable ML wheels — see [conventions](./docs/conventions.md) |
| uv | latest | Manages the Python environment, and can install Python 3.12 for you |

The shipping target is **Windows**; development happens on Linux or Windows. See
[design-decisions.md §9c](./docs/design-decisions.md). Everything below is the same on both except
where marked.

### Installing the prerequisites

**Linux**

```bash
# Node — use your distro's package manager, or nvm
curl -fsSL https://astral.sh/uv/install.sh | sh
```

**Windows** (PowerShell)

```powershell
winget install OpenJS.NodeJS
winget install astral-sh.uv
```

You do **not** need to install Python separately — `uv` fetches 3.12 in the setup step below.
If you prefer to manage it yourself: `pyenv` on Linux, the python.org installer on Windows. The
version is the constraint, not how it gets there.

---

## Setup

Run both, once, from the repository root. Identical on Linux and Windows.

```bash
npm install
```

```bash
cd services/inference
uv sync --python 3.12
cd ../..
```

`uv sync` creates `services/inference/.venv` and installs the service plus its dev tools. If Python
3.12 is not on the machine, uv downloads it.

---

## Running the app

**Production-style — builds the UI and loads it from disk:**

```bash
npm run build
npm start
```

**Development — hot reload, needs two terminals:**

```bash
# terminal 1 — Vite dev server on port 5273
npm run dev --workspace @spectrapaint/ui
```

```bash
# terminal 2 — Electron, pointed at the dev server
npm run dev
```

The port is fixed rather than auto-incremented, so a collision fails loudly instead of Electron
quietly loading the wrong page. (Only the *UI* dev server has a fixed port — the inference service
deliberately takes an OS-assigned one.)

> **Windows:** both commands work in PowerShell, `cmd`, and Git Bash. Nothing here needs a
> Unix shell — if you hit a script that does, that is a bug worth reporting, per §9c.

---

## Checks

Run these before opening a pull request. CI runs the same set on Linux and Windows.

**JavaScript / TypeScript** — from the repository root:

```bash
npm run check           # lint, typecheck, format and test in one go
```

Or individually:

```bash
npm run lint
npm run typecheck
npm run format          # add :write to fix
npm test                # shell logic only — see design-decisions.md §9d
```

**Python** — from `services/inference`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

**The two gates** CI also runs, if you want to check before pushing:

```bash
cd services/inference
uv run python ../../tools/licence_gate.py     # dependency and model-weight licences
cd ../..
uv run --with "numpy>=2,<3" python spikes/latency/bench_render_loop.py --check
```

The second is the performance regression gate: it measures the per-shade render — the loop the
Customer watches — against a budget recorded in `spikes/latency/perf-baseline.json`. That budget is
calibrated to a 2-core CI runner, so **a busy or slower development machine can exceed it with
nothing actually wrong**. CI is the arbiter; locally it is a smoke check, useful mainly for seeing a
large regression before you push.

Prose in `*.md` is hand-wrapped and excluded from prettier on purpose.

`main` is protected: work on a branch per ticket and open a pull request. See
[conventions.md §7b](./docs/conventions.md).

---

## Layout

```
apps/desktop/        Electron main process and preload script
apps/ui/             React renderer
services/inference/  Python service — all image and model work
data/catalogue/      Shade data
models/              ONNX weights (fetched, never committed)
docs/                Decisions, spec, conventions, ADRs
spikes/              Throwaway measurement code
tools/               CI gates and repository tooling
```

Each directory has a `README.md` stating what belongs in it. Read it before adding files.

---

## Troubleshooting

**`npm start` opens a blank window.** The UI has not been built. Run `npm run build` first, or use
the two-terminal dev flow.

**`uv sync` cannot find Python 3.12.** Let uv install it: `uv python install 3.12`.

**Windows: the app launches but Windows Defender warns, or a component vanishes.** Expected, and
documented — SpectraPaint ships unsigned, and antivirus engines treat PyInstaller-bundled Python as
suspicious in itself. See [design-decisions.md §3](./docs/design-decisions.md).

**Windows: a firewall prompt on first launch.** The service binds to `127.0.0.1` and needs no
network access; declining the prompt is safe.
