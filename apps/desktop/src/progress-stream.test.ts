import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProgressStreamEvent } from './bridge-types';
import { PROGRESS_STREAM_START_CHANNEL, PROGRESS_STREAM_STOP_CHANNEL } from './channels';
import { registerProgressStreamBridge } from './progress-stream';

// The module under test imports Electron's `ipcMain`; the handler wiring is the unit under test, so
// the whole runtime is faked. This is the shell logic neither seam reaches (docs/conventions.md §6).
const handlers = vi.hoisted(() => ({ start: undefined as unknown, stop: undefined as unknown }));

vi.mock('electron', () => ({
  ipcMain: {
    handle: (channel: string, handler: unknown) => {
      if (channel === PROGRESS_STREAM_START_CHANNEL) handlers.start = handler;
      if (channel === PROGRESS_STREAM_STOP_CHANNEL) handlers.stop = handler;
    },
  },
}));

const STREAM_FAILED_MESSAGE =
  'SpectraPaint could not finish preparing your photo. Please try again.';

const VALID_SESSION_ID = '0123456789abcdef0123456789abcdef';

const SIDECAR = {
  baseUrl: 'http://127.0.0.1:1',
  secret: 'test-secret',
  stop: async () => {},
};

interface SentPayload {
  sessionId: string;
  event: ProgressStreamEvent;
}

class FakeSender {
  readonly sent: SentPayload[] = [];
  readonly destroyed = false;
  send(_channel: string, payload: SentPayload): void {
    this.sent.push(payload);
  }
  isDestroyed(): boolean {
    return this.destroyed;
  }
}

function sent(sender: FakeSender): SentPayload[] {
  return sender.sent;
}

function invoke(
  channel: 'start' | 'stop',
  sender: FakeSender,
  sessionId: unknown,
): Promise<unknown> {
  const handler = channel === 'start' ? handlers.start : handlers.stop;
  return (handler as (event: { sender: FakeSender }, sessionId: unknown) => Promise<unknown>)(
    { sender },
    sessionId,
  );
}

function invokeStart(sender: FakeSender, sessionId: unknown): Promise<unknown> {
  return invoke('start', sender, sessionId);
}

function invokeStop(sender: FakeSender, sessionId: unknown): Promise<unknown> {
  return invoke('stop', sender, sessionId);
}

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

function deferredRead(): { read: () => Promise<unknown>; resolve: (value: unknown) => void } {
  let resolve!: (value: unknown) => void;
  const promise = new Promise<unknown>((r) => (resolve = r));
  return { read: () => promise, resolve };
}

function readerFor(chunks: Uint8Array[]): { getReader: () => { read: () => Promise<unknown> } } {
  const queue = [...chunks];
  return {
    getReader: () => ({
      read: async () => (queue.length > 0 ? { done: false, value: queue.shift() } : { done: true }),
    }),
  };
}

