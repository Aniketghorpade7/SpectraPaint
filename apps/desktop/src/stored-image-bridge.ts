import { ipcMain, type WebContents } from 'electron';

import type { StoredImageResult } from './bridge-types';
import { STORED_IMAGE_CHANNEL } from './channels';
import { photoDataUrl } from './photo-upload';
import type { Sidecar } from './sidecar';

/**
 * The main-process half of "show what was saved" (issue #11).
 *
 * A fifth bridge for the reason there were four before it (implementation-decisions.md §20): the
 * stored render and the prepared photo answer with `image/png`, which the generic request bridge
 * cannot carry. The renderer names a Consultation and a target — `'photo'` or a render id — and
 * receives a data URL of exactly the bytes on disk; nothing is re-encoded, re-rendered or
 * regenerated in between.
 *
 * The secret stays here, as with every image: an `<img src>` pointed at the service would carry it
 * in a URL.
 */

// Consultation ids are uuid4().hex, render ids are os.urandom(16).hex — both exactly 32 lowercase
// hex digits. Checked here so the renderer cannot name a route outside the contract.
const ID_PATTERN = /^[0-9a-f]{32}$/;

const SERVICE_UNAVAILABLE_MESSAGE =
  'SpectraPaint could not reach its own service. Please restart the app.';

const IMAGE_FAILED_MESSAGE = 'That image could not be shown right now. Please try again.';

export function registerStoredImageBridge(
  getSidecar: () => Sidecar | null,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  ipcMain.handle(
    STORED_IMAGE_CHANNEL,
    async (event, consultationId: unknown, target: unknown): Promise<StoredImageResult> => {
      if (!isTrustedSender(event.sender)) {
        return refusal('unauthorised');
      }
      if (
        typeof consultationId !== 'string' ||
        !ID_PATTERN.test(consultationId) ||
        typeof target !== 'string' ||
        target.length === 0 ||
        (target !== 'photo' && !ID_PATTERN.test(target))
      ) {
        return refusal('malformed_request');
      }

      const sidecar = getSidecar();
      if (!sidecar) {
        return refusal('service_unavailable');
      }

      const suffix = target === 'photo' ? 'photo/png' : `renders/${target}/png`;
      try {
        const response = await fetch(
          `${sidecar.baseUrl}/consultations/${consultationId}/${suffix}`,
          { headers: { Authorization: `Bearer ${sidecar.secret}` } },
        );
        if (!response.ok) {
          const body = (await response.json().catch(() => null)) as {
            code?: string;
            message?: string;
          } | null;
          return {
            status: 'failed',
            code: body?.code ?? 'service_error',
            message: body?.message ?? IMAGE_FAILED_MESSAGE,
          };
        }
        return {
          status: 'ready',
          imageDataUrl: photoDataUrl(new Uint8Array(await response.arrayBuffer()), 'image/png'),
        };
      } catch (error) {
        console.error('[stored-image] the request failed:', error);
        return refusal('service_unavailable');
      }
    },
  );
}

function refusal(code: string): StoredImageResult {
  return {
    status: 'failed',
    code,
    message: code === 'service_unavailable' ? SERVICE_UNAVAILABLE_MESSAGE : IMAGE_FAILED_MESSAGE,
  };
}
