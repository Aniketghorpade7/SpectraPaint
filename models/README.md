# models

Downloaded and ONNX-exported model weights. Not committed - see .gitignore.

Record the licence of every shipped weight.

## What lives here

Each model directory holds the fetched checkpoint (`model.safetensors`, `config.json`,
`preprocessor_config.json` — pinned by `models/manifest.toml`), the exported graphs the service
runs, and the `runtime.json` the service reads instead of re-deriving any constant. Everything
here is produced by two tools, never by hand:

    python tools/fetch_models.py        # fetch the pinned checkpoints
    python tools/export_onnx.py         # export the graphs and write runtime.json

## The faster tier: `-fast` variants (issue #14)

The Dealer can choose a quality tier in Settings (faster vs better). The tier selects a
*runtime config file*, and the config names the graphs and input sizes that belong to it — so a
variant is one file read, never a branch in the inference call site:

    runtime.json        the better tier (the base export)
    runtime-fast.json   the faster tier, when an exported variant exists

A model with no `runtime-fast.json` serves the base model under the faster tier, and the service
logs a warning — a quiet fallback would hide exactly the difference the tier exists to make.

Produce the faster tier with:

    cd services/inference && uv sync --group export
    uv run python ../../tools/export_onnx.py --fast --force

Concretely, the faster tier means:

- **Semantic (SegFormer):** the same weights exported at 384×384 (`semantic-fast.onnx`) instead
  of 512×512 — a quarter fewer pixels through the encoder, and a proportionally smaller upsample.
- **Refiner (SAM 2):** unchanged, deliberately. SAM 2's positional embeddings and neck are pinned
  to 1024×1024 and refuse every other input, so its `runtime-fast.json` is the same graphs as its
  base one — written anyway, so what "faster" means for every model stays inspectable in one
  place.
