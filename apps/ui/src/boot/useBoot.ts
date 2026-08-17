import { useEffect, useState } from 'react';
import type { BootStatus } from '../../../desktop/src/bridge-types';

/**
 * Minimum time the boot screen stays up.
 *
 * "At least 2 seconds, and however long preparation genuinely needs" (docs/design-decisions.md
 * §13). The floor exists because a screen that flashes past reads as a glitch, and because a
 * launch that is sometimes instant and sometimes four seconds reads as broken.
 */
export const MINIMUM_BOOT_MILLISECONDS = 2_000;

/**
 * The floor and the readiness check are combined, not sequential: preparation and the two seconds
 * run concurrently, so a launch that genuinely needs four seconds takes four, not six.
 */
export function isBootFinished(status: BootStatus, minimumElapsed: boolean): boolean {
  return status.phase === 'ready' && minimumElapsed;
}

export interface Boot {
  status: BootStatus;
  /** True only once the service is ready *and* the minimum has elapsed. */
  finished: boolean;
  retry: () => void;
}

export function useBoot(): Boot {
  const [status, setStatus] = useState<BootStatus>({ phase: 'starting' });
  const [minimumElapsed, setMinimumElapsed] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setMinimumElapsed(true), MINIMUM_BOOT_MILLISECONDS);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    // Read first, then subscribe: the service can reach 'ready' before this screen has loaded, and
    // a purely push-based boot screen would then wait forever for an event already sent.
    let listening = true;
    void window.spectrapaint.bootStatus().then((current) => {
      if (listening) setStatus(current);
    });

    const unsubscribe = window.spectrapaint.onBootStatus(setStatus);
    return () => {
      listening = false;
      unsubscribe();
    };
  }, []);

  return {
    status,
    finished: isBootFinished(status, minimumElapsed),
    retry: () => {
      setStatus({ phase: 'starting' });
      void window.spectrapaint.retryBoot();
    },
  };
}
