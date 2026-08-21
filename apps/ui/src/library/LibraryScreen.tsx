import { useEffect, useState } from 'react';

import { Button } from '../components/Button';
import { ErrorState } from '../components/ErrorState';
import type { ConsultationSummary, RenderRecord } from './types';
import { shadesOf } from './types';
import type { Library } from './useLibrary';
import './library.css';

/**
 * The Bundles screen — where the app now lands after boot (issue #11).
 *
 * Three levels, one screen at a time: the Bundles (the Dealer's jobs), the Consultations in one
 * Bundle, and one Consultation's saved renders. Reopening is the point of the whole screen: it
 * puts back exactly what the Customer saw last time, and "Continue" picks the work up without
 * waiting for preparation to run again.
 */

export function LibraryScreen({
  library,
  onReopened,
  onNewConsultation,
}: {
  library: Library;
  onReopened: (reopened: {
    consultationId: string;
    sessionId: string;
    imageDataUrl: string;
  }) => void;
  onNewConsultation: () => void;
}) {
  if (library.openConsultationId) {
    return (
      <ConsultationHistory
        library={library}
        onReopened={onReopened}
        onBack={library.backToBundle}
      />
    );
  }
  if (library.openBundleId) {
    return <BundleDetail library={library} onOpen={library.openConsultation} />;
  }
  return <BundleList library={library} onNewConsultation={onNewConsultation} />;
}

function BundleList({
  library,
  onNewConsultation,
}: {
  library: Library;
  onNewConsultation: () => void;
}) {
  const [newName, setNewName] = useState('');

  return (
    <main className="library">
      <header className="library__bar">
        <h1 className="library__title">Bundles</h1>
        <Button onClick={onNewConsultation}>New consultation</Button>
      </header>

      {library.message ? (
        <ErrorState
          message={library.message}
          actionLabel="Try again"
          onAction={() => void library.refreshBundles()}
        />
      ) : null}

      <form
        className="library__create"
        onSubmit={(event) => {
          event.preventDefault();
          const name = newName.trim();
          if (!name) return;
          void library.createBundle(name).then((created) => created && setNewName(''));
        }}
      >
        <input
          className="library__input"
          value={newName}
          placeholder="Name a new bundle…"
          maxLength={80}
          onChange={(event) => setNewName(event.target.value)}
          aria-label="New bundle name"
        />
        <Button type="submit" disabled={!newName.trim()}>
          Create bundle
        </Button>
      </form>

      <ul className="library__list">
        {library.bundles.map((bundle) => (
          <li key={bundle.bundle_id} className="library__row">
            <button
              type="button"
              className="library__open"
              onClick={() => void library.openBundle(bundle.bundle_id)}
            >
              <span className="library__name">{bundle.name}</span>
              <span className="library__meta">
                {bundle.consultation_count === 1
                  ? '1 consultation'
                  : `${bundle.consultation_count} consultations`}
              </span>
            </button>
            {bundle.name !== 'Consultations' ? (
              <>
                <Button
                  className="library__small-action"
                  onClick={() => {
                    const name = window.prompt('Rename this bundle', bundle.name);
                    if (name && name.trim()) void library.renameBundle(bundle.bundle_id, name);
                  }}
                >
                  Rename
                </Button>
                <Button
                  className="library__small-action"
                  onClick={() => void library.deleteBundle(bundle.bundle_id)}
                >
                  Delete
                </Button>
              </>
            ) : null}
          </li>
        ))}
      </ul>
    </main>
  );
}

function BundleDetail({
  library,
  onOpen,
}: {
  library: Library;
  onOpen: (consultationId: string) => void;
}) {
  return (
    <main className="library">
      <header className="library__bar">
        <Button onClick={library.backToBundles}>All bundles</Button>
        <h1 className="library__title">Consultations</h1>
      </header>

      {library.message ? (
        <ErrorState
          message={library.message}
          actionLabel="Try again"
          onAction={() => void library.refreshBundles()}
        />
      ) : null}

      {library.consultations === null ? (
        <p className="library__meta">Loading…</p>
      ) : library.consultations.length === 0 ? (
        <p className="library__hint">No consultations in this bundle yet.</p>
      ) : (
        <ul className="library__list">
          {library.consultations.map((consultation) => (
            <ConsultationRow
              key={consultation.consultation_id}
              consultation={consultation}
              onOpen={onOpen}
            />
          ))}
        </ul>
      )}
    </main>
  );
}

