import { ipcMain, type WebContents } from 'electron';

import type { WallPlaneOverlay, WallsResult } from './bridge-types';
import { WALLS_CHANNEL } from './channels';
import { photoDataUrl } from './photo-upload';
import type { Sidecar } from './sidecar';

/**
 * The main-process half of "show the Dealer which walls were found" (ticket #6).
 *
 * Two service calls become one IPC round trip: `GET /sessions/{id}/planes` says what planes exist,
 * and a second request per plane fetches its Alpha Matte as a PNG. The renderer receives plane
 * geometry plus a data URL it can draw, and never learns the secret, the port, or that the matte
 * arrived as an image at all.
 *
 * A fourth bridge for the same reason there was a third (implementation-decisions.md §20): the
 * generic request bridge reads a JSON body, so a PNG reaches it as `body: null`. Rather than teach
 * that bridge about content types, the endpoints that answer with images get a bridge that expects
 * one.
 *
 * The matte is fetched here rather than pointed at from an `<img src>`, because an `<img>` in the
 * renderer would have to carry the secret in a URL — the same reason the progress stream is a
 * fetch in main rather than an `EventSource`.
 *
 * `overlaysFrom` and `serviceRefusal` are exported for `corrections-bridge.ts` (ticket #10): every
 * correction answers with the exact same shape `GET .../planes` does, so fetching each plane's
 * matte and turning a non-`ok` response into a `WallsResult` is the same work in both places, not
 * a coincidence worth re-implementing.
 */

// Session ids are uuid4().hex — exactly 32 lowercase hex digits. Anything else is refused before it
// reaches a path, so the renderer cannot name a route outside the contract.
export const SESSION_ID_PATTERN = /^[0-9a-f]{32}$/;

// Plane ids come from the service, but they are round-tripped through the renderer before being
// used in a path, so they are checked on the way back in.
const PLANE_ID_PATTERN = /^[a-z0-9_]{1,64}$/;

const WALLS_FAILED_MESSAGE =
  'The walls in this photo could not be shown. The photo can still be repainted.';

const SERVICE_UNAVAILABLE_MESSAGE =
  'SpectraPaint could not reach its own service. Please restart the app.';

export interface PlaneDescription {
  plane_id: string;
  coverage: number;
  photo_width: number;
  photo_height: number;
  bounds: { left: number; top: number; right: number; bottom: number } | null;
}

/** The shape every planes-listing and every correction answers with (implementation-decisions.md
 * #40/#42) — `note` and the top-level dimensions exist precisely for the photo that has none. */
export interface PlanesResponseBody {
  planes: PlaneDescription[];
  note: string | null;
  photo_width: number;
  photo_height: number;
}

export function registerWallsBridge(
  getSidecar: () => Sidecar | null,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  ipcMain.handle(WALLS_CHANNEL, async (event, sessionId: unknown): Promise<WallsResult> => {
    if (!isTrustedSender(event.sender)) {
      return refusal('unauthorised');
    }
    if (typeof sessionId !== 'string' || !SESSION_ID_PATTERN.test(sessionId)) {
      return refusal('malformed_request');
    }

    const sidecar = getSidecar();
    if (!sidecar) {
      return refusal('service_unavailable');
    }

    const headers = { Authorization: `Bearer ${sidecar.secret}` };

    try {
      const listed = await fetch(`${sidecar.baseUrl}/sessions/${sessionId}/planes`, { headers });
      if (!listed.ok) {
        return await serviceRefusal(listed);
      }

      const body = (await listed.json()) as PlanesResponseBody;
      return await overlaysFrom(sidecar, sessionId, body);
    } catch (error) {
      // Never dead-end: the UI gets a result it can act on rather than a hanging promise. An
      // overlay that cannot be drawn is a cosmetic loss, and the message says so — the photo is
      // still repaintable, which is the thing the Dealer came for.
      console.error('[walls] the wall planes could not be fetched:', error);
      return refusal('service_unavailable');
    }
  });
}

/**
 * A planes-response body from the service, resolved into a `WallsResult` — one matte fetch per
 * plane, each becoming a data URL the renderer can draw directly.
 *
 * Shared by `registerWallsBridge` and `corrections-bridge.ts`: a correction's response has this
 * exact shape (implementation-decisions.md #40), so both fetch the same way rather than the
 * correction bridge re-implementing this loop beside it.
 */
export async function overlaysFrom(
  sidecar: Sidecar,
  sessionId: string,
  body: PlanesResponseBody,
): Promise<WallsResult> {
  const headers = { Authorization: `Bearer ${sidecar.secret}` };
  const overlays: WallPlaneOverlay[] = [];

  for (const plane of body.planes) {
    if (!PLANE_ID_PATTERN.test(plane.plane_id)) {
      continue;
    }
    const matte = await fetch(
      `${sidecar.baseUrl}/sessions/${sessionId}/planes/${plane.plane_id}/matte`,
      { headers },
    );
    if (!matte.ok) {
      return await serviceRefusal(matte);
    }
    overlays.push({
      planeId: plane.plane_id,
      coverage: plane.coverage,
      photoWidth: plane.photo_width,
      photoHeight: plane.photo_height,
      bounds: plane.bounds,
      matteDataUrl: photoDataUrl(new Uint8Array(await matte.arrayBuffer()), 'image/png'),
    });
  }

  return {
    status: 'ready',
    planes: overlays,
    note: body.note,
    photoWidth: body.photo_width,
    photoHeight: body.photo_height,
  };
}

export async function serviceRefusal(response: Response): Promise<WallsResult> {
  // The service's own message where there is one, because it is written for the Dealer to read
  // (conventions.md §5) and is more specific than anything this layer could invent — "no wall could
  // be found in that photo" being exactly the case worth passing through verbatim.
  try {
    const body = (await response.json()) as { code?: string; message?: string };
    if (typeof body.message === 'string' && body.message.length > 0) {
      return {
        status: 'failed',
        code: typeof body.code === 'string' ? body.code : 'service_error',
        message: body.message,
      };
    }
  } catch {
    // A non-JSON error body is not worth reporting on its own; fall through to the generic message.
  }
  return refusal('service_error');
}

function refusal(code: string): WallsResult {
  return {
    status: 'failed',
    code,
    message: code === 'service_unavailable' ? SERVICE_UNAVAILABLE_MESSAGE : WALLS_FAILED_MESSAGE,
  };
}
