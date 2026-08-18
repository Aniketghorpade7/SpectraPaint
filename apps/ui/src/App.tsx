import { BootScreen } from './boot/BootScreen';
import { useBoot } from './boot/useBoot';
import { ConsultationSurface } from './consultation/ConsultationSurface';
import { useConsultation } from './consultation/useConsultation';

/**
 * The app opens on Boot and stays there until the service is ready — which is also what stops
 * every other surface having to handle "the service is not up yet".
 *
 * After boot the Dealer starts a Consultation: pick a Room Photo, see it on screen (issue #2).
 * Bundles becomes the entry point later (ticket #11).
 */
export function App() {
  const boot = useBoot();
  const consultation = useConsultation();

  if (!boot.finished) {
    return <BootScreen boot={boot} />;
  }

  return <ConsultationSurface consultation={consultation} />;
}
