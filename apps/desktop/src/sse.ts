import type { ProgressStreamEvent } from './bridge-types';

/**
 * A minimal incremental parser for the service's server-sent events.
 *
 * Only the shape the service actually sends: data-only frames whose payload is the JSON body
 * `{ "phase": "progress"|"done"|"failed", "message"?: string }`. Comments and other SSE fields are
 * ignored. Chunks arrive split at arbitrary byte boundaries, so the parser keeps the tail of a
 * partially-received event between calls.
 *
 * Kept free of Electron and fetch imports so the parsing logic is a pure function, cheap to test —
 * see docs/design-decisions.md §9d.
 */
export class SseParser {
  private buffer = '';

  push(chunk: string): ProgressStreamEvent[] {
    // Normalise CRLF line endings so events are split on `\n\n` regardless of what the server sent.
    this.buffer += chunk.replace(/\r\n/g, '\n');

    const complete = this.buffer.split('\n\n');
    this.buffer = complete.pop() ?? '';

    const events: ProgressStreamEvent[] = [];
    for (const block of complete) {
      const event = parseBlock(block);
      if (event) events.push(event);
    }
    return events;
  }
}

function parseBlock(block: string): ProgressStreamEvent | null {
  const dataLines: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith(':')) continue; // SSE comment; not ours.
    if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).replace(/^ /, ''));
    }
    // Other fields (`event:`, `id:`, `retry:`) are not part of our contract — ignored.
  }

  if (dataLines.length === 0) return null;

  try {
    const payload = JSON.parse(dataLines.join('\n')) as {
      phase?: unknown;
      message?: unknown;
    };
    if (payload.phase !== 'progress' && payload.phase !== 'done' && payload.phase !== 'failed') {
      return null;
    }
    return {
      phase: payload.phase,
      ...(typeof payload.message === 'string' ? { message: payload.message } : {}),
    };
  } catch {
    // A malformed frame is not ours to trust; the caller treats a broken stream as a failure.
    return null;
  }
}
