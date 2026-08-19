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
 * The Catalogue is a panel here rather than a screen of its own: the Dealer is choosing a Shade for
 * the room in front of them, and sending them elsewhere to do it loses the photo they are choosing
 * against (docs/specs/v1-spectrapaint.md).
 *
 * Every state is defined: nothing loaded, loading, loaded, and a failure that always offers the
 * next action (docs/ui-guidelines.md — never a dead end).
 */
export function ConsultationSurface({ consultation }: { consultation: Consultation }) {
  const { state, start, discard } = consultation;
  const catalogue = useCatalogue();

  if (state.phase === 'ready') {
    return (
      <main className="consultation">
        <div className="consultation__bar">
          <h1 className="consultation__title">Consultation</h1>
          <Button onClick={discard}>Discard photo</Button>
        </div>
        <div className="consultation__work">
          <div className="consultation__stage">
            <img
              className="consultation__photo"
              src={state.imageDataUrl}
              alt="The Customer's room photo"
            />
          </div>
          <CataloguePanel catalogue={catalogue} />
        </div>
      </main>
    );
  }

  return (
    <main className="consultation consultation--start">
      <h1 className="consultation__title">New Consultation</h1>

      {state.phase === 'uploading' ? (
        <ProgressMessage>Loading your photo…</ProgressMessage>
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