function ConsultationRow({
  consultation,
  onOpen,
}: {
  consultation: ConsultationSummary;
  onOpen: (consultationId: string) => void;
}) {
  return (
    <li className="library__row">
      <button
        type="button"
        className="library__open"
        onClick={() => onOpen(consultation.consultation_id)}
      >
        <span className="library__name">
          Consultation of {new Date(consultation.created_at).toLocaleString()}
        </span>
        <span className="library__meta">
          {consultation.render_count === 1
            ? '1 repaint shown'
            : `${consultation.render_count} repaints shown`}
        </span>
      </button>
    </li>
  );
}

function ConsultationHistory({
  library,
  onReopened,
  onBack,
}: {
  library: Library;
  onReopened: (reopened: {
    consultationId: string;
    sessionId: string;
    imageDataUrl: string;
  }) => void;
  onBack: () => void;
}) {
  const [continuing, setContinuing] = useState(false);

  const continueConsultation = async () => {
    setContinuing(true);
    try {
      const reopened = await library.reopen();
      if (reopened) onReopened(reopened);
    } finally {
      setContinuing(false);
    }
  };

  return (
    <main className="library">
      <header className="library__bar">
        <Button onClick={onBack}>Back</Button>
        <h1 className="library__title">Saved consultation</h1>
        <Button onClick={() => void continueConsultation()} disabled={continuing}>
          {continuing ? 'Opening…' : 'Continue this consultation'}
        </Button>
      </header>

      {library.message ? (
        <ErrorState
          message={library.message}
          actionLabel="Try again"
          onAction={() => void library.refreshBundles()}
        />
      ) : null}

      {library.photoDataUrl ? (
        <img
          className="library__photo"
          src={library.photoDataUrl}
          alt="The room photo as prepared"
        />
      ) : null}

      <h2 className="library__subtitle">Shades already tried</h2>
      {library.renders !== null && library.renders.length === 0 ? (
        <p className="library__hint">No shade has been tried in this consultation yet.</p>
      ) : null}
      <div className="library__renders">
        {(library.renders ?? []).map((render) => (
          <StoredRender
            key={render.render_id}
            render={render}
            consultationId={library.openConsultationId ?? ''}
          />
        ))}
      </div>
    </main>
  );
}

function StoredRender({
  render,
  consultationId,
}: {
  render: RenderRecord;
  consultationId: string;
}) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  // The image loads when its card does; a failure keeps the card, with the facts that matter —
  // which shades, in which mode — still readable.
  useEffect(() => {
    let cancelled = false;
    void window.spectrapaint.storedImage(consultationId, render.render_id).then((result) => {
      if (cancelled) return;
      if (result.status === 'ready') setDataUrl(result.imageDataUrl);
      else setFailed(true);
    });
    return () => {
      cancelled = true;
    };
  }, [consultationId, render.render_id]);

  return (
    <figure className="library__render-card">
      {dataUrl ? (
        <img
          className="library__render-image"
          src={dataUrl}
          alt={`Repaint in ${shadesOf(render).join(', ')}`}
        />
      ) : (
        <div
          className={`library__render-image${failed ? ' library__render-image--failed' : ' library__render-image--empty'}`}
          aria-hidden="true"
        />
      )}
      <figcaption className="library__render-caption">
        <strong>{shadesOf(render).join(', ')}</strong> ·{' '}
        {render.mode === 'true_colour' ? 'true colour' : 'realistic'}
        <span className="library__meta">{new Date(render.created_at).toLocaleString()}</span>
      </figcaption>
    </figure>
  );
}
