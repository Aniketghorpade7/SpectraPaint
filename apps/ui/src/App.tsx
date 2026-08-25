import { useCallback } from 'react';

import { BootScreen } from './boot/BootScreen';
import { useBoot } from './boot/useBoot';
import { ConsultationSurface } from './consultation/ConsultationSurface';
import { useConsultation } from './consultation/useConsultation';
import { LibraryScreen } from './library/LibraryScreen';
import { useLibrary } from './library/useLibrary';

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

  const startInBundle = useCallback(
    async (bundleId: string) => {
      const sessionId = await consultation.start();
      if (sessionId) {
        // The service files every new Consultation into the default bundle; move it to the
        // Dealer's chosen job before the Consultation surface takes over. Best-effort: a
        // failure leaves it in the default bundle rather than blocking the photo.
        try {
          await window.spectrapaint.request({
            path: `/bundles/${bundleId}/consultations`,
            method: 'POST',
            body: { consultation_id: sessionId },
          });
          void library.refreshBundles();
        } catch (error) {
          console.error('[app] could not file consultation into bundle:', error);
        }
      }
    },
    [consultation, library],
  );

  if (!boot.finished) {
    return <BootScreen boot={boot} />;
  }

  if (consultation.state.phase === 'idle') {
    return (
      <LibraryScreen
        library={library}
        onReopened={({ sessionId, imageDataUrl }) => consultation.adopt(sessionId, imageDataUrl)}
        onNewConsultation={() => void consultation.start()}
        onNewConsultationInBundle={(bundleId) => void startInBundle(bundleId)}
      />
    );
  }

  return <ConsultationSurface consultation={consultation} />;
}
