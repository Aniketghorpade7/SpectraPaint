import { ipcMain, type WebContents } from 'electron';

import type { ProgressStreamEvent } from './bridge-types';
import {
  PROGRESS_EVENT_CHANNEL,
  PROGRESS_STREAM_START_CHANNEL,
  PROGRESS_STREAM_STOP_CHANNEL,
} from './channels';
import { SseParser } from './sse';
import type { Sidecar } from './sidecar';

/**
 * The main-process half of a session's preparation stream.
 *
 * The renderer must not hold the secret, and the browser's `EventSource` cannot set headers — so the
 * stream is opened here, in main, with `fetch` and the secret in an `Authorization` header. The
 * query string is never used, so the secret cannot leak into a log line (docs/specs/v1-spectrapaint
 * .md, "Electron shell").
 *
 * This is a second bridge alongside the generic request one because the generic one reads a JSON
 * body; a stream must be read incrementally and forwarded frame by frame.
 */

// Session ids are uuid4().hex — exactly 32 lowercase hex digits. Anything else is refused before it
// reaches a path, so the renderer cannot name a route outside the contract.
const SESSION_ID_PATTERN = /^[0-9a-f]{32}$/;

const STREAM_FAILED_MESSAGE =
  'SpectraPaint could not finish preparing your photo. Please try again.';

interface ActiveStream {
  controller: AbortController;
  sender: WebContents;
}

export function registerProgressStreamBridge(
  getSidecar: () => Sidecar | null,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  const active = new Map<string, ActiveStream>();

  ipcMain.handle(PROGRESS_STREAM_START_CHANNEL, (event, sessionId: unknown) => {
    if (!isTrustedSender(event.sender)) return;
    if (typeof sessionId !== 'string' || !SESSION_ID_PATTERN.test(sessionId)) return;
    // Idempotent: one stream per session, whichever window asked first.
    if (active.has(sessionId)) return;

    const sidecar = getSidecar();
    if (!sidecar) {
      send(event.sender, sessionId, { phase: 'failed', message: STREAM_FAILED_MESSAGE });
      return;
    }

    const controller = new AbortController();
    active.set(sessionId, { controller, sender: event.sender });
    void stream(active, sidecar, sessionId, controller, event.sender);
  });

  ipcMain.handle(PROGRESS_STREAM_STOP_CHANNEL, (event, sessionId: unknown) => {
    if (!isTrustedSender(event.sender)) return;
    if (typeof sessionId !== 'string' || !SESSION_ID_PATTERN.test(sessionId)) return;
    const stream = active.get(sessionId);
    if (stream && stream.sender === event.sender) {
      stream.controller.abort();
      active.delete(sessionId);
    }
  });
}

async function stream(
  active: Map<string, ActiveStream>,
  sidecar: Sidecar,
  sessionId: string,
  controller: AbortController,
  sender: WebContents,
): Promise<void> {
  try {
    const response = await fetch(`${sidecar.baseUrl}/sessions/${sessionId}/events`, {
      headers: { Authorization: `Bearer ${sidecar.secret}` },
      signal: controller.signal,
    });

    if (!response.ok || !response.body) {
      send(sender, sessionId, { phase: 'failed', message: STREAM_FAILED_MESSAGE });
      return;
    }

    const parser = new SseParser();
    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      for (const event of parser.push(decoder.decode(value, { stream: true }))) {
        send(sender, sessionId, event);
        if (event.phase === 'done' || event.phase === 'failed') {
          controller.abort();
          return;
        }
      }
    }

    // The stream ended without a terminal event — connection dropped, service died mid-preparation.
    // The Dealer must not sit on an endless "working…" (docs/conventions.md §5: never dead-end).
    send(sender, sessionId, { phase: 'failed', message: STREAM_FAILED_MESSAGE });
  } catch (error) {
    if (controller.signal.aborted) return; // Stopped deliberately by the UI.
    console.error(`[progress] stream for session ${sessionId} failed:`, error);
    send(sender, sessionId, { phase: 'failed', message: STREAM_FAILED_MESSAGE });
  } finally {
    active.delete(sessionId);
  }
}

function send(sender: WebContents, sessionId: string, event: ProgressStreamEvent): void {
  if (sender.isDestroyed()) return;
  sender.send(PROGRESS_EVENT_CHANNEL, { sessionId, event });
}
