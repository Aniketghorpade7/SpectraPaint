# Bugs 7 and 9 (and the "Sunlight" page): walls with sunlight on them paint badly

| | |
|---|---|
| **Area** | Segmentation (what gets painted) **and** render engine (how it's painted) |
| **Severity** | High: sunlit rooms are common in the Dealers' market, and the failure is obvious |
| **Confidence** | Confirmed: pipeline run on the page-4 and page-6 originals; render confirmed on synthetic input |
| **Source** | [SpectrapaintBugs.pdf](./SpectrapaintBugs.pdf), page 4 (item 7), page 6 (item 9), page 7 ("Sunlight") |
| **Root causes** | [A](./root-causes.md#a-the-alpha-matte-is-shaped-by-a-128128-grid), [B](./root-causes.md#b-the-31-confidence-floor-deletes-sunlit-wall), [C](./root-causes.md#c-the-light-map-carries-everything-that-is-not-the-base-colour) |
| **Issues** | [#48](https://github.com/Aniketghorpade7/SpectraPaint/issues/48) (#31 floor mirror exemption); [#51](https://github.com/Aniketghorpade7/SpectraPaint/issues/51) (Soft matte); [#52](https://github.com/Aniketghorpade7/SpectraPaint/issues/52) (Render: stains and sunlight) · [all issues](./README.md#proposed-issues) |

Item 9 and the "Sunlight" page are the same defect as item 7, so this one document covers all three.

## What it is

- **Page 4:** a pale-green dorm wall with sun on it, painted pink. The sunlit part stays green in
  blobs, with square-edged patches.
- **Page 6:** a pale-blue wall with sun, painted yellow. Two pale-yellow blobs stand out where the sun
  falls, and paint leaks onto the door and cabinet.
- **Page 7:** a yellow wall with a vertical sunlit strip, painted orange. The main wall and the strip
  aren't painted at all, while the frame edges and the adjacent wall are, in blocky orange.

Two separate failures combine: **the sunlit pixels are left out of the Alpha Matte** (segmentation),
and **the pixels that are painted get the wrong colour** (render).

## Root cause, part 1: sunlit wall is left out of the matte

1. **The #31 floor deletes it (cause B).** Bright, washed-out, low-texture wall is labelled `mirror` by
   this checkpoint (72% on page 6's sunlit wall). `_unvouched` (`segmentation/matte.py:189`) zeroes any
   non-`wall`-argmax pixel below 0.9 wall confidence. Page 6's sunlit wall: **0.79 coverage without
   the floor, 0.11 with it**. Page 4's right wall: 0.72 → 0.56.
2. **Blocky edges and square holes (cause A):** 75–84% of razor edges sit on 128-grid lines.
3. **Leak onto the door/cabinet (page 6), likely:** SAM 2's uncertain mask, plus restore-step
   cells (`matte.py:245-246`) on pixels mislabelled `wall`. This is the over-claim pattern in
   technical difficulty #12.
4. Nothing excludes bright or clipped pixels on purpose. `quality.py:67` only raises a note on the photo.

## Root cause, part 2: what is painted gets the wrong colour (cause C)

All the numbers come from the synthetic probe in [root-causes.md](./root-causes.md#evidence-synthetic-probe-session-scratchpad-probepy).

1. **Sunlight becomes the Base Colour.** `estimate_base_colour` (`render/engine.py:455-505`) takes the
   mean of the 85th–90th luminance percentile band. If sun covers about 10% or more of the wall, that
   band is entirely sunlit pixels, so the "Base Colour" is the sun-lit colour. On a yellow wall with a
   20% strip, base = (1.0, 0.96, 0.79), nearly white. The base is barely saturated, so the saturation
   blend (`engine.py:67-73`) doesn't engage. The rest of the wall's Light Map becomes
   (0.87, 0.54, 0.07), which is the old yellow **inside the Light Map**, and orange renders as brown
   **(221, 98, 6)** instead of (236, 130, 46). That's ΔE00 ≈ 8.6. Design §6 calls a hue error in the
   Base Colour a correctness bug.
2. **Warm sun on a cool wall makes a yellow blob.** With a small sun patch (below the percentile band),
   the per-channel ratio carries the sun's colour: light map (1.70, 1.35, 0.82). A pale-blue Shade
   renders as **(240, 246, 214)**, a pale yellow, against (189, 216, 234) on the rest of the wall.
   That's ΔE00 ≈ 22.6, and matches page 6.
3. **Per-channel clipping shifts the hue further.** `encode_srgb` (`render/luts.py:54-55`) clips each
   channel to [0, 1] independently. The strip on the yellow wall renders (255, 166, 61): the red
   channel is clipped, so the hue slides toward yellow. `_LIGHT_MAP_CEILING = 4.0`
   (`engine.py:387`) never engages at these values.
4. **Grouping (difficulty #17) can make it worse.** If the sunlit region becomes its own Wall Plane,
   its warm tint can split it into its own Base Colour group (`_grouped_base_colours`,
   `engine.py:545-606`), and it then renders flat, at exactly the target, next to a darker neighbour.
5. **Realistic mode's tint is a whole-image median** (`estimate_light_tint`, `engine.py:508-528`). A
   sunlit room tints every Shade warm, on top of the per-channel sun colour. That's by design (spec:
   "a rough whole-image estimate"), and it's left alone here.

## Decisions

- **Decision 3 (segmentation):** exempt `mirror` from the #31 floor, then re-measure with sunlit
  fixtures. Real mirrors become paintable again (accepted).
- **Decision 2 (render): warm, but capped.** A sunlit patch keeps a **bounded** share of the sun's
  tint (start at 30%). The rest of the deviation is brightness only. So the patch reads as "the chosen
  Shade, brighter and a little warm", never as a different colour.
- **Decision 1** (from [bug 2](./02-stains-survive-repaint.md)) supplies the luminance/chroma split this
  builds on.

## Method of fixing

### Part 1: include the sunlit wall

1. **Mirror exemption.** Full method in [root-causes.md → B](./root-causes.md#method-of-fixing-decision-3):
   export `mirror` under a separate runtime key, carry `floor_exempt` in `SemanticRegions`, add
   `& ~regions.floor_exempt` to `_unvouched`, then re-measure.
2. **Soft matte (cause A).** Full method in [root-causes.md → A](./root-causes.md#method-of-fixing).
   It removes the square holes and staircase edges.
3. **Fixtures.** Add the page-4 and page-6 **originals** (the PDF has them as "Original photo") to
   `data/fixtures/rooms/`. Label them with `tools/fixtures/label_rooms.py`, and add a
   `sunlit_wall_recall` metric to `tests/api/test_walls.py`: the share of the brightest 10% of
   labelled-wall pixels covered at ≥ 0.5, with a target of 0.80. Its structure mirrors
   `test_shadowed_wall_stays_wall` (`:423-446`).

### Part 2: paint it the right colour (render/engine.py, pure)

These steps come **after** bug 2's step 1, which gives `shading` (HxW) and `chroma` (HxWx3).

**Step 1: a sun-robust Base Colour** (`estimate_base_colour`).

Measure the base only from pixels whose **hue agrees with the wall as a whole**, so sun-coloured
pixels can't enter the percentile band:

```python
pixels       = linear_photo[interior]
tints        = pixels / luma(pixels)[:, None]               # brightness removed (as _tint_of)
typical_tint = np.median(tints, axis=0)                     # the wall's hue; robust while sun < 50%
agrees       = norm(tints - typical_tint, axis=1) < _BASE_TINT_TOLERANCE
candidates   = pixels[agrees] if agrees.sum() >= _BASE_MIN_AGREEING else pixels
band         = in_luminance_band(candidates, _BASE_PERCENTILE, _BASE_PERCENTILE_BAND)   # today's rule
base_colour  = max(band.mean(axis=0), _BASE_COLOUR_FLOOR)                              # today's rule
```

- `_BASE_TINT_TOLERANCE = 0.06` is in the same tint space as `_GROUP_TINT_THRESHOLD = 0.08`
  (`engine.py:379`), and just tighter than it. `_BASE_MIN_AGREEING = 500` falls back to today's
  behaviour on a tiny or wildly varied wall (never dead-end).
- The per-channel median is used **only as a filter**. The Base Colour is still the mean RGB of whole
  pixels, so the docstring's argument ("a per-channel percentile … would neutralise the wall's cast")
  still holds.
- On a white wall in white sun, the sunlit pixels agree in hue and still set the brightness, which is
  correct: "the paint as it appears under full light" (CONTEXT.md). Only differently-*coloured* light
  is kept out.
- Grouping uses the per-plane estimates, so a sunlit plane now gets the same tint as its shaded
  neighbour and groups with it (point 4 above).

**Step 2: cap the sun's tint in highlights** (`light_map_of`).

```python
highlight   = smoothstep(_HIGHLIGHT_START, _HIGHLIGHT_FULL, shading)     # 0 in normal light, 1 in sun
keep        = lerp(1.0, _SUN_TINT_KEEP, highlight)
chroma_out  = 1.0 + (chroma_out - 1.0) * keep[..., None]
```

`_HIGHLIGHT_START = 1.15`, `_HIGHLIGHT_FULL = 1.5` (shading relative to the Base Colour's luma) and
`_SUN_TINT_KEEP = 0.30` (decision 2). Worked through by hand on the page-6 probe: shading there is
1.39, so `highlight` ≈ 0.75 and `keep` ≈ 0.48. The sunlit light map goes from (1.70, 1.35, 0.82) to
about (1.54, 1.37, 1.12), and the patch renders about (229, 248, 246). That's Lab b* −1.2 instead of
today's +14.7: a brighter, near-white pale tone on the blue side, not a yellow blob. If the Dealers
find that still reads too warm or too cold, `_SUN_TINT_KEEP` is the one number to turn.

**Step 3: hue-preserving highlight roll-off before encode** (`render` / `render_many`, not `luts.py`).

```python
peak   = composite.max(axis=-1, keepdims=True)
over   = peak > _HIGHLIGHT_KNEE
scaled = _HIGHLIGHT_KNEE + (1 - _HIGHLIGHT_KNEE) * (1 - exp(-(peak - _HIGHLIGHT_KNEE) / (1 - _HIGHLIGHT_KNEE)))
composite = np.where(over, composite * (scaled / peak), composite)
```

`_HIGHLIGHT_KNEE = 0.90` (linear). All three channels are scaled by the same factor, so the hue is
kept, and the soft knee means nothing hard-clips. `encode_srgb`'s clip stays as the last-resort guard.
Apply it only inside the matte (`alpha > 0`), so the untouched part of the photo is bit-identical to
today.

**Step 4: truly clipped photo pixels.** Where the *photo* is at 254-255 in any channel
(`photo_u8 >= _CLIPPED_LEVEL`, `_CLIPPED_LEVEL = 250`), the Light Map there carries no information. Set
`chroma` to the local room chroma (bug 2 step 2's `room_chroma`) and keep `shading`. The patch is
bright, with the Shade's hue. `quality.py`'s clipping note already tells the Dealer the photo is
heavily clipped.

All the new constants go in the engine.py tunables block with conventions §4 comments, tuned against
the page-4 and page-6 fixtures.

## Docs to amend

- `docs/design-decisions.md` §6 (per-channel Light Map): add a highlight exception. Above
  `_HIGHLIGHT_START` only 30% of the chroma deviation is kept, and why (decision 2).
- `docs/design-decisions.md` "Base colour — grouped by existing paint": the base's hue comes from the
  wall's median tint, and its brightness from the lit band.
- `render/engine.py`: docstrings for `estimate_base_colour` and `light_map_of`.
- `data/fixtures/rooms/measured.toml`: new entries for the sunlit fixtures, with the header noting the
  mirror exemption.

## Tests

`services/inference/tests/render/`:

1. **Sun doesn't skew the base:** a yellow wall with a 20% near-white strip. The base's tint is within
   `_BASE_TINT_TOLERANCE` of the unlit wall's tint, and the unlit wall renders the orange Shade within
   ΔE00 < 3 of the same wall with no strip (8.6 today).
2. **No yellow blob:** a pale-blue wall with a 5% warm sun patch and a pale-blue Shade (Lab 85, −5,
   −12). The rendered patch has Lab b* ≤ 0, so it stays on the Shade's blue side (today's (240, 246, 214)
   is b* = +14.7), and a higher L* than the rest of the wall.
3. **No hard clip:** a strip at 1.7× on an orange Shade. There are no channels at 255 inside the matte,
   and the hue angle is within 5° of the Shade's.
4. **Outside the matte is untouched:** pixels with `alpha == 0` are bit-identical to `encode_srgb(photo)`.

`services/inference/tests/api/test_walls.py`: `sunlit_wall_recall` ≥ 0.80 on the two sunlit fixtures,
and `windows-with-curtains` leakage stays ≤ 0.20.

## Acceptance criteria

- [ ] On the page-4 and page-6 fixtures, ≥ 80% of the sunlit wall is painted.
- [ ] Sunlit patches read as the chosen Shade, brighter and at most slightly warm (tests 2 and 3). No
      differently-coloured blobs.
- [ ] A wall partly in sun renders the Shade's hue on its unlit part (test 1).
- [ ] No regression in `measured.toml` beyond the re-measured baselines recorded in the change.

## Related

[Bug 2](./02-stains-survive-repaint.md) (same luminance/chroma split: land it first, or together);
[bug 3](./03-colour-faint-when-selected.md) (edge coverage).
