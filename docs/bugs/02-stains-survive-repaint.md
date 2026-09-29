# Bug 2: stains on the wall still show after repainting

| | |
|---|---|
| **Area** | Render engine (`services/inference/spectrapaint/render/`) |
| **Severity** | High: a Customer who sees their damp patch in the new Shade reads it as "the paint won't cover it" |
| **Confidence** | Confirmed: synthetic probe on the pure render functions |
| **Source** | [SpectrapaintBugs.pdf](./SpectrapaintBugs.pdf), page 1, item 2 |
| **Root cause** | [C: the Light Map carries everything that is not the Base Colour](./root-causes.md#c-the-light-map-carries-everything-that-is-not-the-base-colour) |
| **Issue** | [#52](https://github.com/Aniketghorpade7/SpectraPaint/issues/52) (Render: stains and sunlight) · [all issues](./README.md#proposed-issues) |

## What it is

Stains, damp patches, old touch-ups and scuffs on the existing wall are still visible after a Shade
is applied. They're re-tinted into the new colour, but they're plainly still there.

**Repro:** photograph a pale wall with a damp patch, then apply any Shade. The patch shows as a
darker, off-hue blotch in the new colour.

## Root cause

The repaint formula is `new_wall = light_map × target_shade × light_tint` (`render/engine.py:225-234`),
with `light_map = linear_photo / base_colour` **per RGB channel** (`engine.py:63-65`). A stain is a
*reflectance* change, not a lighting change, but the division can't tell the two apart. Its darkness
**and its hue** go into the Light Map and are multiplied into the new Shade.

The two existing refinements don't help on a typical wall:

- The luminance-only blend (`engine.py:67-73`) only engages as the Base Colour's saturation rises
  above `_SATURATION_BLEND_START = 0.20` (`:394`). Pale walls, the common case, stay fully per-channel.
- `_smooth_where_dark` (`engine.py:193-222`) only smooths dark, noisy pixels. Its docstring (`:205`)
  says it is designed to *"let a well-lit wall keep its stains"*.

The design accepted this on purpose, in `docs/design-decisions.md:326-332`:

> Genuine reflectance defects — stains, patches, previous touch-ups — are **not** lighting … They ride
> through the light map and get re-tinted by the new shade. That is knowingly accepted …

The Dealer testing shows that assumption doesn't hold. A re-tinted stain is still a visible stain.

**Probe** (session scratchpad `probe.py`; cream wall (225,215,190), brown stain (170,150,110),
pale-blue target):

| | Light Map | Rendered sRGB |
|---|---|---|
| Clean wall | (1.00, 1.00, 1.00) | (189, 216, 235) |
| Stain | (0.51, 0.45, 0.35) | (140, 151, 146): grey-brown patch |

On a saturated yellow base the blend removes the stain's hue (light map 0.615 grey), but its darkness
stays.

## Decision (grilling decision 1)

**The repaint promises "your wall, freshly painted".** Lighting, shadows and texture are kept. Stains
and patches are suppressed **by default**. The strength is a named constant in `engine.py`'s tunables
block. **No Dealer-facing slider in V1.** Accepted cost: soft contact shadows (behind furniture or
under a shelf) are weakened somewhat.

## Method of fixing

All of this lives in `render/engine.py` and stays pure (conventions §3: no I/O, no logging, no config
reads). The Light Map is computed once per photo per Base Colour group (`render_many` docstring), so
the extra filtering is paid once, not per Shade tap.

### Step 1: split the Light Map into luminance and chroma

Inside `light_map_of`, after the existing division and saturation blend:

```python
luma_base  = dot(LUMA, base_colour)
shading    = luma(linear_photo) / luma_base                  # HxW   — brightness only
chroma     = light_map / max(shading[..., None], eps)       # HxWx3 — ≈ (1,1,1) on clean wall
```

`shading × chroma` reproduces today's Light Map exactly, so a later step that changes neither returns
today's output. That keeps `test_correctness` / `test_engine` exactness cases intact.

### Step 2: suppress chroma deviations (removes the stain's hue)

```python
room_chroma = box_blur3(chroma, r = _STAIN_ILLUMINATION_RADIUS)   # large-scale colour: bounce light, window cast
chroma_out  = lerp(chroma, room_chroma, _STAIN_CHROMA_SUPPRESSION)
```

`box_blur3` = three passes of `imaging.box_mean` (a Gaussian approximation, O(1) per pixel whatever
the radius), matte-weighted as a normalised convolution exactly as `_smooth_where_dark` already does,
so the chair's colour is never borrowed. Large-scale colour, such as light bouncing off a red sofa,
survives. A 20-cm stain's hue doesn't.

### Step 3: suppress mid-frequency luminance blotches (removes the stain's darkness)

Split `shading` into three bands, in log space so ratios compose:

```python
log_s        = log(max(shading, eps))
illumination = blur(log_s, _STAIN_ILLUMINATION_RADIUS)   # room light, gradients, corner falloff — KEPT
fine         = log_s - blur(log_s, _STAIN_TEXTURE_RADIUS) # roller texture, grain           — KEPT
blotch       = log_s - illumination - fine                # stains, patches, soft contact shadows

protect      = edge_protection(alpha)                      # 1 near the matte boundary, 0 in the interior
strength     = _STAIN_SUPPRESSION * (1 - protect)
shading_out  = exp(illumination + fine + (1 - strength) * blotch)
```

- `edge_protection` ramps from 1 at the matte's edge to 0 at `_STAIN_EDGE_PROTECT_RADIUS` inside it.
  Contact shadows sit *at* occluders (furniture, shelf undersides, the ceiling line), which are matte
  boundaries, so they are mostly kept. Stains in the open wall are suppressed.
- Hard cast shadows mostly land in `illumination` (they're large) or `fine` (their edges), so they
  survive. The softest small shadows are the accepted cost.

### Step 4: recombine

`light_map = shading_out[..., None] * chroma_out`, followed by the existing `_LIGHT_MAP_CEILING` clamp
and `_smooth_where_dark`. The rest of the engine is unchanged.

### New tunables (engine.py tunables block, after `_SMOOTHING_COVERAGE_EPSILON`)

| Constant | Start value | Meaning |
|---|---|---|
| `_STAIN_SUPPRESSION` | 0.8 | Share of mid-frequency luminance deviation removed. 0 = today's behaviour |
| `_STAIN_CHROMA_SUPPRESSION` | 1.0 | Share of local chroma deviation removed |
| `_STAIN_ILLUMINATION_RADIUS_FRACTION` | 0.08 | Of the shorter side: larger is "lighting", kept |
| `_STAIN_TEXTURE_RADIUS_FRACTION` | 0.004 | Of the shorter side: smaller is "texture", kept |
| `_STAIN_EDGE_PROTECT_RADIUS_FRACTION` | 0.03 | Contact-shadow protection band inside the matte edge |

Each gets the comment conventions §4 asks for: what it trades, and which fixture it was tuned against.

## Docs to amend

- `docs/design-decisions.md` §6, lines ~326-332: replace "knowingly accepted" with the decision.
  Stains are reflectance, the repaint covers them, and suppression is band-limited so lighting survives.
  Record the accepted loss of soft contact shadows.
- `CONTEXT.md` → **Light Map**: add one sentence. The Light Map carries *lighting*; reflectance
  defects are removed from it before repainting.
- `engine.py`: the `light_map_of` docstring gains a fourth refinement; fix the `_smooth_where_dark`
  docstring's "keep its stains".
- `docs/implementation-decisions.md`: a new entry with the constants and the probe numbers before and
  after.

## Tests (`services/inference/tests/render/`)

1. **Stain disappears:** cream wall, 40×40 brown patch. ΔE00 between the rendered patch and the
   rendered surrounding wall is **< 3** (it is ≈ 20.6 today).
2. **Illumination survives:** a wall with a left-to-right 2:1 linear light gradient. The rendered
   luminance ratio between the ends is within **2%** of 2:1.
3. **Texture survives:** a wall with ±5% high-frequency noise. The rendered noise standard deviation is
   within **20%** of the input's (relative to the Shade).
4. **Contact shadow near an edge survives:** a darkening ramp within `_STAIN_EDGE_PROTECT_RADIUS` of
   the matte's edge keeps ≥ 80% of its depth.
5. **Clean input is unchanged:** a flat wall still returns exactly `photo / base` (the existing
   exactness contract in the `light_map_of` docstring).
6. Performance gate: `spikes/latency/perf-baseline.json`. The Light Map is per photo, not per tap, but
   check that preparation-to-first-render stays within budget (difficulty #20: the gate must not
   silently fall back).

## Acceptance criteria

- [ ] On the fixture rooms and a photo with a real damp patch, the patch is not visible after
      repainting at normal viewing size (Dealer check), and test 1 passes.
- [ ] Tests 2–5 pass; no existing render test regresses.
- [ ] design-decisions §6 and CONTEXT.md are updated in the same change (conventions §1).

## Related

[Bug 7/9](./07-sunlit-wall-paints-badly.md) builds on the same luminance/chroma split. Land this
first, or both in one change.
