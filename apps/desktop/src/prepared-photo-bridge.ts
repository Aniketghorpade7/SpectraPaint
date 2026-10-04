import { ipcMain, type WebContents } from 'electron';

import type { StoredImageResult } from './bridge-types';
import { PREPARED_PHOTO_CHANNEL } from './channels';
import { photoDataUrl } from './photo-upload';
import type { Sidecar } from './sidecar';

/**
 * The main-process half of "show what was actually prepared" (issue #49).
 *
 * A live session's prepared photo answers `GET /sessions/{id}/photo/png` with `image/png`, which
 * the generic request bridge cannot carry — it reads a JSON body. This is the stored-image bridge's
 * pattern pointed at a session instead of a Consultation (implementation-decisions.md #20): the
 * secret stays in main, the renderer names the session and receives a data URL of exactly the
 * bytes the service holds — the pixels every matte, render and correction tap is built on.
 *
 * The renderer asks for this once preparation reaches `done`, so what the Dealer judges from then
 * on is the prepared photo rather than the raw upload — which an oriented phone photo renders
 * differently (Chromium honours the EXIF tag; the prepared pixels already carry it).
 */

// Session ids are uuid4().hex — exactly 32 lowercase hex digits. Checked here so the renderer
// cannot name a route outside the contract.
const SESSION_ID_PATTERN = /^[0-9a-f]{32}$/;

const SERVICE_UNAVAILABLE_MESSAGE =
  'SpectraPaint could not reach its own service. Please restart the app.';

const PHOTO_FAILED_MESSAGE = 'That photo could not be shown right now. Please try again.';

export function registerPreparedPhotoBridge(
  getSidecar: () => Sidecar | null,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  ipcMain.handle(
    PREPARED_PHOTO_CHANNEL,
    async (event, sessionId: unknown): Promise<StoredImageResult> => {
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

      try {
        const response = await fetch(`${sidecar.baseUrl}/sessions/${sessionId}/photo/png`, {
          headers: { Authorization: `Bearer ${sidecar.secret}` },
        });
        if (!response.ok) {
          const body = (await response.json().catch(() => null)) as {
            code?: string;
            message?: string;
          } | null;
          return {
            status: 'failed',
            code: body?.code ?? 'service_error',
            message: body?.message ?? PHOTO_FAILED_MESSAGE,
          };
        }
        return {
          status: 'ready',
          imageDataUrl: photoDataUrl(new Uint8Array(await response.arrayBuffer()), 'image/png'),
        };
      } catch (error) {
        console.error('[prepared-photo] the request failed:', error);
        return refusal('service_unavailable');
      }
    },
  );
}

function refusal(code: string): StoredImageResult {
  return {
    status: 'failed',
    code,
    message: code === 'service_unavailable' ? SERVICE_UNAVAILABLE_MESSAGE : PHOTO_FAILED_MESSAGE,
  };
}
