import { CataloguePanel } from '../catalogue/CataloguePanel';
import { useCatalogue } from '../catalogue/useCatalogue';
import { Button } from '../components/Button';
import { ErrorState } from '../components/ErrorState';
import { ProgressMessage } from '../components/ProgressMessage';
import type { Consultation } from './useConsultation';
import { overlayVisible } from './walls';

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
  } = consultation;
  const catalogue = useCatalogue();

  if (state.phase === 'ready') {
    // The repaint replaces the photo on screen; the toggle returns to the original. Before that,
    // the Room Photo the Dealer loaded is what the wall is judged against.
    const visibleImage =
      render.showingRender && render.imageDataUrl ? render.imageDataUrl : state.imageDataUrl;

    const showWalls = overlayVisible(walls, render.showingRender);

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
            {render.phase === 'ready' ? (
              <Button onClick={toggleBeforeAfter}>
                {render.showingRender ? 'Show original photo' : 'Show repaint'}
              </Button>
            ) : null}
            <Button onClick={discard}>Discard photo</Button>
          </div>
        </div>
        <div className="consultation__work">
          <div className="consultation__stage">
            <div className="consultation__picture">
              <img
                className="consultation__photo"
                src={visibleImage}
                alt="The Customer's room photo"
              />
              {showWalls
                ? walls.planes.map((plane) => (
                    // The matte is applied as a CSS mask, so the wash appears exactly where the
                    // Alpha Matte says the wall is — including its soft edge, which a border or an
                    // outline could not express.
                    <div
                      key={plane.planeId}
                      className="consultation__wall-overlay"
                      style={{
                        maskImage: `url(${plane.matteDataUrl})`,
                        WebkitMaskImage: `url(${plane.matteDataUrl})`,
                      }}
                      aria-hidden="true"
                    />
                  ))
                : null}
              {showWalls ? (
                <p className="consultation__wall-note">
                  {walls.planes.length === 1
                    ? 'This is the wall SpectraPaint found.'
                    : `SpectraPaint found ${walls.planes.length} walls.`}
                </p>
              ) : null}
              {walls.message ? <p className="consultation__wall-note">{walls.message}</p> : null}
              {render.phase === 'rendering' ? (
                <ProgressMessage>Repainting the wall…</ProgressMessage>
              ) : null}
              {render.phase === 'failed' && render.message ? (
                <ErrorState
                  message={render.message}
                  actionLabel="Choose another Shade"
                  onAction={dismissRender}
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
