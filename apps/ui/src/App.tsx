import { BootScreen } from './boot/BootScreen';
import { useBoot } from './boot/useBoot';

/**
 * The app opens on Boot and stays there until the service is ready — which is also what stops
 * every other surface having to handle "the service is not up yet".
 *
 * Bundles is the entry point after boot (ticket #11); until then this is a placeholder.
 */
export function App() {
  const boot = useBoot();

  if (!boot.finished) {
    return <BootScreen boot={boot} />;
  }

  return (
    <main className="boot">
      <h1 className="boot__title">SpectraPaint</h1>
      <p className="progress-message">Ready for a Consultation.</p>
    </main>
  );
}
