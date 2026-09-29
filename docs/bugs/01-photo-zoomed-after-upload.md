# Bug 1: the Room Photo shows zoomed in after upload

| | |
|---|---|
| **Area** | UI (`apps/ui`), plus a latent service-side orientation defect |
| **Severity** | High: the Customer judges a cropped room, and wall chips and taps can land off-photo |
| **Confidence** | Confirmed: layout measured in headless Chrome at 1280×720 |
| **Source** | [SpectrapaintBugs.pdf](./SpectrapaintBugs.pdf), page 1, item 1 |
| **Issue** | [#49](https://github.com/Aniketghorpade7/SpectraPaint/issues/49) (UI fixes) · [all issues](./README.md#proposed-issues) |

## What it is

After the Dealer loads a Room Photo, the Consultation surface shows only its middle band. The top
and bottom are cut off, so the photo looks zoomed. Every aspect ratio taller than the stage is
affected: 4:3 landscape and all portrait photos. 16:9 only just fits.

**Repro:** open the app at its default window size and load any 4:3 or portrait phone photo. The
top and bottom of the room are missing. The same thing happens on the repaint, the overlay and the
correction tap layer, because they all share the frame.

## Root cause

The service doesn't crop. CSS lets the photo's frame grow taller than the stage, and the stage clips it.

```css
/* apps/ui/src/consultation/consultation.css:53-63 */
.consultation__stage { flex: 1; min-width: 0; display: flex;
  align-items: center; justify-content: center; padding: var(--space-8); overflow: hidden; }

/* :67-74 — no height of its own */
.consultation__picture { display: flex; flex-direction: column; align-items: center;
  gap: var(--space-4); min-width: 0; min-height: 0; }

/* :92-98 */
.consultation__frame { position: relative; width: 100%; height: 100%;
  max-width: 100%; max-height: 100%; }
```

`ConsultationSurface.tsx:160-163` sets `aspect-ratio` inline from the decoded image's natural size.
Because `.consultation__picture` has no definite height, the frame's `height: 100%` and
`max-height: 100%` resolve to `auto`, so they do nothing. The width is definite (100%), so
`aspect-ratio` computes the height from the width, and **nothing caps that height at the stage**.
The stage then centres the too-tall frame (`align-items: center`) and hides the overflow
(`overflow: hidden`), and the Dealer sees the middle band.

**Measured**, with 836×492 px of usable stage:

| Photo | Frame box | Visible |
|---|---|---|
| 4:3, 1280×960 | 836×627, top at y = 25, above the stage | ≈ 78% of the height |
| Portrait, 960×1280 | 836×1115 | ≈ 44% of the height |
| 16:9 | 836×470 | all, only just |

This came in with the `.consultation__frame` fix for technical difficulty #23, which checked that
the frame and the tap layer aligned but never compared the frame with the stage.

**Ruled out:** the sidecar only scales uniformly to 1280 px on the long side
(`services/inference/spectrapaint/api/preparation.py:455-462`). `quality.py` and `sessions.py` never
crop.

### Latent, related: EXIF orientation is never applied

`decode_photo` (`preparation.py:447-466`) does `Image.open(...).convert("RGB")` with no
`ImageOps.exif_transpose`, and nothing in the repository mentions EXIF. But the photo the UI shows is
the **raw upload** (`apps/desktop/src/create-consultation.ts:85`, `photoDataUrl(bytes, mime)`), and
Chromium *does* honour the EXIF orientation tag. For a phone photo stored with an Orientation ≠ 1 tag
(common for portrait shots), the Alpha Mattes, the render and the tap coordinates are all built on the
unrotated pixels, while the Dealer sees the rotated image. The overlay and paint would land sideways.
`api/exports.py:202` (full-resolution export) and `api/sessions.py:302` open the original the same way.

## Decision

Always show the whole photo, letterboxed on neutral grey. That's what ui-guidelines and the
`.consultation__photo` comment already say ("Contain, never cover: the Customer's room is judged
whole"). Always apply the EXIF orientation on the service side (a technical call; harmless when
there's no tag).

## Method of fixing

### Part 1: fit the frame to the stage (CSS container query, tested)

1. In `ConsultationSurface.tsx`, wrap the frame in a new slot element and set the ratio as a custom
   property alongside `aspect-ratio`:

   ```tsx
   <div className="consultation__picture">
     <div className="consultation__frame-slot">
       <div
         className="consultation__frame"
         style={photoAspectRatio
           ? ({ aspectRatio: photoAspectRatio, '--photo-ratio': photoAspectRatio } as CSSProperties)
           : undefined}
       >
         …img, overlays, chips, tap layer unchanged…
       </div>
     </div>
     …status line / notes stay outside the slot…
   </div>
   ```

2. In `consultation.css`:

   ```css
   .consultation__picture { width: 100%; height: 100%; }   /* now definite, from the stage */

   /* The box the photo may occupy. A size container, so the frame can be sized against both axes. */
   .consultation__frame-slot {
     flex: 1; min-height: 0; width: 100%;
     container-type: size;
     display: flex; align-items: center; justify-content: center;
   }

   .consultation__frame {
     position: relative;
     width: min(100cqw, calc(100cqh * var(--photo-ratio, 1)));
     height: auto;           /* aspect-ratio derives it */
   }
   ```

   The frame stays exactly the image's box at every ratio, so the overlay, chips and tap layer
   (all `position: absolute; inset: 0`) stay aligned. Difficulty #23's invariant holds. Electron's
   Chromium supports `container-type: size` and `cq*` units.
3. Rewrite the long comment above `.consultation__frame` (`:76-91`): the rule is now "the slot is
   the stage's free space; the frame is the largest box of the photo's ratio that fits it".

### Part 2: one set of pixels for photo, matte and render (EXIF)

1. `decode_photo`: `image = ImageOps.exif_transpose(image)` before `.convert("RGB")`. Do the same in
   `exports.py:202` so the full-resolution export matches.
2. Show the **prepared** photo, not the raw upload. The service already serves it as
   `GET /consultations/{id}/photo/png` (`api/bundles.py:198`), which reopening a Consultation
   reaches through `apps/desktop/src/stored-image-bridge.ts`. That route only answers **after** the
   first repaint, because `persist_preparation` (`api/sessions.py:125-147`) is called from
   `require_photo`, the render gate. So for a first load, either:
   - **(preferred)** add `GET /sessions/{session_id}/photo/png`, which serves the in-memory prepared
     `srgb` through the same stored-image bridge pattern. It's a REST contract addition (test seam 1),
     so update the contract-pinning test (difficulty #18 notes that it counts routes); or
   - persist the preparation when preparation reaches `done` instead of at the first render.

   Swap `state.imageDataUrl` for the prepared image once preparation finishes. The raw upload can
   stay on screen as a placeholder while preparation runs. That way what the Dealer sees is exactly
   what was segmented.
3. Record it in `docs/implementation-decisions.md` (why the displayed image is the prepared one).

## Docs to amend

- `consultation.css` comments on `.consultation__frame` / `.consultation__picture`.
- `docs/technical-difficulties.md`: new entry, "The frame fitted the tap layer but not the stage", as
  a follow-up to #23.
- `docs/implementation-decisions.md`: EXIF transpose and displaying the prepared photo.

## Tests

- **UI unit** (`apps/ui/src/consultation/*.test.ts`): a pure helper `frameSize(stageW, stageH,
  ratio)` if the sizing is ever moved to JS; otherwise a Playwright/Electron screenshot check is
  the honest test. Assert that the frame's bounding box is inside the stage's content box for ratios
  0.5, 0.75, 1.33 and 1.78.
- **Service** (`services/inference/tests/api/test_sessions.py`): upload a JPEG whose pixels are
  landscape with EXIF Orientation = 6. Assert that the prepared photo and every matte are portrait
  (height > width).

## Acceptance criteria

- [ ] At 1280×720 and 1920×1080 windows, 4:3, 3:4 and 16:9 photos are fully visible, letterboxed on
      grey. No part of the photo is clipped.
- [ ] Wall overlay, wall chips and correction taps still align with the photo at every ratio
      (re-run the #23 check).
- [ ] A phone photo with EXIF Orientation 6 or 8 shows upright, and its overlay and repaint are
      upright and aligned.
- [ ] Full-resolution export is upright.

## Related

[Bug 3](./03-colour-faint-when-selected.md) touches the same overlay layer; do them together.
