"""
Turn the checkpoints in models/ into the `.onnx` graphs the service actually runs.

    python tools/export_onnx.py            # export anything missing, verify everything
    python tools/export_onnx.py --force    # re-export even if the .onnx is already there
    python tools/export_onnx.py --verify   # check what is on disk against PyTorch, export nothing
    python tools/export_onnx.py --fast     # the faster tier: same weights, smaller semantic input

Run it with the export environment active, which is the only place torch and transformers exist:

    cd services/inference
    uv sync --group export
    uv run python ../../tools/export_onnx.py

**This file is the boundary.** It is the one place in the repository allowed to import torch or
transformers; nothing under `spectrapaint/` may. That is ADR-0001's "PyTorch for development and
export, ONNX Runtime ships" expressed as a rule you can check with grep, and the reason is the
installer: PyTorch is several hundred megabytes that must never reach a Dealer's machine.

Three graphs come out, not two, because SAM 2 is split at its natural seam:

  semantic.onnx       SegFormer. Photo in, a score per ADE20K class per pixel out.
  sam2-encoder.onnx   SAM 2's image encoder. The expensive half, and it depends only on the photo,
                      so it runs **once per photo** (spikes/latency/RESULTS.md names this encode as
                      the per-photo cost that matters).
  sam2-decoder.onnx   SAM 2's prompt encoder and mask decoder. Cheap, and it takes the encoder's
                      output plus a set of point prompts, so it can be re-run with different
                      prompts — which is what makes trying a prompt set affordable now, and what
                      ticket #7 needs when it decodes one Wall Plane at a time.

Alongside each model a `runtime.json` is written: the resize and normalisation constants read out
of the checkpoint's own `preprocessor_config.json`, and for the semantic model the five ADE20K
class indices read out of its `config.json`. The service reads that file instead of re-deriving
any of it, so the numbers cannot drift from the weights they belong to and the runtime needs no
transformers to look them up.

**The faster tier** (issue #14) is the same weights exported at a smaller semantic input, written
as `semantic-fast.onnx` beside a `runtime-fast.json` that names it and carries the smaller sizes.
The service's tier selection reads that config, so "faster" is one file read and never a branch in
the inference call site. SAM 2 has no smaller variant: its positional embeddings and neck are
pinned to 1024x1024 and refuse every other input (verified by export), so the refiner's
runtime-fast.json is deliberately the same graphs as its base one — written anyway, so what
"faster" means for every model stays inspectable in one place.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"

try:
    import numpy as np
    import onnxruntime
    import torch
    from torch import nn
    from transformers import Sam2Model, SegformerForSemanticSegmentation
except ModuleNotFoundError as missing:
    raise SystemExit(
        f"{missing.name} is not installed, so nothing can be exported. This tool needs the\n"
        "export environment, which is the only place torch and transformers live:\n"
        "    cd services/inference && uv sync --group export"
    ) from None

# The five ADE20K classes the pipeline uses, named in docs/specs/v1-spectrapaint.md and
# design-decisions.md §5. Their *indices* are never written here — they are looked up in the
# checkpoint's own label map, so a different checkpoint cannot silently shift them.
SEMANTIC_CLASSES = ("wall", "floor", "ceiling", "windowpane", "door")

# Model ids, matching models/manifest.toml.
SEMANTIC_ID = "semantic-segformer-b0-ade20k"
REFINER_ID = "refiner-sam2-hiera-tiny"

# The ONNX opset, pinned rather than left to torch's default so a torch upgrade cannot quietly
# change the graphs under us.
OPSET = 18

# The faster tier's semantic input (issue #14). The checkpoint is finetuned at 512, but SegFormer
# accepts any 32-multiple; 384 is a quarter fewer pixels through the encoder and a proportionally
# smaller upsample, for a tier the Dealer chooses in Settings. SAM 2 has no equivalent: its
# positional embeddings and neck are pinned to 1024 and refuse every other input, so the faster
# tier's refiner is deliberately the same graphs (see the module docstring).
FAST_SEMANTIC_SIZE = 384

# How many point prompts the decoder graph accepts. Fixed rather than dynamic, deliberately: a
# static graph is faster in ONNX Runtime, and SAM's own convention already handles a variable
# number of prompts inside a fixed slot — a point labelled -1 is padding and contributes nothing.
# The pipeline pads to this width, so one graph serves a prompt set of any size up to it.
MAX_PROMPT_POINTS = 32

# Tolerances for the parity check between PyTorch and ONNX Runtime. These are logits, not
# probabilities, and the two runtimes reduce in different orders, so bitwise equality is not the
# thing to ask for. What matters is that no decision flips.
PARITY_ABSOLUTE = 2e-3
PARITY_RELATIVE = 1e-3


# The parity check feeds a pseudo-photo, never zeros. An all-zero input takes the same path
# through every branch and can make a broken export look faithful; realistic values exercise the
# attention and normalisation the graphs actually spend their time in. Seeded, so a failure is
# reproducible and two runs are comparable.
PARITY_SEED = 20260820


def example_input(constants):
    """One batch of pseudo-photo pixels, normalised exactly as the service will normalise them."""
    generator = torch.Generator().manual_seed(PARITY_SEED)
    pixels = torch.rand(
        1,
        3,
        constants["input_height"],
        constants["input_width"],
        generator=generator,
        dtype=torch.float32,
    )
    mean = torch.tensor(constants["image_mean"], dtype=torch.float32).view(1, 3, 1, 1)
    std = torch.tensor(constants["image_std"], dtype=torch.float32).view(1, 3, 1, 1)
    return (pixels - mean) / std


def display(path):
    try:
        return path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return path.resolve()


def preprocessing_of(model_dir):
    """The resize and normalisation constants, from the checkpoint's own preprocessor config.

    Read rather than transcribed: these numbers belong to the weights, and a copy of them in our
    source is a copy that can drift. `size` is spelled two ways upstream — a bare integer by
    SegFormer, a {height, width} table by SAM 2 — so both are normalised to a height and width
    pair here, which is the one shape the service then has to handle.
    """
    with open(model_dir / "preprocessor_config.json", "rb") as f:
        config = json.load(f)

    size = config["size"]
    if isinstance(size, dict):
        height, width = size["height"], size["width"]
    else:
        height = width = size

    return {
        "input_height": height,
        "input_width": width,
        "image_mean": config["image_mean"],
        "image_std": config["image_std"],
        # SegFormer's config omits this; 1/255 is what `do_rescale` means in both processors.
        "rescale_factor": config.get("rescale_factor", 1.0 / 255.0),
    }


def semantic_class_indices(model_dir):
    """Map our five class names to the checkpoint's own label indices.

    ADE20K's ordering is a property of the checkpoint, not folklore, so it is read from
    `config.json`. Upstream writes some labels as comma-separated synonyms ("windowpane, window"),
    so only the first name is compared. A checkpoint missing one of the five is refused: a
    pipeline that cannot find `wall` has nothing to offer, and guessing an index would produce a
    confidently wrong matte.
    """
    with open(model_dir / "config.json", "rb") as f:
        id2label = json.load(f)["id2label"]

    by_name = {label.split(",")[0].strip(): int(index) for index, label in id2label.items()}
    missing = [name for name in SEMANTIC_CLASSES if name not in by_name]
    if missing:
        raise SystemExit(
            f"  FAIL {model_dir.name}: its label map has no {', '.join(missing)}.\n"
            "       This checkpoint does not label the classes the pipeline needs."
        )
    return {name: by_name[name] for name in SEMANTIC_CLASSES}


def write_runtime_json(model_dir, payload, name="runtime.json"):
    """The sidecar the service reads, so nothing at runtime needs transformers."""
    path = model_dir / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"  wrote {display(path)}")


def parity(name, expected, actual):
    """Compare one PyTorch output against its ONNX Runtime counterpart."""
    if expected.shape != actual.shape:
        raise SystemExit(
            f"  FAIL {name}: PyTorch returns {expected.shape}, the exported graph "
            f"returns {actual.shape}."
        )
    difference = float(np.max(np.abs(expected - actual)))
    tolerance = PARITY_ABSOLUTE + PARITY_RELATIVE * float(np.max(np.abs(expected)))
    verdict = "ok" if difference <= tolerance else "FAIL"
    print(f"  parity {name}: max difference {difference:.2e} (tolerance {tolerance:.2e}) {verdict}")
    if difference > tolerance:
        raise SystemExit(
            f"  FAIL {name}: the exported graph does not reproduce the PyTorch model.\n"
            "       An export that runs but computes something else is worse than no export."
        )


def run_onnx(path, inputs):
    """Run an exported graph once, and return its outputs in order."""
    session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return session.run(None, inputs)


def export_graph(
    module, example_inputs, destination, input_names, output_names, force, verify_only
):
    """Write one graph, unless it is already there and nothing asked for a rewrite.

    Returns False when the graph is absent and this run was told not to write one — the caller
    reports that as a missing export rather than treating it as success.
    """
    if verify_only or not (force or not destination.exists()):
        if destination.exists():
            return True
        print(f"  MISSING: {display(destination)}")
        return False

    torch.onnx.export(
        module,
        example_inputs,
        str(destination),
        input_names=input_names,
        output_names=output_names,
        opset_version=OPSET,
        dynamo=False,
    )
    print(f"  exported {display(destination)}")
    return True


def export_semantic(force, verify_only, fast=False):
    """SegFormer: photo in, one score per ADE20K class per pixel out.

    The base graph is fixed at the checkpoint's own 512x512 input. Boundary quality does not come
    from this resolution — the mask is upsampled and its boundary band refined at full resolution
    later (design-decisions.md §5) — so a dynamic input size would buy nothing and cost speed.

    The faster tier exports the same weights at 384x384 into a `-fast` sibling, with its own
    runtime config naming it and carrying the smaller sizes (issue #14).
    """
    model_dir = MODELS_DIR / SEMANTIC_ID
    destination = model_dir / ("semantic-fast.onnx" if fast else "semantic.onnx")
    print(f"{SEMANTIC_ID}{' (faster tier)' if fast else ''}")

    constants = preprocessing_of(model_dir)
    if fast:
        constants = {
            **constants,
            "input_height": FAST_SEMANTIC_SIZE,
            "input_width": FAST_SEMANTIC_SIZE,
        }
    classes = semantic_class_indices(model_dir)

    model = SegformerForSemanticSegmentation.from_pretrained(model_dir).eval()
    example = example_input(constants)

    if not export_graph(
        model, (example,), destination, ["pixel_values"], ["logits"], force, verify_only
    ):
        return False

    with torch.no_grad():
        expected = model(pixel_values=example).logits.numpy()
    (actual,) = run_onnx(destination, {"pixel_values": example.numpy()})
    parity("semantic logits", expected, actual)

    if not verify_only:
        write_runtime_json(
            model_dir,
            {
                "graph": destination.name,
                "classes": classes,
                # Written for the service's benefit: SegFormer's logits come back at a quarter of
                # the input side, and the code that upsamples them should not have to learn that
                # by having tried it.
                "output_stride": constants["input_height"] // expected.shape[-2],
                **constants,
            },
            name="runtime-fast.json" if fast else "runtime.json",
        )
    return True


class Sam2Encoder(nn.Module):
    """SAM 2's image encoder, as a module with one tensor in and three out.

    A wrapper because `torch.onnx.export` traces a `forward`, and the encoder is reached through a
    method on the full model rather than being a `forward` of its own.
    """

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, pixel_values):
        return tuple(self.model.get_image_embeddings(pixel_values))


class Sam2Decoder(nn.Module):
    """SAM 2's prompt encoder and mask decoder: image features plus prompts in, mask logits out.

    `multimask_output=False` on purpose. SAM 2 can return several candidate masks and leave the
    choice to the caller, but the caller here already knows what it wants — the semantic pass has
    said "wall" — so the ambiguity SAM 2 offers to resolve is already resolved, and choosing among
    candidates would only add a way to choose wrong.
    """

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, feature_0, feature_1, feature_2, point_coords, point_labels):
        outputs = self.model(
            image_embeddings=[feature_0, feature_1, feature_2],
            input_points=point_coords,
            input_labels=point_labels,
            multimask_output=False,
        )
        return outputs.pred_masks, outputs.iou_scores


def export_refiner(force, verify_only, fast=False):
    """SAM 2, as two graphs: the once-per-photo encode, and the re-runnable decode.

    The faster tier re-exports nothing: SAM 2's positional embeddings and neck are pinned to
    1024x1024 and refuse every other input, so its runtime-fast.json is deliberately the base
    graphs — written anyway, so the tier's meaning stays inspectable in one place (issue #14).
    """
    model_dir = MODELS_DIR / REFINER_ID
    print(f"{REFINER_ID}{' (faster tier)' if fast else ''}")

    if fast:
        base = model_dir / "runtime.json"
        if not base.is_file():
            raise SystemExit(
                f"  FAIL {model_dir.name}: no runtime.json beside the base graphs.\n"
                "       The faster tier's refiner is the same graphs, so the base export must "
                "exist first — run the export without --fast."
            )
        with open(base, "rb") as f:
            payload = json.load(f)
        write_runtime_json(model_dir, payload, name="runtime-fast.json")
        return True

    encoder_path = model_dir / "sam2-encoder.onnx"
    decoder_path = model_dir / "sam2-decoder.onnx"

    constants = preprocessing_of(model_dir)
    model = Sam2Model.from_pretrained(model_dir).eval()
    photo = example_input(constants)
    feature_names = ["feature_0", "feature_1", "feature_2"]

    encoder = Sam2Encoder(model).eval()
    if not export_graph(
        encoder, (photo,), encoder_path, ["pixel_values"], feature_names, force, verify_only
    ):
        return False

    with torch.no_grad():
        expected_features = [tensor.numpy() for tensor in encoder(photo)]
    actual_features = run_onnx(encoder_path, {"pixel_values": photo.numpy()})
    for name, expected, actual in zip(
        feature_names, expected_features, actual_features, strict=True
    ):
        parity(f"encoder {name}", expected, actual)

    # A prompt set of one positive point at the centre is enough to trace the graph. Padding
    # points carry label -1, SAM's own convention for "not a point", which is what lets a fixed
    # graph serve a prompt set of any size up to MAX_PROMPT_POINTS.
    # Neither prompt is centred, and one is negative: a graph that transposed x and y, or ignored
    # everything past the first point, would still look correct if the only prompt sat at the
    # exact middle of a square image.
    width, height = constants["input_width"], constants["input_height"]
    coords = torch.zeros(1, 1, MAX_PROMPT_POINTS, 2, dtype=torch.float32)
    coords[0, 0, 0] = torch.tensor([width * 0.30, height * 0.55])
    coords[0, 0, 1] = torch.tensor([width * 0.70, height * 0.20])
    labels = torch.full((1, 1, MAX_PROMPT_POINTS), -1, dtype=torch.int32)
    labels[0, 0, 0] = 1
    labels[0, 0, 1] = 0

    decoder = Sam2Decoder(model).eval()
    features = [torch.from_numpy(f) for f in expected_features]

    if not export_graph(
        decoder,
        (*features, coords, labels),
        decoder_path,
        [*feature_names, "point_coords", "point_labels"],
        ["mask_logits", "iou_scores"],
        force,
        verify_only,
    ):
        return False

    with torch.no_grad():
        expected_masks, expected_iou = decoder(*features, coords, labels)
    actual_masks, actual_iou = run_onnx(
        decoder_path,
        {
            **{name: f.numpy() for name, f in zip(feature_names, features, strict=True)},
            "point_coords": coords.numpy(),
            "point_labels": labels.numpy(),
        },
    )
    parity("decoder mask logits", expected_masks.numpy(), actual_masks)
    parity("decoder iou scores", expected_iou.numpy(), actual_iou)

    if not verify_only:
        write_runtime_json(
            model_dir,
            {
                "encoder_graph": encoder_path.name,
                "decoder_graph": decoder_path.name,
                "max_prompt_points": MAX_PROMPT_POINTS,
                "padding_point_label": -1,
                "mask_height": int(expected_masks.shape[-2]),
                "mask_width": int(expected_masks.shape[-1]),
                **constants,
            },
        )
    return True


def main():
    parser = argparse.ArgumentParser(description="Export the pinned checkpoints to ONNX.")
    parser.add_argument(
        "--force", action="store_true", help="Re-export even if the .onnx already exists"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check the exported graphs against PyTorch without exporting",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Export the faster tier: the same weights at a smaller semantic input",
    )
    args = parser.parse_args()

    for model_id in (SEMANTIC_ID, REFINER_ID):
        if not (MODELS_DIR / model_id / "model.safetensors").exists():
            raise SystemExit(
                f"{model_id} is not on disk. Fetch the weights first:\n"
                "    python tools/fetch_models.py"
            )

    results = [
        export_semantic(args.force, args.verify, fast=args.fast),
        export_refiner(args.force, args.verify, fast=args.fast),
    ]
    print()
    if all(results):
        print("All graphs exported and matching their PyTorch originals.")
        return 0
    print("Some graphs are missing. Run without --verify to export them.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
