import { ipcMain, type WebContents } from 'electron';

import type { CorrectionTool, TapPoint, WallsResult } from './bridge-types';
import { CORRECTIONS_CHANNEL } from './channels';
import type { Sidecar } from './sidecar';
import {
  type PlanesResponseBody,
  SESSION_ID_PATTERN,
  overlaysFrom,
  serviceRefusal,
} from './walls-bridge';

/**
 * The main-process half of "correct the detected walls by tapping" (ticket #10).
 *
 * One channel for all three tools — Add, Split, Merge — because to the renderer this is one
 * action with a tool and a point, the same way `render-bridge.ts` takes a Shade Code or an
 * assignments map on one channel rather than two. `tool` picks the service route; the point never
 * changes shape. Every response is resolved through `walls-bridge.ts`'s `overlaysFrom`, because a
 * correction's answer is exactly the same shape `GET .../planes` already is
 * (implementation-decisions.md #40) — fetching each plane's matte is the same work either way.
 */

const ROUTE_FOR: Record<CorrectionTool, string> = {
  add: 'planes',
  'add-ceiling': 'planes/ceiling',
  split: 'planes/split',
  merge: 'planes/merge',
};

const CORRECTION_FAILED_MESSAGE = 'That could not be done. The walls stay as they were.';

const SERVICE_UNAVAILABLE_MESSAGE =
  'SpectraPaint could not reach its own service. Please restart the app.';

export function registerCorrectionsBridge(
  getSidecar: () => Sidecar | null,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  ipcMain.handle(
    CORRECTIONS_CHANNEL,
    async (event, sessionId: unknown, tool: unknown, point: unknown): Promise<WallsResult> => {
      if (!isTrustedSender(event.sender)) {
        return refusal('unauthorised');
      }
      if (typeof sessionId !== 'string' || !SESSION_ID_PATTERN.test(sessionId)) {
        return refusal('malformed_request');
      }
      if (typeof tool !== 'string' || !(tool in ROUTE_FOR)) {
        return refusal('malformed_request');
      }
      if (!isTapPoint(point)) {
        return refusal('malformed_request');
      }

      const sidecar = getSidecar();
      if (!sidecar) {
        return refusal('service_unavailable');
      }

      try {
        const response = await fetch(
          `${sidecar.baseUrl}/sessions/${sessionId}/${ROUTE_FOR[tool as CorrectionTool]}`,
          {
            method: 'POST',
            headers: {
              Authorization: `Bearer ${sidecar.secret}`,
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(point),
          },
        );
        if (!response.ok) {
          // The service's own message names the right tool instead — "already part of a wall,
          // try Split" — which is exactly why this is passed through rather than replaced with
          // the generic one below (conventions.md §5).
          return await serviceRefusal(response);
        }

        const body = (await response.json()) as PlanesResponseBody;
        return await overlaysFrom(sidecar, sessionId, body);
      } catch (error) {
        // Never dead-end: the existing walls are untouched by a failed request, so this is a
        // cosmetic loss the Dealer can retry, not a reason to lose what was already found.
        console.error('[corrections] the correction could not be made:', error);
        return refusal('service_unavailable');
      }
    },
  );
}

function isTapPoint(point: unknown): point is TapPoint {
  return (
    typeof point === 'object' &&
    point !== null &&
    typeof (point as TapPoint).x === 'number' &&
    typeof (point as TapPoint).y === 'number' &&
    Number.isInteger((point as TapPoint).x) &&
    Number.isInteger((point as TapPoint).y) &&
    (point as TapPoint).x >= 0 &&
    (point as TapPoint).y >= 0
  );
}

function refusal(code: string): WallsResult {
  return {
    status: 'failed',
    code,
    message:
      code === 'service_unavailable' ? SERVICE_UNAVAILABLE_MESSAGE : CORRECTION_FAILED_MESSAGE,
  };
}
