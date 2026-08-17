import { ErrorState } from '../components/ErrorState';
import { ProgressMessage } from '../components/ProgressMessage';
import type { Boot } from './useBoot';
import './boot.css';

/**
 * What the Dealer sees while SpectraPaint prepares itself.
 *
 * Plain language, and naming no model or technique: "Getting things ready", never "warming ONNX
 * sessions" (docs/conventions.md §5).
 */
const PROGRESS: Record<string, string> = {
  starting: 'Getting SpectraPaint ready…',
  restarting: 'Just a moment — reconnecting…',
  ready: 'Ready.',
  failed: '',
};

export function BootScreen({ boot }: { boot: Boot }) {
  const { status, retry } = boot;

  return (
    <main className="boot">
      <h1 className="boot__title">SpectraPaint</h1>

      {status.phase === 'failed' ? (
        <ErrorState
          message={status.message ?? 'SpectraPaint could not finish starting.'}
          actionLabel="Try again"
          onAction={retry}
        />
      ) : (
        <ProgressMessage>{PROGRESS[status.phase] ?? PROGRESS.starting}</ProgressMessage>
      )}
    </main>
  );
}
