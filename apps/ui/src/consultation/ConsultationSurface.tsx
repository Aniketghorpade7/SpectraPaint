import { CataloguePanel } from '../catalogue/CataloguePanel';
import { useCatalogue } from '../catalogue/useCatalogue';
import { Button } from '../components/Button';
import { ErrorState } from '../components/ErrorState';
import { ProgressMessage } from '../components/ProgressMessage';
import type { Consultation } from './useConsultation';

/**
 * The Consultation surface: one action to load a Room Photo, the photo on screen, the Catalogue
 * panel beside it (issue #5), and a way to end it. Deliberately thin — Wall Planes, applying the
 * chosen Shade to the render and persistence arrive with later tickets.
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
  const { state, start, discard, render, applyShade, toggleBeforeAfter, dismissRender } =
    consultation;
  const catalogue = useCatalogue();

  if (state.phase === 'ready') {
    // The repaint replaces the photo on screen; the toggle returns to the original. Before that,
    // the Room Photo the Dealer loaded is what the wall is judged against.
    const visibleImage =
      render.showingRender && render.imageDataUrl ? render.imageDataUrl : state.imageDataUrl;

    return (
      <main className="consultation">
        <div className="consultation__bar">
          <h1 className="consultation__title">Consultation</h1>
          <div className="consultation__bar-actions">
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
