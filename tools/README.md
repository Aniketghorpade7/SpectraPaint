# tools

Repository tooling that CI runs and contributors can run by hand. Python 3.12, standard library
only where possible, and cross-platform — anything here may be run on Windows
(`design-decisions.md` §9c).

Not application code. Nothing in `apps/` or `services/` may import from here.

| | |
|---|---|
| `fetch_models.py` | Downloads the weights pinned in `models/manifest.toml` from their original upstream source, verifying sha256. Also prints the Actions cache key. |
| `licence_gate.py` | Fails the build when a dependency or a model weight carries a licence that is not approved. |
| `approved-licences.toml` | The licence policy. Adding a licence here is a deliberate, reviewable decision — read the file before you edit it. |

```bash
python tools/fetch_models.py            # fetch anything missing, verify everything
python tools/fetch_models.py --verify   # verify what is on disk, fetch nothing

cd services/inference                   # the gate reads licences from this environment
uv run python ../../tools/licence_gate.py
uv run python ../../tools/licence_gate.py --list   # print every licence found
```

Weights are fetched, never committed, and never mirrored anywhere we control. The SegFormer
checkpoint is under a non-commercial research licence: downloading it for development is fine,
re-hosting it would be redistribution. See `docs/design-decisions.md` §5 and §9b.
