import type { ServiceRequest } from './bridge-types';

/**
 * What the renderer is allowed to ask for.
 *
 * Routing requests through the main process is what stops the renderer reaching arbitrary hosts.
 * A lax check here would hand that capability straight back, so this is deliberately a whitelist
 * of shapes rather than a blacklist of known-bad ones.
 *
 * A path inside the contract, and nothing else: no scheme, no authority, and no protocol-relative
 * `//elsewhere.example` — which is why the pattern rejects a second leading slash.
 */
const CONTRACT_PATH = /^\/(?!\/)[A-Za-z0-9\-._~/]*$/;

const ALLOWED_METHODS = new Set(['GET', 'POST', 'DELETE']);

export function isPermittedRequest(request: ServiceRequest | undefined | null): boolean {
  if (!request || typeof request.path !== 'string') return false;
  // Backslashes, encoded slashes and traversal are all rejected by the pattern, but `..` deserves
  // its own line: it is the one an attacker reaches for first.
  if (request.path.includes('..')) return false;
  return CONTRACT_PATH.test(request.path) && ALLOWED_METHODS.has(request.method ?? 'GET');
}
