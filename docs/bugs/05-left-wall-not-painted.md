# Bug 5: the left wall (behind open shelving) could not be painted

| | |
|---|---|
| **Area** | Segmentation, plus a Dealer-facing note |
| **Severity** | Medium-high: a whole Wall Plane is missing from the repaint |
| **Confidence** | Confirmed on the page-4 original (same room); page 2 is a painted screenshot |
| **Source** | [SpectrapaintBugs.pdf](./SpectrapaintBugs.pdf), page 2, item 5 |
| **Root cause** | Local (wall labelled `wardrobe`) + [A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid) |
| **Proposed issue** | Issue 6, "Add-tap quality: tiles and hidden walls" ([README](./README.md#proposed-issues)) |

## What it is

In a room with a tall open shelf unit against the left wall, the paint covers only the band of wall
**above** the shelf, and even that has stair-stepped edges and square holes. The wall visible between
and behind the shelves, and the lower-left wall, get nothing.

## Root cause

1. **The wall between the shelves is labelled `wardrobe`**, at 99% (ADE20K index 35). That's neither
   `wall` nor an exclusion, so:
   - positive prompts come only from the eroded `regions.wall` (`segmentation/prompts.py:142`), so
     **no prompt lands there**;
   - SAM 2 sits at about 0.27 there, below the 0.5 edge level `soften_boundary` treats as inside
     (`matte.py:60`, `_EDGE_LEVEL`), so the pixel ends up exterior (0);
   - the restore step (`matte.py:245-246`) only restores argmax-`wall` pixels.

   Coverage there is **0.00 with or without** the #31 floor, so the floor isn't the cause here.
   `split.py` isn't either: it only divides coverage between planes, and `walls.py:192` checks the
   total is preserved.
2. **The band above the shelf is `wall` at 98% and gets painted**, but its edge against the ceiling is
   the 128-grid staircase (cause A). On the page-2 screenshot SAM 2 returned essentially nothing (0% of
   pixels above 0.5), so the whole matte was the grid-shaped restore mask. That explains the
   square-edged pink band.

## Decision (grilling decision 7)

**The Add tap, plus a plain note.** Automatic detection isn't changed. Putting positive prompts inside
furniture labels would paint the furniture itself, which is the leakage #31 is fighting. When the
photo suggests wall is hidden behind furniture, the Dealer gets a note pointing them to the Add tool
(conventions §5, never dead-end).

## Method of fixing

### Step 1: the Add tap covers the gap

Everything in [bug 4 → Method of fixing](./04-tiled-bathroom-not-painted.md#method-of-fixing) applies:
multimask best-score decoding for a single tap, and a second tap to grow a plane. Walls seen *between*
shelves are several disconnected pieces, so **Step 2 of bug 4 (multi-tap growth) matters most here**.
Each gap is one more tap on the same plane, not a new plane per gap. Otherwise the Dealer ends up with
five planes named "left wall 1…5".

### Step 2: the "hidden wall" note

1. **Export the furniture labels.** Add `FURNITURE_CLASSES = ("wardrobe", "cabinet", "shelf",
   "bookcase")` (ADE20K 35, 10, 24, 62) to `tools/export_onnx.py`. Write them under a separate
   `runtime.json` key (like `mirror` in [cause B](./root-causes.md#b-the-31-confidence-floor-deletes-sunlit-wall)),
   never as exclusions.
2. **Carry them** in `SemanticRegions` as `furniture: np.ndarray` (HxW bool).
3. **Detect** in `segmentation/walls.py`, after planes are built:

   ```python
   near_wall = dilate_round(wall_union >= 0.5, round(min(shape) * HIDDEN_WALL_REACH_FRACTION))
   hidden = regions.furniture & near_wall
   if hidden.mean() >= HIDDEN_WALL_NOTE_FRACTION:
       hint = MESSAGE_HIDDEN_WALL
   ```

   with `HIDDEN_WALL_REACH_FRACTION = 0.05`, `HIDDEN_WALL_NOTE_FRACTION = 0.08` and
   `MESSAGE_HIDDEN_WALL = "Some wall may be hidden behind furniture. Use Add a wall and tap it to
   include it."` It names no model or technique (conventions §5).
4. **Return it** as a new optional `wall_hint` field in the planes response (`api/planes.py`,
   `GET /{session_id}/planes`). Keep it separate from `note` (set only when no wall was found) and
   `quality_note` (the photo's own quality), because it answers a different question. This is a REST
   contract change (seam 1): update the contract test and `bridge-types.ts`.
5. **Show it** in the UI as a grey note under the photo, the same style as `.consultation__wall-note`
   (`consultation.css:139-145`), only while the original photo is showing.

### Step 3: clean edges on what *is* found

Cause A's fixes (bilinear probability upsample, soft exclusion ramp, round morphology) replace the
staircase along the top band with an edge that follows the photo.

## Tests

- **Fixture:** add the page-4 original (it's the same room) to `data/fixtures/rooms/`, labelling the
  wall between the shelves as wall in `.wall.png`.
- `tests/api/test_walls.py`: on that fixture, `wall_hint` is set. On `empty-corner.jpg` (no
  furniture), `wall_hint` is `None`.
- `tests/api/test_corrections.py`: three taps into three shelf gaps extend **one** plane (once bug 4
  step 2 lands), and its coverage of the labelled gap wall is ≥ 0.70.

## Acceptance criteria

- [ ] On the shelf-room fixture, the Dealer sees the hidden-wall note.
- [ ] Tapping the gaps between shelves adds them to one Wall Plane that takes one Shade.
- [ ] The painted band above the shelf has no grid-stair edge: ≤ 10% of its razor edges on 128-grid
      lines (cause A metric).

## Related

[Bug 4](./04-tiled-bathroom-not-painted.md) (the same Add-tap work), [root cause A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid).
