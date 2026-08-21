import { describe, expect, it } from 'vitest';

import { isPermittedRequest } from './contract-path';

/**
 * The renderer can only reach the service because main refuses to fetch anything else. If this
 * check loosens, that guarantee is gone and nothing else in the app would notice.
 */
describe('what the renderer is allowed to ask for', () => {
  it('permits paths inside the contract', () => {
    expect(isPermittedRequest({ path: '/health' })).toBe(true);
    expect(isPermittedRequest({ path: '/sessions', method: 'POST' })).toBe(true);
    expect(isPermittedRequest({ path: '/sessions/abc-123/planes' })).toBe(true);
    expect(isPermittedRequest({ path: '/sessions/abc-123', method: 'DELETE' })).toBe(true);
    // Issue #11: renaming a Bundle is the one PATCH in the contract.
    expect(isPermittedRequest({ path: '/bundles/bundle_abcdef123456', method: 'PATCH' })).toBe(
      true,
    );
  });

  it('permits the query strings the Catalogue endpoints need', () => {
    expect(isPermittedRequest({ path: '/catalogue/shades?limit=100&offset=200' })).toBe(true);
    expect(isPermittedRequest({ path: '/catalogue/shades?q=morning+linen' })).toBe(true);
    expect(isPermittedRequest({ path: '/catalogue/shades?shade_family=Earth%20Tones' })).toBe(true);
    expect(isPermittedRequest({ path: '/catalogue/shades?q=' })).toBe(true);
  });

  it('permits what a Dealer types, once URLSearchParams has encoded it', () => {
    const typed = ['50% grey', 'café crème', 'a/b', '..', '<script>', "o'brien"];

    for (const q of typed) {
      const path = `/catalogue/shades?${new URLSearchParams({ q }).toString()}`;
      expect(isPermittedRequest({ path }), path).toBe(true);
    }
  });

  it('refuses a query string that was not built by encoding', () => {
    expect(isPermittedRequest({ path: '/catalogue/shades?q=a b' })).toBe(false);
    expect(isPermittedRequest({ path: '/catalogue/shades?q=<script>' })).toBe(false);
    expect(isPermittedRequest({ path: '/catalogue/shades?q=a?b' })).toBe(false);
  });

  it('refuses a fragment, which would hide the tail of the URL from this check', () => {
    expect(isPermittedRequest({ path: '/catalogue/shades#/../secrets' })).toBe(false);
    expect(isPermittedRequest({ path: '/catalogue/shades?q=a#b' })).toBe(false);
  });

  it('still refuses traversal in the path when a query string is present', () => {
    expect(isPermittedRequest({ path: '/catalogue/../secrets?q=x' })).toBe(false);
    expect(isPermittedRequest({ path: '//example.com/catalogue?q=x' })).toBe(false);
  });

  it('refuses anything that names a host', () => {
    expect(isPermittedRequest({ path: 'http://example.com/health' })).toBe(false);
    expect(isPermittedRequest({ path: '//example.com/health' })).toBe(false);
    expect(isPermittedRequest({ path: 'file:///etc/passwd' })).toBe(false);
  });

  it('refuses traversal, in every spelling it can be written', () => {
    expect(isPermittedRequest({ path: '/../secrets' })).toBe(false);
    expect(isPermittedRequest({ path: '/sessions/../../etc/passwd' })).toBe(false);
    expect(isPermittedRequest({ path: '/sessions/%2e%2e/admin' })).toBe(false);
    expect(isPermittedRequest({ path: '\\\\server\\share' })).toBe(false);
  });

  it('refuses a relative path, which would resolve against the base URL', () => {
    expect(isPermittedRequest({ path: 'health' })).toBe(false);
    expect(isPermittedRequest({ path: '' })).toBe(false);
  });

  it('refuses methods outside the contract', () => {
    expect(isPermittedRequest({ path: '/health', method: 'PUT' as 'GET' })).toBe(false);
    expect(isPermittedRequest({ path: '/health', method: 'TRACE' as 'GET' })).toBe(false);
  });

  it('refuses a malformed request rather than trusting the renderer', () => {
    expect(isPermittedRequest(undefined)).toBe(false);
    expect(isPermittedRequest(null)).toBe(false);
    expect(isPermittedRequest({ path: 42 as unknown as string })).toBe(false);
  });
});
