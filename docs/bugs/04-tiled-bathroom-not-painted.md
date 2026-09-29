# Bug 4: tiled walls in a bathroom can't be painted

| | |
|---|---|
| **Area** | Segmentation (`services/inference/spectrapaint/segmentation/`) and the Add tool |
| **Severity** | Medium: a whole room type (bathrooms, kitchens) is only partly paintable |
| **Confidence** | Likely: measured on the page-1 screenshot, which already carries paint |
| **Source** | [SpectrapaintBugs.pdf](./SpectrapaintBugs.pdf), page 1, item 4 ("Still not able to [paint] some tiles type room") |
| **Root cause** | Local (no tile class; tiles labelled `floor`) + [A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid) |
| **Proposed issue** | Issue 6, "Add-tap quality: tiles and hidden walls" ([README](./README.md#proposed-issues)) |

## What it is

In a bathroom with half-height grey wall tiles, only the plain plaster wall above the tiles on one side
gets the Shade. The tiled band, and some of the plaster on the other side, stay unpainted.

## Root cause

1. **The checkpoint has no tile class.** ADE20K's 150 classes include no "tile"; the runtime uses five
   (`models/semantic-segformer-b0-ade20k/runtime.json`: `wall, floor, ceiling, windowpane, door`;
   `semantic.py:33`, `EXCLUDED_CLASSES = ("floor", "ceiling", "windowpane", "door")`). Nothing in
   the code rejects tiles specifically.
2. **Grey wall tiles are labelled `floor`.** Measured: 35% of the right tile band and 19% of the left
   are argmax `floor`. `floor` is a **hard exclusion**, applied twice after softening
   (`segmentation/matte.py:250`, `:263`). It is also a source of negative prompts
   (`segmentation/prompts.py:143`, `sample_grid(erode(regions.excluded, …))`), so SAM 2 is actively
   told the tiles are not the wall. No floor-confidence setting can bring them back. The right tiles end
   up about 26% covered.
3. **Half-height tiling splits the wall.** The tile/plaster boundary is a strong horizontal edge, and
   `split.py` can turn it into two planes. Part of what's missing on page 1 may be a plane that wasn't
   assigned a Shade rather than one that wasn't detected (61% of the left and back tiles were covered).
4. **Grid-shaped edges** where tile meets floor (cause A).

**Scope:** neither `docs/specs/v1-spectrapaint.md` nor `docs/design-decisions.md` mentions tiles. The
nearest rule is design-decisions §5: *"The test is 'is this wall material?', never 'does this look like
the rest of the wall?'"*

## Decision (grilling decision 4)

**Tiles are paintable in V1 only via the Add tap, as their own Wall Plane.** No automatic tile
detection in V1: treating `floor`/`cabinet`/`refrigerator` labels as wall was rejected, because #31 and
technical difficulty #26 found this checkpoint's labels unreliable. A tiled plane takes its own Shade,
which suits the fact that tile paint is often a different product. Long term, add a `tile` class to the
custom model.

## Method of fixing

The Add tap already ignores semantic labels. `add_plane`
(`segmentation/corrections.py:213-275`) decodes SAM 2 from the tap alone, with no exclusions and no
#31 floor. So a tap on tiles works today in principle. What fails in practice is **the quality of a
single-point SAM 2 mask**, which is weak with `multimask_output=False`.

### Step 1: multimask decoding for the single-point Add tap

The rationale in `tools/export_onnx.py:310-315` for single-mask output is: *"the caller here already
knows what it wants — the semantic pass has said 'wall' — so the ambiguity SAM 2 offers to resolve is
already resolved"*. That holds for the automatic pass. It does **not** hold for a single tap, which is
exactly the ambiguous case SAM 2's three candidates (sub-part / part / whole) exist for.

1. `tools/export_onnx.py`: export a second decoder, `Sam2DecoderMulti`, identical except
   `multimask_output=True`, to `sam2-decoder-multi.onnx`. Add `"decoder_multi_graph"` to the refiner's
   `runtime.json`. Bump `models/manifest.toml`, and check the licence gate (`tools/licence_gate.py`).
2. `runtime/graphs.py`: load it as `graphs.refiner_decoder_multi`, lazily, since only corrections use it.
   Warm it up after the single decoder.
3. `segmentation/matte.py`: a new `decode_alpha_best(graphs, features, prompts, shape) -> tuple[np.ndarray, float]`.
   Run the multi decoder, then pick the candidate with the highest `iou_scores`, **preferring the larger
   mask when scores are within `_MULTIMASK_SCORE_TIE = 0.05`**, because a Dealer tapping a wall means
   the whole surface. Return the score too.
4. `corrections.add_plane`: use `decode_alpha_best`. If the best score is below
   `ADD_TAP_MIN_SCORE = 0.5`, still add the plane (never dead-end), but return a plain note:
   *"That wall was hard to outline. Tap again on a clearer part of it to improve it."*

### Step 2: let a second tap grow a plane

Today a tap that lands on an existing plane raises `PointAlreadyCovered` (`corrections.py:118-128`).
For a tiled band that came back partial, the natural move is to tap the missed part. The Add tool
should decode from **all taps so far on this plane** as positives, which lets SAM 2 refine. Store the
tap list on `WallPlane` (a new optional field), and have the Add route accept "extend plane X".
That's a REST contract change (test seam 1). If it's too large for this issue, split it into a follow-up.

### Step 3: soft matte (cause A)

The Add tool shares `soften_boundary`, so the round morphology and continuous band from
[root cause A](./root-causes.md#method-of-fixing) (steps 3-4) remove the square notches on added planes too.

### Step 4: tile planes render well

- The Base Colour is grouped by tint (`engine.py:545-606`), so a grey tile plane gets its own base, which
  is correct.
- Grout lines are a few pixels wide at 1280 px, so they're "texture" under
  `_STAIN_TEXTURE_RADIUS_FRACTION` ([bug 2](./02-stains-survive-repaint.md)) and survive. Tile-to-tile
  colour variation is mid-frequency and gets suppressed. That's what painted tiles look like, so it's
  the right outcome.

### Step 5: record the scope

- `docs/specs/v1-spectrapaint.md`: add "Tiled walls: not detected automatically in V1; the Dealer adds
  them with one tap, and they become their own Wall Plane".
- `docs/handoff/custom-wall-segmentation-model.md`: add `tile` to the planned label set
  (`wall · floor · ceiling · window · door · other` today).
- `CONTEXT.md`: no new term needed. A tiled surface is a Wall Plane.

## Tests

- **Fixture:** add a tiled-bathroom **original** photo to `data/fixtures/rooms/`, with its `.wall.png`
  labelled so that tiles count as wall. Record `add_tap_recall` for a scripted tap on the tiles, with a
  target of 0.80. Page 1 is a screenshot with paint already on it and can't be used; an original is needed.
- `tests/api/test_corrections.py`: with a stub multi-decoder returning three candidates, assert that the
  highest-scoring candidate is picked, that ties go to the larger one, and that a low score still adds
  the plane and returns the note.
- `tests/api/test_walls.py::test_the_add_tool_grows_a_plane_from_a_missed_wall`: extend it to the tiled
  fixture.

## Acceptance criteria

- [ ] One tap on a tiled band adds a Wall Plane covering ≥ 80% of it on the tiled fixture.
- [ ] The tiled plane takes a Shade independently of the plaster above it.
- [ ] A low-confidence tap still adds a plane and shows a plain-language note that names no model.
- [ ] Spec and handoff doc record the tile scope.

## Related

[Bug 8](./08-kitchen-tiles-not-identified.md) (kitchen tiles, same fix); [bug 5](./05-left-wall-not-painted.md)
(the Add tap is also the answer for walls behind shelving).
