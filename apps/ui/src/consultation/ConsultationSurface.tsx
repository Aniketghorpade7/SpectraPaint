import { Button } from '../components/Button';
import { ErrorState } from '../components/ErrorState';
import { ProgressMessage } from '../components/ProgressMessage';
import type { Consultation } from './useConsultation';

/**
 * The Consultation surface for issue #2: one action to load a Room Photo, the photo on screen, and
 * a way to end it. Deliberately thin — Wall Planes, Shade selection and persistence arrive with
 * later tickets.
 *
 * Every state is defined: nothing loaded, loading, loaded, and a failure that always offers the
 * next action (docs/ui-guidelines.md — never a dead end).
 */
export function ConsultationSurface({ consultation }: { consultation: Consultation }) {
  const { state, start, discard } = consultation;

  if (state.phase === 'ready') {
    return (
      <section className="consultation">
        <div className="consultation__bar">
          <h1 className="consultation__title">Consultation</h1>
          <Button onClick={discard}>Discard photo</Button>
        </div>
        <div className="consultation__stage">
          <img
            className="consultation__photo"
            src={state.imageDataUrl}
            alt="The Customer's room photo"
          />
        </div>
      </section>
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
