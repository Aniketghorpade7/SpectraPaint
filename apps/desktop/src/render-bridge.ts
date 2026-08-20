import { ipcMain, type WebContents } from 'electron';

import type { RenderResult } from './bridge-types';
import { RENDER_CHANNEL } from './channels';
import { photoDataUrl } from './photo-upload';
import type { Sidecar } from './sidecar';

/**
 * The main-process half of "repaint the Wall Plane".
 *
 * The render contract returns `image/png`, which the generic request bridge cannot carry — it reads
 * a JSON body, so a PNG arrives as `body: null`. This is a third bridge, on the same model as the
 * progress stream (implementation-decisions.md #13): the secret stays in main, the renderer asks for
 * a Shade Code and receives a data URL, and never touches the wire shape, a file or a socket.
 *
 * The stub Wall Plane's id lives here, not in the renderer: the UI speaks in Shade Codes, and the
 * wire shape (`assignments` keyed by Wall Plane id) is this package's job. The segmentation tickets
 * widen the set of plane ids here, in the one place that talks to the service.
 */

// Session ids are uuid4().hex — exactly 32 lowercase hex digits. Anything else is refused before it
// reaches a path, so the renderer cannot name a route outside the contract.
const SESSION_ID_PATTERN = /^[0-9a-f]{32}$/;

/** The stub Wall Plane every render colours until the segmentation tickets produce real planes. */
const STUB_WALL_PLANE_ID = 'wall_plane_1';

const RENDER_FAILED_MESSAGE = 'The wall could not be repainted. Please try another Shade.';

const SERVICE_UNAVAILABLE_MESSAGE =
  'SpectraPaint could not reach its own service. Please restart the app.';

export function registerRenderBridge(
  getSidecar: () => Sidecar | null,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  ipcMain.handle(
    RENDER_CHANNEL,
    async (event, sessionId: unknown, shadeCode: unknown): Promise<RenderResult> => {
      if (!isTrustedSender(event.sender)) {
        return refusal('unauthorised');
      }

      if (
        typeof sessionId !== 'string' ||
        !SESSION_ID_PATTERN.test(sessionId) ||
        typeof shadeCode !== 'string' ||
        shadeCode.length === 0
      ) {
        return refusal('malformed_request');
      }

      const sidecar = getSidecar();
      if (!sidecar) {
        return refusal('service_unavailable');
      }

      let response: Response;
      try {
        response = await fetch(`${sidecar.baseUrl}/sessions/${sessionId}/renders`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${sidecar.secret}`,
            'Content-Type': 'application/json',
          },
          // The mode is the contract's default (realistic) for now; the two-modes toggle is ticket
          // #8 and will add `mode` here, in this one place.
          body: JSON.stringify({ assignments: { [STUB_WALL_PLANE_ID]: shadeCode } }),
        });
      } catch (error) {
        // Never dead-end: the UI gets a result it can act on rather than a hanging promise.
        console.error('[render] the repaint request failed:', error);
        return refusal('service_unavailable');
      }

      if (response.ok) {
        return {
          status: 'ready',
          imageDataUrl: photoDataUrl(new Uint8Array(await response.arrayBuffer()), 'image/png'),
        };
      }

      // The service's error body is the message the Dealer should see as-is — an unknown Shade Code
      // has a specific, plain-language answer that an invented one would replace.
      const body = (await response.json().catch(() => null)) as {
        code?: string;
        message?: string;
      } | null;
      return {
        status: 'failed',
        code: body?.code ?? 'render_failed',
        message: body?.message ?? RENDER_FAILED_MESSAGE,
      };
    },
  );
}

function refusal(code: string): RenderResult {
  return {
    status: 'failed',
    code,
    message: code === 'service_unavailable' ? SERVICE_UNAVAILABLE_MESSAGE : RENDER_FAILED_MESSAGE,
  };
}
