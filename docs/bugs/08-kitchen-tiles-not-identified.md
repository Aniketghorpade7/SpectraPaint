# Bug 8: kitchen wall tiles are not identified

| | |
|---|---|
| **Area** | Segmentation |
| **Severity** | Medium |
| **Confidence** | Confirmed: the pipeline was run on the page-5 image |
| **Source** | [SpectrapaintBugs.pdf](./SpectrapaintBugs.pdf), page 5, item 8 |
| **Root cause** | Local (tiles labelled `refrigerator`/`cabinet`) + [A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid) |
| **Issue** | [#53](https://github.com/Aniketghorpade7/SpectraPaint/issues/53) (Add-tap quality: tiles and hidden walls) · [all issues](./README.md#proposed-issues) |

## What it is

A kitchen wall of ceramic tiles around a window, with exposed plaster below, gets paint in only
scattered, blocky patches. Most of the tiles and the lower-right area stay unpainted.

## Root cause

1. **The tiles aren't labelled wall.** SegFormer calls them `refrigerator` (32%) and `cabinet` (9–20%).
   Neither is `wall` nor one of the four exclusions, so they're "unclaimed". They get no positive
   prompts (`prompts.py:142`, positives come only from the eroded `regions.wall`), and the #31 floor
   (`matte.py:189`) zeroes whatever SAM 2 claimed there. The lower-right tiles end up **0.00** covered.
   The floor itself isn't the main factor here: 0.33 coverage with it vs 0.36 without.
2. **SAM 2 is uncertain everywhere.** Logits −0.8 to 0.2, `iou_scores` 0.00. So what *does* get painted
   is the restore step's 1.0 cells (`matte.py:245-246`), which are 128-grid squares. That reproduces the
   scattered blocky patches in the screenshot (cause A).

## Decision

Same as [bug 4](./04-tiled-bathroom-not-painted.md): **tiles are paintable in V1 via the Add tap only**
(decision 4). Don't add `refrigerator`/`cabinet` to the wall classes; difficulty #26 showed these labels
aren't reliable enough to act on.

## Method of fixing

Everything in [bug 4 → Method of fixing](./04-tiled-bathroom-not-painted.md#method-of-fixing) applies
unchanged (multimask Add tap, a second tap to grow a plane, soft matte). Two things are specific to
this bug:

1. **Stop the grid-square patches.** With cause A fixed (bilinear probabilities, continuous band, and
   `iou_scores` below `REFINER_TRUST_FLOOR` handing the shape to the semantic probability), the
   automatic pass paints the plaster that *is* labelled wall cleanly, instead of scattering cells over
   the tiles.
2. **The window in a tiled wall.** The window (`windowpane`) stays a hard exclusion. The Add tap
   ignores exclusions by design (`corrections.py:224-228`: *"a tap that lands on a window is a tap the
   Dealer chose to make"*), so a tap on tiles around a window can grow into the glass. After
   `decode_alpha_best`, multiply by the exclusion ramp from cause A step 2 **for `windowpane` and `door`
   only**. That needs the `SemanticRegions` available to corrections. Today the preparation
   *workspace* holds them (`api/preparation.py:303`, `workspace.regions`), but the finished
   `PreparedPhoto` carries only `features` (`:130`). Add a `regions` field alongside `features`, set
   the same way `cache_features` (`:277`) sets features, and have `add_plane` accept it as an
   optional argument. When it's `None` (a reopened consultation), skip the ramp. It's a deliberate,
   documented exception to "Add ignores labels": glass is never wall material (design-decisions §5).

## Tests

- **Fixture:** a tiled-kitchen original photo (page 5 is a screenshot with paint, so ask the Dealer
  for the original), with the tiles labelled as wall in `.wall.png`.
- Assert that `add_tap_recall` ≥ 0.80 for a tap on the tiles, and that window pixels in the added plane
  are 0.

## Acceptance criteria

- [ ] On the kitchen fixture, the automatic pass paints no isolated grid-square patches: every connected
      component of the matte is ≥ 0.5% of the photo.
- [ ] One tap on the tiles adds a plane covering ≥ 80% of them, with no coverage on the window glass.

## Related

[Bug 4](./04-tiled-bathroom-not-painted.md), [root cause A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid).
