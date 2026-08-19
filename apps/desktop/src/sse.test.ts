import { describe, expect, it } from 'vitest';

import { SseParser } from './sse';

describe('the SSE stream parser', () => {
  it('parses a single progress event', () => {
    const parser = new SseParser();

    expect(parser.push('data: {"phase":"progress","message":"Reading your photo…"}\n\n')).toEqual([
      { phase: 'progress', message: 'Reading your photo…' },
    ]);
  });

  it('parses several events from one chunk, in order', () => {
    const parser = new SseParser();

    const events = parser.push(
      'data: {"phase":"progress","message":"First…"}\n\n' +
        'data: {"phase":"progress","message":"Second…"}\n\n' +
        'data: {"phase":"done"}\n\n',
    );

    expect(events).toEqual([
      { phase: 'progress', message: 'First…' },
      { phase: 'progress', message: 'Second…' },
      { phase: 'done' },
    ]);
  });

  it('holds an event that arrives split across chunks until it is complete', () => {
    const parser = new SseParser();

    expect(parser.push('data: {"phase":"prog')).toEqual([]);
    expect(parser.push('ress","message":"Still ')).toEqual([]);
    expect(parser.push('working…"}\n')).toEqual([]);
    expect(parser.push('\n')).toEqual([{ phase: 'progress', message: 'Still working…' }]);
  });

  it('accepts CRLF line endings, which a server may legally send', () => {
    const parser = new SseParser();

    expect(parser.push('data: {"phase":"done"}\r\n\r\n')).toEqual([{ phase: 'done' }]);
  });

  it('parses a failed event with its message', () => {
    const parser = new SseParser();

    expect(
      parser.push('data: {"phase":"failed","message":"That photo could not be read."}\n\n'),
    ).toEqual([{ phase: 'failed', message: 'That photo could not be read.' }]);
  });

  it('ignores comments and foreign fields', () => {
    const parser = new SseParser();

    const events = parser.push(': keepalive\nid: 7\nretry: 100\ndata: {"phase":"done"}\n\n');

    expect(events).toEqual([{ phase: 'done' }]);
  });

  it('returns nothing for a malformed payload instead of throwing', () => {
    const parser = new SseParser();

    expect(parser.push('data: not-json\n\n')).toEqual([]);
  });

  it('returns nothing for a payload with an unknown phase', () => {
    const parser = new SseParser();

    expect(parser.push('data: {"phase":"exploded"}\n\n')).toEqual([]);
  });
});
