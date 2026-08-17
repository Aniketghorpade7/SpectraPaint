import { randomBytes } from 'node:crypto';

/**
 * The per-launch secret.
 *
 * Fresh on every launch, so a secret recovered from a previous run — out of a log, a crash dump, a
 * process listing — is worthless. Generated in the main process and given to exactly two parties:
 * the service, through its environment, and the preload script. The renderer never sees it.
 */
export function generateLaunchSecret(): string {
  // 256 bits. The secret is never typed by a human, so there is no reason to make it short.
  return randomBytes(32).toString('base64url');
}
