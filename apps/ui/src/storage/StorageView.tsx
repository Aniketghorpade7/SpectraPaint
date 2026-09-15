import { useEffect, useState } from 'react';

import { Button } from '../components/Button';
import { ErrorState } from '../components/ErrorState';
import { formatBytes } from './formatBytes';
import type { Storage } from './useStorage';
import './storage.css';

/**
 * Storage view (issue #13): bundles by space consumed, largest first,
 * so the Dealer can see what is filling the disk and act.
 *
 * Bundles and Consultations can both be deleted from here — since nothing
 * is deleted automatically, manual deletion has to be genuinely actionable.
 * The disk banner appears well before the disk is critically full and says
 * what to do, in plain language.
 */
export function StorageView({
  storage,
  onBack,
  onDeletedBundle,
}: {
  storage: Storage;
  onBack: () => void;
  onDeletedBundle?: () => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [consultations, setConsultations] = useState<
    Record<string, { consultation_id: string; created_at: string; render_count: number }[]>
  >({});

  const openBundle = async (bundleId: string) => {
    if (expanded === bundleId) {
      setExpanded(null);
      return;
    }
    setExpanded(bundleId);
    const result = await window.spectrapaint.request({
      path: `/bundles/${bundleId}/consultations`,
      method: 'GET',
    });
    if (result.ok) {
      const body = result.body as {
        consultations: { consultation_id: string; created_at: string; render_count: number }[];
      };
      setConsultations((prev) => ({ ...prev, [bundleId]: body.consultations ?? [] }));
    }
  };

  useEffect(() => {
    // Refresh consultations for expanded bundle after a delete.
    if (expanded) {
      void (async () => {
        const result = await window.spectrapaint.request({
          path: `/bundles/${expanded}/consultations`,
          method: 'GET',
        });
        if (result.ok) {
          const body = result.body as {
            consultations: { consultation_id: string; created_at: string; render_count: number }[];
          };
          setConsultations((prev) => ({ ...prev, [expanded]: body.consultations ?? [] }));
        }
      })();
    }
  }, [storage.bundles, expanded]);

  return (
    <main className="storage">
      <header className="library__bar">
        <Button onClick={onBack}>Back to Bundles</Button>
        <h1 className="library__title">Storage</h1>
      </header>

      {storage.disk?.low && storage.disk.warning ? (
        <div className="storage__warning" role="alert">
          <strong>Disk getting full.</strong> {storage.disk.warning}{' '}
          <span className="storage__meta">
            {formatBytes(storage.disk.free_bytes)} free of {formatBytes(storage.disk.total_bytes)}.
          </span>
        </div>
      ) : storage.disk ? (
        <p className="storage__meta">
          {formatBytes(storage.disk.free_bytes)} free of {formatBytes(storage.disk.total_bytes)}.
        </p>
      ) : null}

      {storage.message ? (
        <ErrorState
          message={storage.message}
          actionLabel="Try again"
          onAction={() => void storage.load()}
        />
      ) : null}

      {storage.loading ? (
        <p className="library__meta">Loading…</p>
      ) : storage.bundles.length === 0 ? (
        <p className="library__hint">
          No bundles yet. Storage will appear here once you save a consultation.
        </p>
      ) : (
        <ul className="library__list">
          {storage.bundles.map((bundle) => (
            <li key={bundle.bundle_id} className="library__row storage__row">
              <button
                type="button"
                className="library__open"
                onClick={() => void openBundle(bundle.bundle_id)}
              >
                <span className="library__name">{bundle.name}</span>
                <span className="library__meta">
                  {bundle.consultation_count === 1
                    ? '1 consultation'
                    : `${bundle.consultation_count} consultations`}{' '}
                  · {formatBytes(bundle.bytes)}
                </span>
              </button>
              {!bundle.is_default ? (
                <Button
                  className="library__small-action"
                  onClick={() => {
                    void storage.deleteBundle(bundle.bundle_id).then((ok) => {
                      if (ok) onDeletedBundle?.();
                    });
                  }}
                >
                  Delete bundle
                </Button>
              ) : null}
              <Button
                className="library__small-action"
                onClick={() => void openBundle(bundle.bundle_id)}
              >
                {expanded === bundle.bundle_id ? 'Hide' : 'Consultations'}
              </Button>
            </li>
          ))}
        </ul>
      )}

      {expanded ? (
        <section className="storage__consultations" aria-label="Consultations in bundle">
          <h2 className="library__subtitle">Consultations</h2>
          {(consultations[expanded] ?? []).length === 0 ? (
            <p className="library__hint">No consultations in this bundle.</p>
          ) : (
            <ul className="library__list">
              {(consultations[expanded] ?? []).map((c) => (
                <li key={c.consultation_id} className="library__row">
                  <span
                    className="library__open"
                    style={{ cursor: 'default' } as React.CSSProperties}
                  >
                    <span className="library__name">
                      Consultation of {new Date(c.created_at).toLocaleString()}
                    </span>
                    <span className="library__meta">
                      {c.render_count === 1 ? '1 repaint' : `${c.render_count} repaints`}
                    </span>
                  </span>
                  <Button
                    className="library__small-action"
                    onClick={() => void storage.deleteConsultation(c.consultation_id)}
                  >
                    Delete
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
    </main>
  );
}
