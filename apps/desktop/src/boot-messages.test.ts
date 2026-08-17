import { describe, expect, it } from 'vitest';

import { bootStatusFor, failureMessageFor } from './boot-messages';

const ALL_FAILURE_CODES = [
  'service_missing',
  'service_exited',
  'service_timeout',
  'service_unreachable',
];

describe('what the Dealer is told when a launch fails', () => {
  it('never dead-ends: every failure says something, including ones we did not anticipate', () => {
    for (const code of [...ALL_FAILURE_CODES, 'something_new', undefined]) {
      expect(failureMessageFor(code).length).toBeGreaterThan(0);
    }
  });

  it('names no model or technique', () => {
    for (const code of ALL_FAILURE_CODES) {
      const message = failureMessageFor(code).toLowerCase();
      for (const jargon of ['python', 'onnx', 'sam', 'port', 'http', 'process', 'sidecar']) {
        expect(message).not.toContain(jargon);
      }
    }
  });

  it('tells the Dealer about quarantine, which they would otherwise never guess', () => {
    // SpectraPaint ships unsigned and looks structurally like what antivirus engines catch
    // (docs/design-decisions.md §3), so this is the likeliest failure in a real shop.
    const message = failureMessageFor('service_missing').toLowerCase();

    expect(message).toContain('antivirus');
    expect(message).toContain('quarantine');
  });

  it('carries a message only when there is a failure to explain', () => {
    expect(bootStatusFor('starting')).toEqual({ phase: 'starting' });
    expect(bootStatusFor('ready')).toEqual({ phase: 'ready' });
    expect(bootStatusFor('failed', 'service_missing').message).toBeTruthy();
  });
});
