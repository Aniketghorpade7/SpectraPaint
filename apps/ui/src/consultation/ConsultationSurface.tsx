import { useState, type CSSProperties, type MouseEvent, type SyntheticEvent } from 'react';

import { CataloguePanel } from '../catalogue/CataloguePanel';
import { useCatalogue } from '../catalogue/useCatalogue';
import { Button } from '../components/Button';
import { ErrorState } from '../components/ErrorState';
import { ProgressMessage } from '../components/ProgressMessage';
import { describePlane, describeTarget, isTargeted } from './accent';
import { describeArmedTool, tapPointFromFraction } from './corrections';
import type { Consultation } from './useConsultation';
import { overlayVisible } from './walls';
import { WallOutlineCanvas } from './WallOutlineCanvas';

/**
 * The Consultation surface: one action to load a Room Photo, the photo on screen, the Catalogue
 * panel beside it (issue #5), the walls SpectraPaint found outlined over the photo (issue #6), and
 * a way to end it. Deliberately thin — splitting the wall into separate planes and persistence
 * arrive with later tickets.
 *
 * The wall overlay is a white wash rather than the coloured mask a segmentation demo would use, and
 * it takes itself off screen the moment there is a repaint to look at — see walls.ts, and
 * ui-guidelines.md on why nothing may sit near the colour a Customer is judging.
 *
 * From issue #7 a photo with more than one wall lets the Dealer paint them separately: tapping a
 * wall chooses it, and the next Shade lands only there, so an Accent Wall costs one extra tap and
 * painting the whole room still costs none. Tapping the chosen wall again goes back to painting them
 * all — a toggle rather than a confirmation, which is a tap the budget cannot afford.
 *
 * From issue #3, the photo repaints when a Shade is tapped: the render replaces the photo, a
 * before/after toggle returns to the original, a repaint in flight is a visible state rather than a
 * frozen swatch, and a failed repaint shows the service's message with the photo still reachable
 * (docs/ui-guidelines.md — never a dead end).
 *
 * The Catalogue is a panel here rather than a screen of its own: the Dealer is choosing a Shade for
 * the room in front of them, and sending them elsewhere to do it loses the photo they are choosing
 * against (docs/specs/v1-spectrapaint.md).
 *
 * Every state is defined: nothing loaded, loading, loaded, and a failure that always offers the
 * next action (docs/ui-guidelines.md — never a dead end).
 */
