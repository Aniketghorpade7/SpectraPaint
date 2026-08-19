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

/** The one refusal shape every dead-end branch sends, so the caller's UI can never wait forever. */
const FAILED_EVENT: ProgressStreamEvent = { phase: 'failed', message: STREAM_FAILED_MESSAGE };

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
    if (typeof sessionId === 'string') {
      // Refuse — never silently. A silent return leaves the caller's UI mid-"Loading your
      // photo…" with no terminal event to end it (docs/conventions.md §5). The refusal is keyed by
      // the sessionId the caller passed, so its own listener matches it.
      if (
        !isTrustedSender(event.sender) ||
        !SESSION_ID_PATTERN.test(sessionId) ||
        active.has(sessionId)
      ) {
        send(event.sender, sessionId, FAILED_EVENT);
        return;
      }
    } else {
      return;
    }

    const sidecar = getSidecar();
    if (!sidecar) {
      send(event.sender, sessionId, FAILED_EVENT);
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
      send(sender, sessionId, FAILED_EVENT);
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
    send(sender, sessionId, FAILED_EVENT);
  } catch (error) {
    if (controller.signal.aborted) return; // Stopped deliberately by the UI.
    console.error(`[progress] stream for session ${sessionId} failed:`, error);
    send(sender, sessionId, FAILED_EVENT);
  } finally {
    // Only clear the entry if it is still this stream's. A stop-then-start on the same session
    // replaces the registration; this stream's finally must not delete the newer stream's, or a
    // third start would open a second concurrent reader.
    if (active.get(sessionId)?.controller === controller) active.delete(sessionId);
  }
}

function send(sender: WebContents, sessionId: string, event: ProgressStreamEvent): void {
  if (sender.isDestroyed()) return;
  sender.send(PROGRESS_EVENT_CHANNEL, { sessionId, event });
}
