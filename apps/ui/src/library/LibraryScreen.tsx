import { useEffect, useState } from 'react';

import { Button } from '../components/Button';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { ProgressMessage } from '../components/ProgressMessage';
import { SettingsModal } from '../components/SettingsModal';
import { Toast } from '../components/Toast';
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
  onNewConsultationInBundle,
  onOpenStorage,
}: {
  library: Library;
  onReopened: (reopened: {
    consultationId: string;
    sessionId: string;
    imageDataUrl: string;
  }) => void;
  onNewConsultation: () => void;
  onNewConsultationInBundle: (bundleId: string) => void;
  onOpenStorage?: () => void;
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
    return (
      <BundleDetail
        library={library}
        onOpen={library.openConsultation}
        onNewConsultationInBundle={onNewConsultationInBundle}
      />
    );
  }
  return (
    <BundleList
      library={library}
      onNewConsultation={onNewConsultation}
      onOpenStorage={onOpenStorage}
    />
  );
}

function BundleList({
  library,
  onNewConsultation,
  onOpenStorage,
}: {
  library: Library;
  onNewConsultation: () => void;
  onOpenStorage?: () => void;
}) {
  const [newName, setNewName] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [qualityTier, setQualityTier] = useState<string>('better');

  const startEditing = (bundleId: string, currentName: string) => {
    setEditingId(bundleId);
    setEditingName(currentName);
  };

  const commitRename = () => {
    if (!editingId) return;
    const name = editingName.trim();
    if (!name) return;
    void library.renameBundle(editingId, name).then(() => {
      setEditingId(null);
      setEditingName('');
    });
  };

  const handleQualityTierChange = async (tier: string) => {
    // Validate the tier before attempting to set it
    if (tier !== 'faster' && tier !== 'better') {
      console.error(`Invalid quality tier: ${tier}`);
      return;
    }

    try {
      // Use the exposed spectrapaint API to set the quality tier
      await window.spectrapaint.setQualityTier(tier);
      setQualityTier(tier);
    } catch (error) {
      console.error('Failed to set quality tier:', error);
      // In a production app, we would show an error to the user
    }
  };

  // Load the current quality tier from the service when the component mounts
  useEffect(() => {
    const loadQualityTier = async () => {
      try {
        const tier = await window.spectrapaint.getQualityTier();
        if (tier === 'faster' || tier === 'better') {
          setQualityTier(tier);
        } else {
          // Default to better if we get an unexpected value
          setQualityTier('better');
        }
      } catch (error) {
        console.error('Failed to get quality tier:', error);
        // Default to better if we can't get it
        setQualityTier('better');
      }
    };

    loadQualityTier();
  }, []);

  return (
    <main className="library">
      <header className="library__bar">
        <h1 className="library__title">Bundles</h1>
        <div className="library__bar-actions">
          <Button onClick={onNewConsultation}>New consultation</Button>
          {onOpenStorage ? <Button onClick={onOpenStorage}>Storage</Button> : null}
          <Button onClick={() => setIsSettingsOpen(true)}>Settings</Button>
        </div>
      </header>

      {library.message ? (
        <ErrorState
          message={library.message}
          actionLabel="Try again"
          onAction={() => void library.refreshBundles()}
        />
      ) : null}

      {library.lastDeleted ? (
        <Toast
          message={`Bundle “${library.lastDeleted.name}” deleted — consultations moved to Consultations.`}
          actionLabel="Undo"
          onAction={() => void library.undoDeleteBundle()}
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

      {!library.bundlesLoaded ? <ProgressMessage>Loading your bundles…</ProgressMessage> : null}

      <ul className="library__list">
        {library.bundles.map((bundle) => (
          <li key={bundle.bundle_id} className="library__row">
            {editingId === bundle.bundle_id ? (
              <form
                className="library__create library__row--editing"
                onSubmit={(event) => {
                  event.preventDefault();
                  commitRename();
                }}
              >
                <input
                  className="library__input"
                  value={editingName}
                  maxLength={80}
                  onChange={(event) => setEditingName(event.target.value)}
                  aria-label="Bundle name"
                  autoFocus
                />
                <Button type="submit" disabled={!editingName.trim()}>
                  Save
                </Button>
                <Button
                  type="button"
                  className="library__small-action"
                  onClick={() => {
                    setEditingId(null);
                    setEditingName('');
                  }}
                >
                  Cancel
                </Button>
              </form>
            ) : (
              <>
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
                {!bundle.is_default ? (
                  <>
                    <Button
                      className="library__small-action"
                      onClick={() => startEditing(bundle.bundle_id, bundle.name)}
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
              </>
            )}
          </li>
        ))}
      </ul>

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onQualityTierChange={handleQualityTierChange}
        currentQualityTier={qualityTier}
      />
    </main>
  );
}

function BundleDetail({
  library,
  onOpen,
  onNewConsultationInBundle,
}: {
  library: Library;
  onOpen: (consultationId: string) => void;
  onNewConsultationInBundle: (bundleId: string) => void;
}) {
  const openId = library.openBundleId ?? '';
  return (
    <main className="library">
      <header className="library__bar">
        <Button onClick={library.backToBundles}>All bundles</Button>
        <h1 className="library__title">Consultations</h1>
        <Button onClick={() => onNewConsultationInBundle(openId)}>New consultation</Button>
      </header>

      {library.message ? (
        <ErrorState
          message={library.message}
          actionLabel="Try again"
          onAction={() => void library.openBundle(openId)}
        />
      ) : null}

      {library.lastDeleted ? (
        <Toast
          message={`Bundle “${library.lastDeleted.name}” deleted.`}
          actionLabel="Undo"
          onAction={() => void library.undoDeleteBundle()}
        />
      ) : null}

      {library.consultations === null ? (
        <ProgressMessage>Loading…</ProgressMessage>
      ) : library.consultations.length === 0 ? (
        <EmptyState message="No consultations in this bundle yet." />
      ) : (
        <ul className="library__list">
          {library.consultations.map((consultation) => (
            <ConsultationRow
              key={consultation.consultation_id}
              consultation={consultation}
              onOpen={onOpen}
              library={library}
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
  library,
}: {
  consultation: ConsultationSummary;
  onOpen: (consultationId: string) => void;
  library: Library;
}) {
  const [moving, setMoving] = useState(false);

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
      {library.bundles.length > 1 ? (
        moving ? (
          <select
            className="library__input library__move-select"
            defaultValue=""
            aria-label="Move to bundle"
            onChange={(event) => {
              const bundleId = event.target.value;
              if (!bundleId) {
                setMoving(false);
                return;
              }
              void library
                .placeConsultation(bundleId, consultation.consultation_id)
                .then(() => setMoving(false));
            }}
            onBlur={() => setMoving(false)}
            autoFocus
          >
            <option value="" disabled>
              Move to…
            </option>
            {library.bundles
              .filter((b) => b.bundle_id !== library.openBundleId)
              .map((b) => (
                <option key={b.bundle_id} value={b.bundle_id}>
                  {b.name}
                </option>
              ))}
          </select>
        ) : (
          <Button className="library__small-action" onClick={() => setMoving(true)}>
            Move
          </Button>
        )
      ) : null}
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
          onAction={() => void library.retryConsultation()}
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
      {library.renders === null && !library.message ? (
        <ProgressMessage>Loading…</ProgressMessage>
      ) : null}
      {library.renders !== null && library.renders.length === 0 ? (
        <EmptyState message="No shade has been tried in this consultation yet." />
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
