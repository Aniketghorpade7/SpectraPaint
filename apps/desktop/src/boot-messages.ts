import type { BootPhase, BootStatus } from './bridge-types';

/**
 * What the Dealer is told when a launch fails.
 *
 * Written in main rather than the renderer because main is what knows *why* it failed. Plain
 * language, naming no model or technique, and every one of them ends with something the Dealer can
 * actually do — docs/conventions.md §5: never dead-end.
 */

/**
 * The quarantine wording matters. SpectraPaint ships unsigned, and antivirus engines treat a
 * PyInstaller-bundled Python as suspicious in itself, so a component can be removed rather than
 * merely warned about (docs/design-decisions.md §3). A Dealer would never guess that their
 * antivirus took a piece of the app, or that it can be restored.
 */
const FAILURE_MESSAGES: Record<string, string> = {
  service_missing:
    'Part of SpectraPaint is missing. Your antivirus may have removed it — check its quarantine ' +
    'and restore SpectraPaint, then start the app again.',
  service_exited: 'SpectraPaint could not start its own components.',
  service_timeout:
    'SpectraPaint is taking longer than expected to start. If this keeps happening, restarting ' +
    'the computer usually clears it.',
  service_unreachable: 'SpectraPaint could not start its own components.',
};

const FALLBACK_FAILURE = 'SpectraPaint could not finish starting.';

export function failureMessageFor(code: string | undefined): string {
  return (code && FAILURE_MESSAGES[code]) || FALLBACK_FAILURE;
}

export function bootStatusFor(phase: BootPhase, failureCode?: string): BootStatus {
  return phase === 'failed' ? { phase, message: failureMessageFor(failureCode) } : { phase };
}
