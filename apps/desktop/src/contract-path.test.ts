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