const encode = (text: string): Uint8Array => new TextEncoder().encode(text);

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  // Trust every sender by default; the untrusted case re-registers with a real check.
  registerProgressStreamBridge(
    () => SIDECAR,
    () => true,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('registerProgressStreamBridge', () => {
  it('refuses a session id that fails the pattern with a failed event, never silently', async () => {
    const sender = new FakeSender();

    await invokeStart(sender, '../../etc/passwd');

    expect(sent(sender)).toEqual([
      { sessionId: '../../etc/passwd', event: { phase: 'failed', message: STREAM_FAILED_MESSAGE } },
    ]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses an untrusted sender with a failed event', async () => {
    const sender = new FakeSender();
    registerProgressStreamBridge(
      () => SIDECAR,
      () => false,
    );

    await invokeStart(sender, VALID_SESSION_ID);

    expect(sent(sender)).toEqual([
      { sessionId: VALID_SESSION_ID, event: { phase: 'failed', message: STREAM_FAILED_MESSAGE } },
    ]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses a second stream for an already-active session with a failed event', async () => {
    const first = new FakeSender();
    const second = new FakeSender();
    const pending = deferredRead();
    fetchMock.mockResolvedValue({ ok: true, body: { getReader: () => ({ read: pending.read }) } });

    await invokeStart(first, VALID_SESSION_ID);
    await invokeStart(second, VALID_SESSION_ID);

    expect(sent(second)).toEqual([
      { sessionId: VALID_SESSION_ID, event: { phase: 'failed', message: STREAM_FAILED_MESSAGE } },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await invokeStop(first, VALID_SESSION_ID);
  });

  it('emits a failed event when there is no sidecar to stream from', async () => {
    const sender = new FakeSender();
    fetchMock.mockResolvedValue({
      ok: true,
      body: { getReader: () => ({ read: () => Promise.resolve({ done: true }) }) },
    });
    registerProgressStreamBridge(
      () => null,
      () => true,
    );

    await invokeStart(sender, VALID_SESSION_ID);

    expect(sent(sender)).toEqual([
      { sessionId: VALID_SESSION_ID, event: { phase: 'failed', message: STREAM_FAILED_MESSAGE } },
    ]);
  });

  it('forwards progress events and stops at the terminal done event', async () => {
    const sender = new FakeSender();
    fetchMock.mockResolvedValue({
      ok: true,
      body: readerFor([
        encode('data: {"phase":"progress","message":"Reading your photo…"}\n\n'),
        encode('data: {"phase":"done"}\n\n'),
      ]),
    });

    await invokeStart(sender, VALID_SESSION_ID);
    await flush();

    expect(sent(sender)).toEqual([
      {
        sessionId: VALID_SESSION_ID,
        event: { phase: 'progress', message: 'Reading your photo…' },
      },
      { sessionId: VALID_SESSION_ID, event: { phase: 'done' } },
    ]);
  });

  it('synthesises a failed event when the stream ends without a terminal event', async () => {
    const sender = new FakeSender();
    fetchMock.mockResolvedValue({
      ok: true,
      body: readerFor([encode('data: {"phase":"progress","message":"Reading your photo…"}\n\n')]),
    });

    await invokeStart(sender, VALID_SESSION_ID);
    await flush();

    expect(sent(sender).at(-1)).toEqual({
      sessionId: VALID_SESSION_ID,
      event: { phase: 'failed', message: STREAM_FAILED_MESSAGE },
    });
  });

  it('an aborted stream cannot clear a newer stream registration for the same session', async () => {
    const first = new FakeSender();
    const second = new FakeSender();
    const third = new FakeSender();
    const firstRead = deferredRead();
    const secondRead = deferredRead();
    fetchMock
      .mockResolvedValueOnce({ ok: true, body: { getReader: () => ({ read: firstRead.read }) } })
      .mockResolvedValueOnce({ ok: true, body: { getReader: () => ({ read: secondRead.read }) } });

    await invokeStart(first, VALID_SESSION_ID);
    await invokeStop(first, VALID_SESSION_ID);
    await invokeStart(second, VALID_SESSION_ID);

    firstRead.resolve({ done: true });
    await flush();
    await flush();

    // The aborted stream's finally must not delete the second stream's entry: a third start is
    // still refused as already-active, and no third fetch happens.
    await invokeStart(third, VALID_SESSION_ID);
    expect(sent(third)).toEqual([
      { sessionId: VALID_SESSION_ID, event: { phase: 'failed', message: STREAM_FAILED_MESSAGE } },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    secondRead.resolve({ done: true });
    await flush();
    await flush();

    // Now that the real stream ended, its own finally clears the entry and a new start streams again.
    const fourth = new FakeSender();
    const thirdRead = deferredRead();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      body: { getReader: () => ({ read: thirdRead.read }) },
    });
    await invokeStart(fourth, VALID_SESSION_ID);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    await invokeStop(fourth, VALID_SESSION_ID);
  });
});