export function ConsultationSurface({ consultation }: { consultation: Consultation }) {
  const {
    state,
    start,
    discard,
    render,
    applyShade,
    toggleBeforeAfter,
    dismissRender,
    walls,
    toggleWalls,
    paint,
    selectWall,
    renderMode,
    toggleRenderMode,
    armedTool,
    armTool,
    correctWallsAt,
    correctionMessage,
    correctionCode,
    exportState,
    exportRender,
    dismissExport,
  } = consultation;
  const catalogue = useCatalogue();
  // The displayed image's own aspect ratio, read off it once it decodes. Sets the exact box the
  // wall overlay, the wall-chip buttons and the correction tap-layer all align to — see
  // consultation.css on `.consultation__frame` for why this cannot be answered from CSS alone.
  // Recomputed on every image swap, which matters twice over: the repaint and the original share
  // one ratio, but the prepared photo (issue #49) need not share the raw upload's — an oriented
  // phone photo swaps from a landscape placeholder to a portrait prepared photo, and the frame
  // follows the pixels that are actually on screen.
  //
  // Remembered with the image it was read from: the frame may keep the previous ratio for the
  // instant a new image is decoding, but nothing that has to align with the pixels (overlay,
  // outline, chips, tap layer) may be drawn until the ratio belongs to the image on screen.
  const [photoFrame, setPhotoFrame] = useState<{ src: string; ratio: number } | null>(null);
  const photoAspectRatio = photoFrame?.ratio ?? null;

  function handlePhotoLoad(event: SyntheticEvent<HTMLImageElement>) {
    const image = event.currentTarget;
    if (image.naturalWidth > 0 && image.naturalHeight > 0) {
      setPhotoFrame({
        src: image.currentSrc || image.src,
        ratio: image.naturalWidth / image.naturalHeight,
      });
    }
  }

  if (state.phase === 'ready') {
    // The repaint replaces the photo on screen; the toggle returns to the original. Before that,
    // the Room Photo the Dealer loaded is what the wall is judged against.
    const visibleImage =
      render.showingRender && render.imageDataUrl ? render.imageDataUrl : state.imageDataUrl;

    // One rule for the whole overlay, from walls.ts: never on screen while a repaint shows — not
    // for the Dealer's show/hide choice, and not for an armed tool (issue #49). A tool armed keeps
    // the overlay up regardless of the Dealer's earlier hide/show choice, because correcting walls
    // that are not visible is not a thing a Dealer can do (ticket #10) — but only while the photo,
    // not the render, is what is on screen.
    // And never before the frame has taken the ratio of the image now on screen: right after the
    // prepared photo replaces the upload, the frame still has the placeholder's ratio for a moment,
    // and an oriented photo's mattes would sit on the wrong rectangle (issue #49).
    const frameMatchesImage = photoFrame !== null && photoFrame.src === visibleImage;
    const showWalls = overlayVisible(walls, render.showingRender, armedTool) && frameMatchesImage;
    // Wall-only counts (issue #39): the ceiling is its own surface and never takes a wall's
    // positional name, so neither the chips' totals nor "found N walls" may count it.
    const wallPlanes = walls.planes.filter((plane) => plane.surface !== 'ceiling');
    const wallCount = wallPlanes.length;

    function handlePhotoTap(event: MouseEvent<HTMLButtonElement>) {
      if (walls.photoWidth <= 0 || walls.photoHeight <= 0) return;
      const rect = event.currentTarget.getBoundingClientRect();
      correctWallsAt(
        tapPointFromFraction(
          (event.clientX - rect.left) / rect.width,
          (event.clientY - rect.top) / rect.height,
          walls.photoWidth,
          walls.photoHeight,
        ),
      );
    }

    return (
      <main className="consultation">
        <div className="consultation__bar">
          <h1 className="consultation__title">Consultation</h1>
          <div className="consultation__bar-actions">
            {walls.planes.length > 0 && !render.showingRender ? (
              <Button onClick={toggleWalls}>
                {walls.wanted ? 'Hide the walls found' : 'Show the walls found'}
              </Button>
            ) : null}
            {!render.showingRender ? (
              <>
                <Button onClick={() => armTool('add')} aria-pressed={armedTool === 'add'}>
                  Add a wall
                </Button>
                {!walls.planes.some((p) => p.surface === 'ceiling') ? (
                  <Button
                    onClick={() => armTool('add-ceiling')}
                    aria-pressed={armedTool === 'add-ceiling'}
                  >
                    Add ceiling
                  </Button>
                ) : null}
                {walls.planes.length >= 1 ? (
                  <Button onClick={() => armTool('split')} aria-pressed={armedTool === 'split'}>
                    Split a wall
                  </Button>
                ) : null}
                {walls.planes.length >= 2 ? (
                  <Button onClick={() => armTool('merge')} aria-pressed={armedTool === 'merge'}>
                    Merge walls
                  </Button>
                ) : null}
              </>
            ) : null}
            {render.phase === 'ready' ? (
              <Button onClick={toggleBeforeAfter}>
                {render.showingRender ? 'Show original photo' : 'Show repaint'}
              </Button>
            ) : null}
            <Button onClick={toggleRenderMode} aria-pressed={renderMode === 'true_colour'}>
              {renderMode === 'realistic' ? 'True Colour mode' : 'Realistic mode'}
            </Button>
            {render.phase === 'ready' ? (
              <Button onClick={exportRender} disabled={exportState.phase === 'exporting'}>
                {exportState.phase === 'exporting' ? 'Exporting…' : 'Export and share'}
              </Button>
            ) : null}
            <Button onClick={discard}>Discard photo</Button>
          </div>
        </div>
        <div className="consultation__work">
          <div className="consultation__stage">
            <div className="consultation__picture">
              {/* The slot is the stage's free space; the frame is the largest box of the photo's
                  ratio that fits it (consultation.css). Everything the photo carries — overlay,
                  outline, chips, tap layer — lives inside the frame; every status line and note
                  stays outside the slot, under the photo. */}
              <div className="consultation__frame-slot">
                <div
                  className="consultation__frame"
                  style={
                    photoAspectRatio
                      ? ({
                          aspectRatio: photoAspectRatio,
                          '--photo-ratio': photoAspectRatio,
                        } as CSSProperties)
                      : undefined
                  }
                >
                  <img
                    className="consultation__photo"
                    src={visibleImage}
                    alt="The Customer's room photo"
                    onLoad={handlePhotoLoad}
                  />
                  {showWalls
                    ? walls.planes.map((plane) => (
                        // The matte is applied as a CSS mask, so the wash appears exactly where the
                        // Alpha Matte says the wall is — including its soft edge, which a border or
                        // an outline could not express. Every detected wall gets the same weak wash;
                        // the *chosen* one is marked by the outline below, never by a stronger wash
                        // here — that would make the wall being judged paler than the others
                        // (issue #49).
                        <div
                          key={plane.planeId}
                          className="consultation__wall-overlay"
                          style={{ maskImage: `url(${plane.matteDataUrl})` }}
                          aria-hidden="true"
                        />
                      ))
                    : null}
                  {showWalls
                    ? walls.planes
                        .filter((plane) => isTargeted(paint.target, plane.planeId))
                        .map((plane) => (
                          // The chosen wall's mark: an outline along its matte edge, never a wash —
                          // the Customer judges this very wall's colour (issue #49). The tap layer,
                          // when armed, sits above it; the outline is pointer-events: none, so the
                          // tap reaches the layer regardless.
                          <WallOutlineCanvas
                            key={`outline-${plane.planeId}`}
                            matteDataUrl={plane.matteDataUrl}
                          />
                        ))
                    : null}
                  {showWalls && armedTool === null && walls.planes.length > 1
                    ? walls.planes.map((plane, index) => (
                        // Choosing a wall is a real `<button>`: a div with a click handler is not
                        // one (ui-guidelines.md), and choosing the accent wall by keyboard has to
                        // work. It is a chip over the wall rather than the wash itself, because a
                        // mask clips what is painted and not what is clickable — two full-size
                        // masked buttons would overlap, and the upper one would swallow every tap
                        // meant for the lower.
                        <button
                          key={`choose-${plane.planeId}`}
                          type="button"
                          className={
                            isTargeted(paint.target, plane.planeId)
                              ? 'consultation__wall-chip consultation__wall-chip--chosen'
                              : 'consultation__wall-chip'
                          }
                          style={chipPosition(plane, index, wallCount)}
                          aria-pressed={isTargeted(paint.target, plane.planeId)}
                          onClick={() => selectWall(plane.planeId)}
                        >
                          {describePlane(plane, index, wallCount)}
                          {paint.assignments[plane.planeId]
                            ? ` · ${paint.assignments[plane.planeId]}`
                            : ''}
                        </button>
                      ))
                    : null}
                  {showWalls && armedTool !== null ? (
                    // The correction surface itself: one tool armed at a time (ticket #10). A real
                    // `<button>` covering the photo — the same reason the chip above is a button
                    // and not a div — with no chrome of its own, since the room photo is what it
                    // sits on. Gated on `showWalls`, which is false while a render shows (walls.ts),
                    // so no tap layer ever sits over a repaint either (issue #49).
                    <button
                      type="button"
                      className="consultation__tap-layer"
                      aria-label={describeArmedTool(armedTool)}
                      onClick={handlePhotoTap}
                    />
                  ) : null}
                </div>
              </div>
              {showWalls ? (
                <p className="consultation__wall-note">
                  {armedTool !== null
                    ? describeArmedTool(armedTool)
                    : wallCount === 1
                      ? 'This is the wall SpectraPaint found.'
                      : `SpectraPaint found ${wallCount} walls. ${describeTarget(
                          paint.target,
                          walls.planes,
                        )}`}
                </p>
              ) : null}
              {state.photoNotice ? (
                <p className="consultation__wall-note">{state.photoNotice}</p>
              ) : null}
              {walls.message ? <p className="consultation__wall-note">{walls.message}</p> : null}
              {walls.qualityNote ? (
                // The photo's own warning (issue #15) — dark, blurred or heavily clipped — shown
                // regardless of whether a wall was found, since it says nothing about the walls.
                <p className="consultation__wall-note">{walls.qualityNote}</p>
              ) : null}
              {correctionMessage && correctionCode !== 'session_not_found' ? (
                <p className="consultation__wall-note">{correctionMessage}</p>
              ) : null}
              {correctionMessage && correctionCode === 'session_not_found' ? (
                // A sidecar restart, not a refused tap (issue #15) — the walls the Dealer sees are
                // frozen at whatever they were, and no further tap here can ever succeed.
                <ErrorState
                  message={correctionMessage}
                  actionLabel="Go to Bundles"
                  onAction={discard}
                />
              ) : null}
              {render.phase === 'rendering' ? (
                <ProgressMessage>Repainting the wall…</ProgressMessage>
              ) : null}
              {render.phase === 'failed' && render.message ? (
                <ErrorState
                  message={render.message}
                  actionLabel={
                    render.code === 'session_not_found' ? 'Go to Bundles' : 'Choose another Shade'
                  }
                  onAction={render.code === 'session_not_found' ? discard : dismissRender}
                />
              ) : null}
              {exportState.phase === 'exporting' ? (
                <ProgressMessage>Preparing your export…</ProgressMessage>
              ) : null}
              {exportState.phase === 'ready' && exportState.filename ? (
                <p className="consultation__wall-note">
                  Exported {exportState.filename} — choose another Shade to keep browsing.
                </p>
              ) : null}
              {exportState.phase === 'failed' && exportState.message ? (
                <ErrorState
                  message={exportState.message}
                  actionLabel="Try export again"
                  onAction={dismissExport}
                />
              ) : null}
            </div>
          </div>
          <CataloguePanel catalogue={catalogue} onShadeSelected={applyShade} />
        </div>
      </main>
    );
  }

  return (
    <main className="consultation consultation--start">
      <h1 className="consultation__title">New Consultation</h1>

      {state.phase === 'uploading' ? (
        <ProgressMessage>{state.progressMessage ?? 'Loading your photo…'}</ProgressMessage>
      ) : (
        <p className="consultation__hint">
          Start with a photo of the Customer's room. The paint is chosen next.
        </p>
      )}

      {state.phase === 'failed' && state.message ? (
        <ErrorState message={state.message} actionLabel="Try another photo" onAction={start} />
      ) : (
        <Button onClick={start} disabled={state.phase === 'uploading'}>
          Choose a Room Photo
        </Button>
      )}
    </main>
  );
}

/**
 * Where a wall's chooser sits: over the middle of that wall's bounding box.
 *
 * Percentages of the photo, so the chip stays on its wall however the photo is scaled to the stage.
 * A plane with no bounds — the service may report none — falls back to spacing the chips evenly, so
 * the choice is still reachable rather than stacked in one corner.
 */
function chipPosition(
  plane: {
    bounds: { left: number; top: number; right: number; bottom: number } | null;
    photoWidth: number;
    photoHeight: number;
  },
  index: number,
  total: number,
): { left: string; top: string } {
  if (!plane.bounds || plane.photoWidth <= 0 || plane.photoHeight <= 0) {
    return { left: `${((index + 1) / (total + 1)) * 100}%`, top: '50%' };
  }
  const centreX = (plane.bounds.left + plane.bounds.right) / 2 / plane.photoWidth;
  const centreY = (plane.bounds.top + plane.bounds.bottom) / 2 / plane.photoHeight;
  return { left: `${centreX * 100}%`, top: `${centreY * 100}%` };
}
