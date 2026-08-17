import { ipcMain, type WebContents } from 'electron';

import type { ServiceRequest, ServiceResponse } from './bridge-types';
import { SERVICE_REQUEST_CHANNEL } from './channels';
import { isPermittedRequest } from './contract-path';
import type { Sidecar } from './sidecar';

/**
 * The main-process half of the renderer's HTTP client.
 *
 * The renderer holds neither the secret nor the base URL. It names a path within the contract and
 * the main process performs the call — which is also what makes a service restart invisible: the
 * port changes here, not in code the renderer captured at startup.
 */

export function registerServiceBridge(
  getSidecar: () => Sidecar | null,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  ipcMain.handle(
    SERVICE_REQUEST_CHANNEL,
    async (event, request: ServiceRequest): Promise<ServiceResponse> => {
      if (!isTrustedSender(event.sender)) {
        return refusal(403, 'unauthorised');
      }

      if (!isPermittedRequest(request)) {
        return refusal(400, 'malformed_request');
      }

      const sidecar = getSidecar();
      if (!sidecar) {
        // Never dead-end: the UI gets a code it can act on rather than a hanging promise.
        return refusal(503, 'service_unavailable');
      }

      const method = request.method ?? 'GET';
      const response = await fetch(`${sidecar.baseUrl}${request.path}`, {
        method,
        headers: {
          Authorization: `Bearer ${sidecar.secret}`,
          ...(request.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        body: request.body === undefined ? undefined : JSON.stringify(request.body),
      });

      return {
        status: response.status,
        ok: response.ok,
        body: await response.json().catch(() => null),
      };
    },
  );
}

function refusal(status: number, code: string): ServiceResponse {
  return {
    status,
    ok: false,
    body: {
      code,
      message: 'SpectraPaint could not reach its own service. Please restart the app.',
    },
  };
}
