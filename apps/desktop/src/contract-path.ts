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

/**
 * A query string, which the Catalogue endpoints need (`/catalogue/shades?q=...`, issue #5).
 *
 * The set is exactly what `URLSearchParams` emits: unreserved characters, `*`, the `%` of an escape,
 * and the `=`, `&` and `+` that join the pairs. Everything a Dealer can type — spaces, accents, `#`,
 * a slash — arrives percent-encoded and so passes as `%` plus hex. Anything else is a caller
 * building a URL by hand, which is the case this whitelist exists to refuse.
 *
 * `#` is absent deliberately: a fragment would let a caller hide the real tail of the URL from this
 * check while `fetch` still sees it.
 */
const QUERY_STRING = /^[A-Za-z0-9*\-._%=&+]*$/;

const ALLOWED_METHODS = new Set(['GET', 'POST', 'DELETE']);

export function isPermittedRequest(request: ServiceRequest | undefined | null): boolean {
  if (!request || typeof request.path !== 'string') return false;
  if (!ALLOWED_METHODS.has(request.method ?? 'GET')) return false;

  const parts = request.path.split('?');

  // One question mark. A second would mean the first `?` is being read as data by this check and as
  // a separator by something downstream — the disagreement is the bug, whichever way it resolves.
  if (parts.length > 2) return false;

  const path = parts[0] ?? '';
  const query = parts[1];

  // Backslashes, encoded slashes and traversal are all rejected by the pattern, but `..` deserves
  // its own line: it is the one an attacker reaches for first. Only the path is checked for it — a
  // Dealer searching the Catalogue for ".." is asking a question, not climbing a directory tree.
  if (path.includes('..')) return false;
  if (!CONTRACT_PATH.test(path)) return false;

  return query === undefined || QUERY_STRING.test(query);
}
