# Bug 3: wall colour looks faint when a wall is selected or at its edges

| | |
|---|---|
| **Area** | UI overlay (`apps/ui`), plus plane-edge coverage in the service |
| **Severity** | Medium-high: the Customer judges a washed-out colour |
| **Confidence** | Confirmed: all three code paths below produce a faint wall |
| **Source** | [SpectrapaintBugs.pdf](./SpectrapaintBugs.pdf), page 1, item 3 ("When edge selected wall colour get faint and observation looks improper") |
| **Root cause** | Local (UI wash, armed tool) + [A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid) (edge coverage) |
| **Proposed issues** | Issue 2, "UI fixes" (paths 1-2); Issue 4, "Soft matte" (path 3) ([README](./README.md#proposed-issues)) |

## What it is

The wall's colour appears pale or washed out, so the Customer isn't seeing the Shade as it would look.
The report doesn't say which interaction triggered it, and the code has three separate ways to cause
it. **Decision 5: fix all three.**

## Root cause

### Path 1: the chosen wall is washed 45% white

```css
/* apps/ui/src/consultation/consultation.css:113-118 */
.consultation__wall-overlay { position: absolute; inset: 0; background: rgb(255 255 255 / 30%); … }

/* :150-152 */
.consultation__wall-overlay--chosen { background: rgb(255 255 255 / 45%); }
```

The overlay is masked by each Wall Plane's Alpha Matte (`ConsultationSurface.tsx:165-181`). The wall
chips that pick an Accent Wall only appear when the render is hidden (`walls.ts:103-105`,
`overlayVisible` requires `!showingRender`). So to choose a wall, the Dealer goes back to the original
photo, where the chosen wall is covered by a 45% white wash. It looks pale, and nothing like the
Shade it's about to receive.

### Path 2: an armed correction tool leaves the wash over the painted render

```tsx
// apps/ui/src/consultation/ConsultationSurface.tsx:87
const showWalls = overlayVisible(walls, render.showingRender) || armedTool !== null;
```

`explicitTool` is cleared only by a photo tap (`useConsultation.ts:450`, inside `correctWallsAt`) or by
discarding. `applyShade` (`useConsultation.ts:318-371`) never clears it. So:

1. The Dealer arms "Add a wall" / "Split a wall" / "Merge walls".
2. Instead of tapping the photo, they tap a Shade.
3. The render arrives and is shown (`showingRender`), but `armedTool !== null`, so `showWalls` is true.
   The **painted render** now has a 30–45% white wash on top, plus the crosshair tap layer.
4. The tool buttons are hidden while the render shows (`ConsultationSurface.tsx:116`,
   `!render.showingRender ? … : null`), so the Dealer **can't disarm it**.

### Path 3: soft claims at plane-to-plane edges don't add up to full coverage

- **Add tool** (`services/inference/spectrapaint/segmentation/corrections.py:249-274`): where a new
  plane and an existing plane overlap, the higher claim keeps its value and the loser drops to 0
  (`new_wins = alpha >= existing_claim`). Where both claims are soft (for example 0.6 and 0.5), the
  pixel ends up covered at `max(a, b)` = 0.6, not ~1, and 40% of the old paint shows through. The
  result is a faint stripe along the shared edge.
- **Wall vs ceiling** (`services/inference/spectrapaint/api/preparation.py:400-420`): only the
  *ceiling* is zeroed where a confident wall wins. The wall is **never** zeroed where the ceiling
  wins, so both are composited on the same pixels. That breaks the "every pixel belongs to exactly one
  plane" rule (`docs/design-decisions.md` §6, exclusive assignment).
- Cause A's hard staircases at exclusion edges (`matte.py:263`) add half-covered cells along the
  edges.

The engine's composite itself is correct: linear-light blend, no opacity factor
(`render/engine.py:237-248`), and a matte interior forced to 1.0 (`segmentation/matte.py:224`).

## Method of fixing

### Path 1: show the selection without washing the wall (UI)

1. Delete `.consultation__wall-overlay--chosen` and its class switch (`ConsultationSurface.tsx:177-181`).
   Every detected wall keeps the same weak 30% wash, and the chosen one gets no extra white.
2. Mark the chosen wall with **an outline along its matte edge**, in neutral grey (ui-guidelines: no
   saturated colour near the render):
   - A new pure helper in `apps/ui/src/consultation/walls.ts`:
     `matteOutline(matte: ImageData, width: number): ImageData`. Threshold at 128; a pixel is on the
     outline if it is inside and any 4-neighbour within `width` px is outside. Unit-testable.
   - A `<canvas className="consultation__wall-outline">` absolutely positioned in the frame, drawn once
     per (plane, frame size) from the matte PNG, with a 2 px `--grey-6` line and a 1 px `--grey-0`
     halo, so it reads on both light and dark walls.
3. The chip already inverts for the chosen wall (`consultation__wall-chip--chosen`); keep it.

### Path 2: never wash the render (UI)

1. In `applyShade`, call `setExplicitTool(null)` before the request. Tapping a Shade means the
   Dealer has moved on from correcting.
2. Harden the display rule so a future path can't bring the bug back:

   ```tsx
   const showWalls = !render.showingRender && (overlayVisible(walls, false) || armedTool !== null);
   ```

   Also gate the tap layer on `!render.showingRender`.
3. Put it in `walls.ts` as a pure function (`overlayVisible(state, showingRender, armedTool)`) with a
   unit test for "tool armed + render showing → no overlay".

### Path 3: full coverage where planes meet (service)

1. **Add tool:** at contested pixels (both claims > 0), give the winner the **union** coverage rather
   than just its own value:

   ```python
   contested = (alpha > 0) & (existing_claim > 0)
   union = np.minimum(1.0, alpha + existing_claim)   # the pixel's total wall coverage
   resolved_new = np.where(new_wins, np.where(contested, union, alpha), 0.0)
   # and the symmetric update for the existing plane that wins
   ```

   The exclusivity rule and the "an already-correct pixel is never made worse" property in the
   `add_plane` docstring both still hold, because coverage only goes up.

   **Caveat to test:** `a + b` over-counts where both soft edges are describing the *same* outside
   boundary (two planes fading into the same window). Restrict `contested` to pixels where the two
   mattes' 0.5-contours are within `_BAND_FRACTION` of each other, which is a wall↔wall seam, and
   where the pixel isn't within the exclusion ramp of cause A step 2. Everywhere else keep `max`.
2. **Wall vs ceiling** (`preparation.py:400-420`): resolve the pair symmetrically. Where the ceiling
   wins, zero the wall, and give the winner `min(1, wall + ceiling)`. Extract that rule into
   `segmentation/corrections.py` as `resolve_exclusive(winner, loser)` so the Add tool,
   `add_ceiling_plane` and preparation share one implementation (the Duplicated Code smell today).
3. Cause A's fixes (soft exclusion ramp, round morphology) remove the half-covered grid cells. See
   [root-causes.md](./root-causes.md#method-of-fixing).

## Docs to amend

- `docs/ui-guidelines.md`: selection is shown by an outline or chip, never by a wash on the wall being
  judged.
- `docs/implementation-decisions.md`: tapping a Shade disarms any correction tool, and why.
- `docs/design-decisions.md` §6 "Open: the assignment rule for contested pixels": record the union rule.

## Tests

- `apps/ui/src/consultation/walls.test.ts`: `overlayVisible` is false whenever a render is showing,
  whatever tool is armed. `matteOutline` on a synthetic disc gives a closed ring of the right width.
- `apps/ui/src/consultation/*.test.ts`: `applyShade` clears the armed tool (hook test, or extract the
  reducer).
- `services/inference/tests/api/test_corrections.py`: add a plane whose soft edge overlaps an existing
  soft edge. Assert that the summed coverage over the overlap is ≥ 0.99 and that no pixel is claimed by
  two planes.
- `services/inference/tests/api/test_walls.py::test_no_pixel_belongs_to_two_wall_planes`: extend it to
  include the ceiling plane.

## Acceptance criteria

- [ ] Choosing a wall never makes that wall paler than the others. It's marked by an outline and its chip.
- [ ] After arming any tool and then tapping a Shade, the render shows with no wash and no tap layer.
- [ ] No faint stripe is visible along a wall ↔ wall or wall ↔ ceiling boundary after repainting. Test:
      coverage ≥ 0.99 across boundaries.
- [ ] No pixel is composited by two planes, ceiling included.

## Related

[Bug 1](./01-photo-zoomed-after-upload.md) (same overlay layer); [root cause A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid).
