import { ipcMain, type WebContents } from 'electron';

import { STORAGE_CHANNEL } from './channels';
import type { Sidecar } from './sidecar';

/**
 * Storage view bridge (issue #13).
 *
 * Proxies GET /storage and DELETE /consultations/{id} / DELETE /bundles/{id}
 * through main so the secret never leaves the main process — same rule as
 * every JSON bridge in this app. The renderer asks for storage; main asks
 * the service.
 */
export function registerStorageBridge(
  getSidecar: () => Sidecar | null,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  ipcMain.handle(
    STORAGE_CHANNEL,
    async (event, payload: { path: string; method?: string; body?: unknown }) => {
      if (!isTrustedSender(event.sender)) {
        return { status: 403, ok: false, body: { code: 'unauthorised', message: 'Unauthorised.' } };
      }
      const sidecar = getSidecar();
      if (!sidecar) {
        return {
          status: 503,
          ok: false,
          body: {
            code: 'service_unavailable',
            message: 'SpectraPaint could not reach its own service. Please restart the app.',
          },
        };
      }
      const method = payload.method ?? 'GET';
      const headers: Record<string, string> = { Authorization: `Bearer ${sidecar.secret}` };
      if (payload.body !== undefined) headers['Content-Type'] = 'application/json';
      const response = await fetch(`${sidecar.baseUrl}${payload.path}`, {
        method,
        headers,
        body: payload.body === undefined ? undefined : JSON.stringify(payload.body),
      });
      return {
        status: response.status,
        ok: response.ok,
        body: await response.json().catch(() => null),
      };
    },
  );
}
