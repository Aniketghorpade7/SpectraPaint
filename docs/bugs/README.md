# Bugs: Dealer testing, September 2026

**Status:** Diagnosed. Product decisions taken 2026-09-29 (grilling session). Not yet filed as GitHub
issues; the [proposed issues](#proposed-issues) below are written so they can be pasted in as they are.

**Source report:** [SpectrapaintBugs.pdf](./SpectrapaintBugs.pdf), "Spectrapaint Remaining Issues", 9 items
across 7 pages.

**Code reviewed:** branch `31-wall-matte-over-claim` @ `64d7a61`. All `file:line` references in this
section are at that commit.

## How the diagnosis was done

- **Wall detection:** the real pipeline (`semantic_regions` → `prompts_for` → `decode_alpha` →
  `wall_alpha` → split) was run on images extracted from the PDF, at the 1280 px preparation cap. Pages
  4 and 6 contain the **original** photos, so those results are the cleanest. Pages 1, 2, 5 and 7 are
  screenshots that already carry paint, so treat those numbers as indicative. The #31 floor was A/B
  tested (0.9 vs off), and a PyTorch reference run checked the SAM 2 ONNX export.
- **Render:** a synthetic probe calling the pure `estimate_base_colour` / `light_map_of` / `render_many`
  on walls with a stain patch and a sunlit strip. ΔE00 figures are CIEDE2000 on the rendered sRGB.
- **UI:** the Consultation layout was rebuilt in headless Chrome at 1280×720 and the frame, stage and
  image boxes measured. The fix was prototyped the same way.
- Probe scripts were kept in the session scratchpad and aren't committed. Anything a fix needs
  becomes a fixture or a test (see each bug's **Tests** section).

## Bug index

| # | Symptom (as reported) | PDF page | Root cause | Document | Issue |
|---|---|---|---|---|---|
| 1 | Images get zoomed after uploading | 1 | CSS frame taller than the stage; EXIF not applied | [01](./01-photo-zoomed-after-upload.md) | 2 |
| 2 | Stains remain after painting | 1 | [C](./root-causes.md#c-the-light-map-carries-everything-that-is-not-the-base-colour): per-channel Light Map | [02](./02-stains-survive-repaint.md) | 5 |
| 3 | Wall colour faint when selected / at edges | 1 | White selection wash; armed tool over render; soft plane-edge coverage | [03](./03-colour-faint-when-selected.md) | 2, 4 |
| 4 | Tiled room can't be painted | 1 | Tiles labelled `floor` (hard exclusion); no tile class; [A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid) | [04](./04-tiled-bathroom-not-painted.md) | 6 |
| 5 | Could not paint left wall | 2 | Wall behind shelving labelled `wardrobe`; [A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid) | [05](./05-left-wall-not-painted.md) | 6, 4 |
| 6 | Edit menu buttons don't work | 3 | Electron default menu; no undo history | [06](./06-edit-menu-does-nothing.md) | 3 |
| 7 | Not painting well with sunlight on the wall | 4 | [B](./root-causes.md#b-the-31-confidence-floor-deletes-sunlit-wall) + [A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid) + [C](./root-causes.md#c-the-light-map-carries-everything-that-is-not-the-base-colour) | [07](./07-sunlit-wall-paints-badly.md) | 1, 4, 5 |
| 8 | Could not identify the tiles | 5 | Tiles labelled `refrigerator`/`cabinet`; [A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid) | [08](./08-kitchen-tiles-not-identified.md) | 6 |
| 9 | Again not painting well with sunlight | 6, 7 | Same as 7 | [07](./07-sunlit-wall-paints-badly.md) | 1, 4, 5 |

**Three shared root causes** account for most of the list. See [root-causes.md](./root-causes.md):

- **A.** The Alpha Matte is shaped by SegFormer's 128×128 grid (blocky edges, square holes).
- **B.** The #31 confidence floor deletes sunlit wall that the checkpoint mislabels `mirror`.
- **C.** The Light Map carries every deviation from the Base Colour, per channel: stains, sun colour,
  and a sun-skewed Base Colour.

## Decisions (grilling log, 2026-09-29)

| # | Question | Decision |
|---|---|---|
| 1 | What does a repaint promise? | **"Your wall, freshly painted."** Stains and patches are suppressed by default; lighting and shadows kept. The strength is a named constant; no Dealer slider in V1. Amend design-decisions §6. |
| 2 | How should sunlit patches render? | **Warm, but capped:** keep about 30% of the sun's tint; the rest is brightness only. |
| 3 | The #31 confidence floor vs sunlit walls | **Exempt `mirror`, then re-measure** with sunlit fixtures. Revisit if `windows-with-curtains` leakage goes back above 0.20. Real mirrors become paintable again (accepted). |
| 4 | Are tiles in V1 scope? | **Paintable via the Add tap only**, as their own Wall Plane. No automatic tile detection in V1. |
| 5 | What did "edge selected" mean in bug 3? | Unknown. **Fix all three** faint-colour paths. |
| 6 | Edit menu | **Custom menu + Undo/Redo for Shade and wall choice** within an open Consultation. Corrections aren't undoable in V1. Reload/DevTools removed from packaged builds. |
| 7 | Walls hidden behind shelving | **Add tap plus a plain note** to the Dealer. |
| – | Soft vs hard exclusion edges | Already settled by design-decisions §6 (~line 404): wall↔window/furniture/ceiling edges are soft. The exclusion ramp stays 0 on the excluded side. |
| – | EXIF orientation | Technical call: always apply `ImageOps.exif_transpose`, and display the prepared photo. |

## Proposed issues

Six issues, ordered so each one can be reviewed and measured on its own. Suggested labels: `bug` plus
the area.

### Issue 1: Exempt `mirror` from the #31 wall-confidence floor, and measure sunlit-wall recall

- **Labels:** `bug`, `segmentation`
- **Covers:** bugs 7, 9 (part)
- **Branch:** finish on `31-wall-matte-over-claim`, since it changes that branch's floor.
- **Summary:** SegFormer labels sunlit wall `mirror`, and `_unvouched` (`matte.py:189`) deletes it:
  page-6 sunlit-wall coverage is 0.79 → 0.11. Export `mirror` under a separate runtime key, exempt it
  from the floor, add the page-4/page-6 originals as fixtures with a `sunlit_wall_recall` metric, and
  label the two existing mirror fixtures.
- **Method:** [root-causes.md → B](./root-causes.md#b-the-31-confidence-floor-deletes-sunlit-wall).
- **Acceptance:** `sunlit_wall_recall` ≥ 0.80 on both sunlit fixtures; `windows-with-curtains` leakage
  ≤ 0.20; `measured.toml` updated with the reasoning in the commit.
- **Depends on:** nothing.

### Issue 2: UI: fit the photo to the stage, upright photos, and no washed-out walls

- **Labels:** `bug`, `ui`, `desktop`
- **Covers:** bug 1, bug 3 (paths 1–2)
- **Summary:** the frame grows taller than the stage and is clipped (container-query fix). Apply EXIF
  orientation and display the prepared photo. Show the chosen wall with an outline instead of a 45%
  white wash. Disarm correction tools when a Shade is applied, and never show the wash over a render.
- **Method:** [01](./01-photo-zoomed-after-upload.md#method-of-fixing),
  [03 → paths 1–2](./03-colour-faint-when-selected.md#method-of-fixing).
- **Acceptance:** the checklists in [01](./01-photo-zoomed-after-upload.md#acceptance-criteria) and
  [03](./03-colour-faint-when-selected.md#acceptance-criteria) (UI items).
- **Depends on:** nothing. Includes a small REST addition (the prepared photo before the first render).

### Issue 3: Replace Electron's default menu, and add Undo/Redo for Shades

- **Labels:** `bug`, `desktop`, `ui`
- **Covers:** bug 6
- **Summary:** add an `app-menu.ts` template (no Reload/DevTools in packaged builds), menu⇄renderer IPC
  channels, a pure `history.ts` for `{target, assignments}` snapshots, and a single `repaint()` helper
  in `useConsultation`.
- **Method:** [06](./06-edit-menu-does-nothing.md#method-of-fixing).
- **Acceptance:** [06 → acceptance criteria](./06-edit-menu-does-nothing.md#acceptance-criteria).
- **Depends on:** nothing.

### Issue 4: Soft Alpha Matte: stop the 128-grid staircase and square holes

- **Labels:** `bug`, `segmentation`
- **Covers:** root cause A; bugs 3 (path 3), 5, 7, 8, 9 (part)
- **Summary:** upsample class probabilities bilinearly before the argmax; replace the hard post-softening
  exclusion with a ramp that is 0 on the excluded side; round (blur-and-threshold) morphology; a
  continuous band blend; read SAM 2's `iou_scores`; full coverage where planes meet (a shared
  `resolve_exclusive`), including wall vs ceiling.
- **Method:** [root-causes.md → A](./root-causes.md#method-of-fixing),
  [03 → path 3](./03-colour-faint-when-selected.md#path-3-full-coverage-where-planes-meet-service).
- **Acceptance:** `edge_on_grid_fraction` ≤ 0.10 on every fixture; no excluded-argmax pixel with alpha
  > 0; boundary coverage ≥ 0.99; no `measured.toml` regression.
- **Depends on:** Issue 1 (so re-measuring happens once, against the new floor).

### Issue 5: Render: cover stains, and paint sunlit walls in the Shade's own hue

- **Labels:** `bug`, `render`
- **Covers:** root cause C; bugs 2, 7, 9 (part)
- **Summary:** split the Light Map into shading and chroma; suppress mid-frequency blotches and local
  chroma (stains); a sun-robust Base Colour (hue-agreeing pixels only); keep about 30% of the sun's tint
  in highlights; hue-preserving highlight roll-off; handle clipped photo pixels. Amend design-decisions §6.
- **Method:** [02](./02-stains-survive-repaint.md#method-of-fixing),
  [07 → part 2](./07-sunlit-wall-paints-badly.md#part-2-paint-it-the-right-colour-renderenginepy-pure).
- **Acceptance:** stain ΔE00 < 3 (20.6 today); unlit wall next to sun ΔE00 < 3 (8.6 today); sunlit patch
  b* stays on the Shade's side; no channel clipped in the matte; outside the matte bit-identical.
- **Depends on:** nothing (pure `render/`). Tune against the Issue 1 fixtures once they exist.

### Issue 6: Add tap good enough for tiles and walls behind furniture

- **Labels:** `bug`, `segmentation`, `ui`
- **Covers:** bugs 4, 5, 8
- **Summary:** a multimask SAM 2 decoder for the single-point Add tap (best score, prefer the larger mask);
  a low-score note; a second tap grows the same plane; keep windows and doors out of added planes; a
  "wall hidden behind furniture" note; record tile scope in the spec and the custom-model handoff.
- **Method:** [04](./04-tiled-bathroom-not-painted.md#method-of-fixing),
  [05](./05-left-wall-not-painted.md#method-of-fixing), [08](./08-kitchen-tiles-not-identified.md#method-of-fixing).
- **Acceptance:** one tap covers ≥ 80% of a tiled band on the tiled fixtures; three taps in shelf gaps
  extend one plane; the hidden-wall note appears on the shelf-room fixture.
- **Depends on:** Issue 4 (added planes share `soften_boundary`). Needs original photos of a tiled
  bathroom and a tiled kitchen from the Dealer.

## Open items

- **Original photos needed** for pages 1, 2, 5 and 7. The PDF has only painted screenshots for those,
  and fixtures need the originals.
- **`_SUN_TINT_KEEP`, `_STAIN_SUPPRESSION`** and the other new constants start at reasoned values. Tune
  them against the fixtures and one Dealer review, and record the result in
  `docs/implementation-decisions.md`.
- **The touchscreen question** (`docs/specs/v1-spectrapaint.md:270`) is still open. It decides whether
  Undo also needs an on-screen control.
- **Long term:** a `tile` class and furniture-occluded wall in the custom segmentation model
  ([handoff](../handoff/custom-wall-segmentation-model.md)). The SegFormer checkpoint's mislabels
  (`mirror`, `wardrobe`, `floor` on tiles) are the underlying limit behind several of these bugs.
