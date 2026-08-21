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

/**
 * Fallback plane id when the plane list cannot be read. The service has
 * always spoken in assignments keyed by wall_plane_N; after issue #7 the
 * photo may have wall_plane_1..N. The bridge discovers the ids at render
 * time so the Dealer can colour an Accent Wall without the renderer ever
 * holding the secret or the wire shape.
 *
 * The literal is kept as a fallback only — every successful path fetches
 * the photo's own planes and assigns the Shade to each of them. A per-plane
 * assignment map (Accent Wall) is also accepted directly.
 */
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
    async (
      event,
      sessionId: unknown,
      shadeCodeOrAssignments: unknown,
      mode: unknown = 'realistic',
    ): Promise<RenderResult> => {
      if (!isTrustedSender(event.sender)) {
        return refusal('unauthorised');
      }

      if (typeof sessionId !== 'string' || !SESSION_ID_PATTERN.test(sessionId)) {
        return refusal('malformed_request');
      }

      // Two shapes: a Shade Code string to paint every plane, or a full
      // assignments map for an Accent Wall. The generic guard keeps the
      // channel from being used to probe arbitrary paths.
      let assignments: Record<string, string> | null = null;
      if (typeof shadeCodeOrAssignments === 'string') {
        if (shadeCodeOrAssignments.length === 0) return refusal('malformed_request');
      } else if (
        shadeCodeOrAssignments !== null &&
        typeof shadeCodeOrAssignments === 'object' &&
        !Array.isArray(shadeCodeOrAssignments)
      ) {
        const entries = Object.entries(shadeCodeOrAssignments as Record<string, unknown>);
        if (
          entries.length === 0 ||
          entries.some(([k, v]) => typeof k !== 'string' || typeof v !== 'string' || k.length === 0 || (v as string).length === 0)
        ) {
          return refusal('malformed_request');
        }
        assignments = shadeCodeOrAssignments as Record<string, string>;
      } else {
        return refusal('malformed_request');
      }

      const sidecar = getSidecar();
      if (!sidecar) {
        return refusal('service_unavailable');
      }

      // Resolve which planes to paint. A string Shade Code means "paint every
      // plane this photo has" — the bridge discovers the ids so the renderer
      // never holds the secret. A map is used as-is (per-plane Accent Wall).
      if (assignments === null) {
        const shadeCode = shadeCodeOrAssignments as string;
        try {
          const planesResp = await fetch(`${sidecar.baseUrl}/sessions/${sessionId}/planes`, {
            headers: { Authorization: `Bearer ${sidecar.secret}` },
          });
          if (planesResp.ok) {
            const data = (await planesResp.json()) as { planes: { plane_id: string }[] };
            const ids = data.planes.map((p) => p.plane_id).filter((id) => /^[a-z0-9_]{1,64}$/.test(id));
            assignments = ids.length > 0 ? Object.fromEntries(ids.map((id) => [id, shadeCode])) : { [STUB_WALL_PLANE_ID]: shadeCode };
          } else {
            assignments = { [STUB_WALL_PLANE_ID]: shadeCode };
          }
        } catch {
          assignments = { [STUB_WALL_PLANE_ID]: shadeCode };
        }
      }

      const renderMode = mode === 'true_colour' ? 'true_colour' : 'realistic';

      let response: Response;
      try {
        response = await fetch(`${sidecar.baseUrl}/sessions/${sessionId}/renders`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${sidecar.secret}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ assignments, mode: renderMode }),
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
