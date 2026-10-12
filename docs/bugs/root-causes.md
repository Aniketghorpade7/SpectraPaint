# Shared root causes

Three defects in the pipeline account for most of the Dealer-testing bug list. Each per-bug document
links here rather than repeating the mechanism. Line numbers are at `31-wall-matte-over-claim` @
`64d7a61`; paths are relative to `services/inference/spectrapaint/` unless stated.

| Cause | One line | Bugs |
|---|---|---|
| [A](#a-the-alpha-matte-is-shaped-by-a-128128-grid) | The Alpha Matte is shaped by SegFormer's 128×128 grid, not by the photo | [3](./03-colour-faint-when-selected.md), [4](./04-tiled-bathroom-not-painted.md), [5](./05-left-wall-not-painted.md), [7/9](./07-sunlit-wall-paints-badly.md), [8](./08-kitchen-tiles-not-identified.md) |
| [B](#b-the-31-confidence-floor-deletes-sunlit-wall) | The #31 confidence floor deletes sunlit wall | [7/9](./07-sunlit-wall-paints-badly.md) |
| [C](#c-the-light-map-carries-everything-that-is-not-the-base-colour) | The Light Map carries everything that is not the Base Colour — stains and sunlight included | [2](./02-stains-survive-repaint.md), [7/9](./07-sunlit-wall-paints-badly.md) |

---

## A. The Alpha Matte is shaped by a 128×128 grid

**Symptom.** Square, stair-stepped edges and square holes/patches in the paint — visible on PDF pages
2, 4, 5, 6 and 7.

### Mechanism

1. **SegFormer's labels are coarse and are upsampled with nearest neighbour.** The checkpoint sees a
   512×512 squash of the photo and returns logits at stride 4, i.e. a 128×128 grid
   (`models/semantic-segformer-b0-ade20k/runtime.json`: `input_height: 512`, `output_stride: 4`).
   The argmax is taken **at 128×128** and the boolean maps are resized with nearest neighbour:

   ```python
   # segmentation/semantic.py:141-146
   # Resized as floats and thresholded back, because Pillow has no boolean mode. Nearest
   # neighbour, so a resized label map contains only labels that were actually predicted.
   wall = _resize_to(wall_small.astype(np.float32), shape, nearest=True) > 0.5
   excluded = _resize_to(excluded_small.astype(np.float32), shape, nearest=True) > 0.5
   confidence = _resize_to(probabilities[wall_index], shape, nearest=False)
   ceiling = _resize_to(ceiling_small.astype(np.float32), shape, nearest=True) > 0.5
   ```

   On a 1280×960 prepared photo each grid cell is 10×7.5 px, so every boundary of `wall`,
   `excluded` and `ceiling` is a staircase of 10-px steps. The module docstring
   (`semantic.py:111-117`) accepts this on the grounds that "the boundary is SAM 2's job and the
   refinement pass's job". Step 3 shows that SAM 2 isn't doing that job.

2. **Those grid masks write hard 0/1 values straight into the matte**, in `wall_alpha`
   (`segmentation/matte.py:227-265`):

   ```python
   confident_wall = regions.wall & (regions.wall_confidence >= SEMANTIC_OVERRULE_CONFIDENCE)
   alpha = np.where(
       confident_wall & ~regions.excluded, 1.0, alpha
   )  # :245-246  restore → grid squares of 1.0
   alpha = np.where(regions.excluded, 0.0, alpha)  # :250      exclusion → grid squares of 0
   alpha = np.where(
       _unvouched(regions, confident_wall), 0.0, alpha
   )  # :256      #31 floor, bounded by ~regions.wall (grid)
   alpha = soften_boundary(photo_u8, alpha)  # :258
   alpha = np.where(regions.excluded, 0.0, alpha)  # :263      re-imposed AFTER softening
   ```

   The last line is the worst one. Whatever softening `soften_boundary` did at a floor, door,
   window or ceiling boundary is overwritten by a nearest-upsampled grid mask. **Every wall ↔
   exclusion edge ends up as a razor-sharp 10-px staircase.** That breaks the rule in
   `docs/design-decisions.md` (~line 404): *"where a wall meets furniture, a window or the ceiling,
   the photograph genuinely is soft … a soft matte is what stops the render looking cut out"*.

3. **SAM 2 barely shapes the matte.** Its logits come back 256×256 and are upsampled bilinearly
   (`matte.py:139`), which is fine. But on the tested photos the logits are within ±2 (sigmoid
   0.12–0.88) on 77–100% of pixels, and the decoder's own `iou_scores` for the full 20+-point
   prompt set are 0.00–0.04. The score is discarded:

   ```python
   # segmentation/matte.py:127
   mask_logits, _iou = graphs.refiner_decoder.run({...})
   ```

   A PyTorch reference run gives similarly weak single-mask logits, so this comes from the
   checkpoint being used with `multimask_output=False` (`tools/export_onnx.py:310-325`), not from
   a broken export. Because SAM 2 is unsure everywhere, the grid-shaped restore/exclude steps decide
   the shape.

4. **The softening adds squares of its own.** `soften_boundary` (`matte.py:192-224`) hard-switches
   between core, band and exterior (`np.where(core, 1.0, np.where(band, sharpened, 0.0))`, `:224`).
   Its `erode`/`dilate` are repeated 3×3 rank filters (`imaging.py:19-32`,
   `image.filter(kernel(3))`), which grow and shrink regions as **squares** (Chebyshev distance),
   not discs. A concave corner in the matte becomes a right-angled notch.

### Evidence (measured on the PDF images at the 1280 px cap)

| Photo | Razor edges (jump > 0.5) lying exactly on 128-grid cell lines |
|---|---|
| Page 4 original | 81% |
| Page 6 original | 75% |
| Page 7 screenshot | 84% |

Scripts: session scratchpad `tiles_agent/edge_probe.py`, `sam_probe.py`, `torch_ref.py`.

### Method of fixing

Done in this order. Each step is measurable on its own against `data/fixtures/rooms/measured.toml`.

1. **Upsample probabilities, then argmax (semantic.py).** Resize the needed class-probability
   planes (`wall`, the four exclusions, `ceiling`) to photo resolution **bilinearly**, then take
   the argmax/threshold at photo resolution. Boundaries follow smooth probability contours
   instead of grid cells. Cost: five float planes at 1280×960 ≈ 25 MB transient, about 30 ms. To
   keep the "only labels actually predicted" property the docstring cares about, argmax over the
   upsampled planes of the *same* classes, never over a blend of labels.
2. **Exclusions as a soft ramp that stays 0 on the excluded side (matte.py).** Replace the hard
   re-imposition at `:263` with a feather that lies entirely on the wall side of the boundary:

   ```python
   excluded = regions.excluded  # photo-resolution argmax, from step 1
   spread = blur(excluded.astype(float32), r=round(min(shape) * EXCLUSION_FEATHER_FRACTION))
   ramp = np.clip(1.0 - 2.0 * spread, 0.0, 1.0)  # 0 at the boundary, 1 at r px into the wall
   alpha = np.where(excluded, 0.0, alpha * ramp)
   ```

   with a new named constant `EXCLUSION_FEATHER_FRACTION = 0.004` (about 4 px at 960 px short side)
   in matte.py's constants block (conventions §4). "Never paint a window" holds by construction:
   every excluded pixel is exactly 0, and the softness sits only in wall pixels next to it. Because
   `excluded` now comes from bilinearly upsampled probabilities (step 1), its boundary follows the
   probability contour rather than grid cells.
3. **Round morphology (imaging.py).** Add `erode_round`/`dilate_round` implemented as
   *blur-and-threshold*: a Gaussian blur of radius r (`ImageFilter.GaussianBlur`), thresholded at
   a low level to dilate or a high level to erode. That is isotropic, costs the same regardless of
   radius, and keeps the numpy+Pillow-only dependency rule (`imaging.py` docstring). Switch
   `soften_boundary` and `prompts.erosion_radius` users to it. Keep the square versions for
   `estimate_base_colour`, where the shape does not matter.
4. **Continuous band blend in `soften_boundary`.** Replace the three-zone `np.where` with a blend
   weight that falls off with distance from the edge level (the same blur-and-threshold
   machinery), so there is no step where band meets core.
5. **Use SAM 2's score.** Read `iou_scores` instead of discarding them. When the score is below
   `REFINER_TRUST_FLOOR` (new constant, start 0.3), lean on the step-1 upsampled semantic
   probability for the shape rather than on SAM's mushy logits. Log the score at `debug` so it
   shows up in the field. For the single-point Add tap, see [bug 4](./04-tiled-bathroom-not-painted.md)
   (multimask + best score).

**Docs to amend:** `semantic.py` / `matte.py` module docstrings (the "blocky staircase … is SAM 2's
job" claim is false on real photos); a new `docs/technical-difficulties.md` entry ("The matte's edges
were the semantic grid's edges"); an `docs/implementation-decisions.md` entry for the soft
exclusion ramp.

**Tests:**
- New unit test in `tests/segmentation/`: a synthetic 128-grid label map with a diagonal boundary.
  Assert that no more than 10% of matte razor edges sit on grid lines, and that no excluded-argmax
  pixel has alpha > 0.
- The fixture lane (`uv run pytest -m models`) must not regress `measured.toml`. Add an
  `edge_on_grid_fraction` metric per fixture with target ≤ 0.10.

---

## B. The #31 confidence floor deletes sunlit wall

**Symptom.** Sunlit wall is left unpainted: page 6's right wall and the sunlit parts of pages 4 and 7.

### Mechanism

```python
# segmentation/matte.py:53   WALL_CONFIDENCE_FLOOR = 0.9
# segmentation/matte.py:189
return (regions.wall_confidence < WALL_CONFIDENCE_FLOOR) & ~confident_wall & ~regions.wall
```

This returns true for any pixel whose argmax is **not** `wall` and whose wall probability is below
0.9. Such a pixel is set to 0 at `matte.py:256`, whatever SAM 2 thought. Sunlit wall (bright,
washed-out, low texture) is labelled `mirror` by this SegFormer-B0 checkpoint, so the floor removes it.

### Evidence

| Photo | Painted fraction, no floor | With floor 0.9 |
|---|---|---|
| Page 6, sunlit right wall (SegFormer: `mirror` 72%) | **0.79** | **0.11** |
| Page 6, whole frame | 0.626 | 0.467 |
| Page 4, right wall | 0.72 | 0.56 |

The floor's measured benefit (`data/fixtures/rooms/measured.toml` header and entries) is one
fixture: `windows-with-curtains` non-wall leakage 0.239 → 0.185. It moves `empty-corner` by 0.000
and `corner-with-clothesline` by 0.010.

### Method of fixing (decision 3)

1. **Expose `mirror` to the runtime.** Only five class indices are exported today
   (`tools/export_onnx.py:70` `SEMANTIC_CLASSES`, written to `runtime.json`). Add `mirror` (ADE20K
   index 27, looked up from the checkpoint's `id2label` as the exporter already does) to a new
   tuple `FLOOR_EXEMPT_CLASSES = ("mirror",)`, and have the exporter write it under a separate
   `runtime.json` key, so it is never mistaken for an exclusion. Regenerate with
   `tools/export_onnx.py --verify-only` or re-export. `models/` is fetched, not committed, so
   bump `models/manifest.toml`.
2. **Carry it in `SemanticRegions`** as `floor_exempt: np.ndarray` (HxW bool, upsampled like the
   others; bilinear after cause A step 1).
3. **Exempt it in `_unvouched`:**

   ```python
   return (
       (regions.wall_confidence < WALL_CONFIDENCE_FLOOR)
       & ~confident_wall
       & ~regions.wall
       & ~regions.floor_exempt
   )
   ```

4. **Re-measure.** Add the page-4 and page-6 originals as fixtures (`data/fixtures/rooms/`,
   provenance in `origin.md`, labels via `tools/fixtures/label_rooms.py`). Add a
   `sunlit_wall_recall` metric to `tests/api/test_walls.py`, defined like
   `test_shadowed_wall_stays_wall` but over the *brightest* labelled-wall pixels, target 0.80. Watch
   the two existing mirror fixtures (`dim-room-with-mirror.jpg`, `wood-doors-with-mirror.jpg`).
   They have no `.wall.png` labels yet; label them so mirror leakage is measured, not assumed.
5. **Revisit trigger:** if `windows-with-curtains` leakage goes back above 0.20, or a real mirror
   gets painted in a fixture, record it in `measured.toml` and reopen this decision.

**Accepted cost:** a real mirror is paintable again, as it was before #31.

---

## C. The Light Map carries everything that is not the Base Colour

**Symptom.** Stains show through the new Shade (bug 2). Sunlit patches render as blobs of a
different hue, and a sunlit wall's non-sunlit part renders in the wrong hue (bugs 7/9).

### Mechanism

1. **Per-channel division.** `render/engine.py:63-65`:

   ```python
   light_map = linear_photo / base_colour
   ```

   Everything that differs from the Base Colour, **in all three channels**, lands in the Light Map
   and is multiplied into the new Shade at `new_wall_of` (`engine.py:225-234`,
   `light_map * target_shade * light_tint`). That includes the stain's hue and the sun's hue as
   well as their brightness.
2. **The luminance-only escape hatch only opens for saturated bases.** `engine.py:67-73` blends
   toward luma/luma as the Base Colour's saturation rises from `_SATURATION_BLEND_START = 0.20` to
   `_SATURATION_BLEND_END = 0.60` (`:394-395`). Pale walls, the common case, keep the full
   per-channel ratio.
3. **Smoothing runs only where the wall is dark and noisy.** `_smooth_where_dark`
   (`engine.py:193-222`) weights by `(_SMOOTHING_LIT_LUMA - luma)` and local noise. Its docstring
   says outright that this *"lets a well-lit wall keep its stains"* (`:205`).
4. **The Base Colour is the mean of the 85th–90th luminance percentile** (`engine.py:496-505`,
   `_BASE_PERCENTILE = 90.0`, `_BASE_PERCENTILE_BAND = 5.0` at `:366-367`). If sun covers about
   10% or more of the wall, that band lies entirely on sunlit pixels, so the "Base Colour" becomes
   the sun-lit colour. The rest of the wall's Light Map then carries the old paint's hue relative
   to it.
5. **Per-channel clip at encode.** `render/luts.py:54-55` clips each channel to [0, 1]
   independently. An over-bright pixel (light map > 1 on a bright Shade) loses its top channel first,
   and the hue shifts toward the other two.
6. **The design accepted this on purpose.** `docs/design-decisions.md:326-332` says stains *"ride
   through the light map and get re-tinted by the new shade. That is knowingly accepted"*. Decision
   1 overturns that.

### Evidence: synthetic probe (session scratchpad `probe.py`)

Calls the pure `estimate_base_colour` / `light_map_of` / `render_many` on a 200×200 wall.

| Case | Light map at the defect | Rendered sRGB (wall → defect) |
|---|---|---|
| Cream wall, brown stain, pale-blue Shade (sun 5%) | stain (0.51, 0.45, 0.35) | (189,216,235) → **(140,151,146)**: grey-brown patch |
| Pale-blue wall, 5% warm sun, pale-blue Shade | sun (1.70, 1.35, 0.82) | (189,216,234) → **(240,246,214)**: pale-yellow blob (page 6) |
| Yellow wall, 20% clipped sun strip, orange Shade | base = (1.0, 0.96, 0.79), near white; rest of wall (0.87, 0.54, 0.07) | wall renders **(221,98,6)**, brown, while the strip renders the true (236,130,46) (page 7) |
| Yellow wall, 5% clipped strip, orange Shade | sun (1.71, 1.71, 1.71) | strip **(255,166,61)**: clipped, hue-shifted |

### Method of fixing

Covered in full in [bug 2](./02-stains-survive-repaint.md) (stain suppression) and
[bug 7/9](./07-sunlit-wall-paints-badly.md) (robust Base Colour, capped sun tint, hue-preserving
clip). They share one change to `light_map_of`: the Light Map is split into **luminance** (kept, with
shadows) and **chroma** (suppressed or capped). The rest is layered on top of that split.
