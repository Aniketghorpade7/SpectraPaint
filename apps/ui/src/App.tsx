import { useCallback, useEffect, useState } from 'react';

import { BootScreen } from './boot/BootScreen';
import { useBoot } from './boot/useBoot';
import { ConsultationSurface } from './consultation/ConsultationSurface';
import { useConsultation } from './consultation/useConsultation';
import { LibraryScreen } from './library/LibraryScreen';
import { useLibrary } from './library/useLibrary';
import { StorageView } from './storage/StorageView';
import { useStorage } from './storage/useStorage';
import './storage/storage.css';

/**
 * The app opens on Boot and stays there until the service is ready — which is also what stops
 * every other surface having to handle "the service is not up yet".
 *
 * After boot the Dealer lands in their Bundles (issue #11): start a new Consultation, or pick up
 * an old one — which reopens the stored renders, never regenerated ones, and skips preparation
 * entirely. A Consultation surface is shown while a photo is on screen; leaving it returns to the
 * Bundles, with everything already saved behind the Dealer.
 */
export function App() {
  const boot = useBoot();
  const consultation = useConsultation();
  const library = useLibrary();
  const [showStorage, setShowStorage] = useState(false);
  const storage = useStorage();
  const [diskLow, setDiskLow] = useState<{ low: boolean; warning: string | null } | null>(null);

  // Global low-disk warning, checked on mount and periodically, from both
  // the service (authoritative) and the shell fallback (works when service is down).
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const probe = await window.spectrapaint.disk();
        if (!cancelled && probe.low) {
          setDiskLow({
            low: true,
            warning:
              'Your disk is getting full. Open Storage to delete old Bundles — otherwise new photos may fail to save.',
          });
          return;
        }
      } catch {
        // fall through to service check
      }
      try {
        const resp = await window.spectrapaint.request({ path: '/storage/disk' });
        if (!cancelled && resp.ok) {
          const body = resp.body as { low: boolean; warning: string | null };
          setDiskLow({ low: !!body.low, warning: body.warning ?? null });
        }
      } catch {
        // no warning rather than a false one
      }
    };
    void check();
    const id = setInterval(() => void check(), 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [boot.finished]);

  const startInBundle = useCallback(
    async (bundleId: string) => {
      const sessionId = await consultation.start();
      if (sessionId) {
        // The service files every new Consultation into the default bundle; move it to the
        // Dealer's chosen job. Use the library's placeConsultation so a non-2xx is surfaced
        // as a message instead of vanishing — the raw request bridge returns { ok: false }
        // without throwing, which the previous try/catch missed.
        await library.placeConsultation(bundleId, sessionId);
      }
    },
    [consultation, library],
  );

  if (!boot.finished) {
    return <BootScreen boot={boot} />;
  }

  const banner =
    diskLow?.low && diskLow.warning ? (
      <div className="disk-banner" role="alert">
        <span>{diskLow.warning}</span>
        <button
          type="button"
          className="button disk-banner__action"
          onClick={() => setShowStorage(true)}
        >
          Open Storage
        </button>
        <button type="button" className="button" onClick={() => setDiskLow(null)}>
          Dismiss
        </button>
      </div>
    ) : null;

  if (consultation.state.phase === 'idle') {
    if (showStorage) {
      return (
        <>
          {banner}
          <StorageView
            storage={storage}
            onBack={() => {
              setShowStorage(false);
              void library.refreshBundles();
            }}
            onDeletedBundle={() => void library.refreshBundles()}
          />
        </>
      );
    }
    return (
      <>
        {banner}
        <LibraryScreen
          library={library}
          onReopened={({ sessionId, imageDataUrl }) => consultation.adopt(sessionId, imageDataUrl)}
          onNewConsultation={() => void consultation.start()}
          onNewConsultationInBundle={(bundleId) => void startInBundle(bundleId)}
          onOpenStorage={() => setShowStorage(true)}
        />
      </>
    );
  }

  return (
    <>
      {banner}
      <ConsultationSurface consultation={consultation} />
    </>
  );
}
