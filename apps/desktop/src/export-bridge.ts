import { dialog, ipcMain, shell, type WebContents } from 'electron';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import type { ExportResult } from './bridge-types';
import { EXPORT_CHANNEL } from './channels';
import type { Sidecar } from './sidecar';

/**
 * Export at full resolution and hand the JPEG to the OS (issue #12).
 *
 * The renderer never touches bytes or the secret. Main fetches the JPEG
 * from the service (which re-renders at full resolution), writes it to a
 * temporary file, then hands it to the native save dialog / share sheet.
 * The stored PNG archive is never handed out directly — a fresh JPEG is
 * always generated for export.
 */

const SESSION_ID_PATTERN = /^[0-9a-f]{32}$/;
const STUB_WALL_PLANE_ID = 'wall_plane_1';

const EXPORT_FAILED_MESSAGE = 'The export could not be completed. Please try again.';
const SERVICE_UNAVAILABLE_MESSAGE =
  'SpectraPaint could not reach its own service. Please restart the app.';

export function registerExportBridge(
  getSidecar: () => Sidecar | null,
  getWindow: () => Electron.BrowserWindow | null,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  ipcMain.handle(
    EXPORT_CHANNEL,
    async (
      event,
      sessionId: unknown,
      shadeCodeOrAssignments: unknown,
      mode: unknown = 'realistic',
    ): Promise<ExportResult> => {
      if (!isTrustedSender(event.sender)) {
        return { status: 'failed', code: 'unauthorised', message: EXPORT_FAILED_MESSAGE };
      }

      if (typeof sessionId !== 'string' || !SESSION_ID_PATTERN.test(sessionId)) {
        return { status: 'failed', code: 'malformed_request', message: EXPORT_FAILED_MESSAGE };
      }

      let assignments: Record<string, string> | null = null;
      if (typeof shadeCodeOrAssignments === 'string') {
        if (shadeCodeOrAssignments.length === 0) {
          return { status: 'failed', code: 'malformed_request', message: EXPORT_FAILED_MESSAGE };
        }
      } else if (
        shadeCodeOrAssignments !== null &&
        typeof shadeCodeOrAssignments === 'object' &&
        !Array.isArray(shadeCodeOrAssignments)
      ) {
        const entries = Object.entries(shadeCodeOrAssignments as Record<string, unknown>);
        if (
          entries.length === 0 ||
          entries.some(
            ([k, v]) =>
              typeof k !== 'string' ||
              typeof v !== 'string' ||
              k.length === 0 ||
              (v as string).length === 0,
          )
        ) {
          return { status: 'failed', code: 'malformed_request', message: EXPORT_FAILED_MESSAGE };
        }
        assignments = shadeCodeOrAssignments as Record<string, string>;
      } else {
        return { status: 'failed', code: 'malformed_request', message: EXPORT_FAILED_MESSAGE };
      }

      const sidecar = getSidecar();
      if (!sidecar) {
        return {
          status: 'failed',
          code: 'service_unavailable',
          message: SERVICE_UNAVAILABLE_MESSAGE,
        };
      }

      if (assignments === null) {
        const shadeCode = shadeCodeOrAssignments as string;
        try {
          const planesResp = await fetch(`${sidecar.baseUrl}/sessions/${sessionId}/planes`, {
            headers: { Authorization: `Bearer ${sidecar.secret}` },
          });
          if (planesResp.ok) {
            const data = (await planesResp.json()) as { planes: { plane_id: string }[] };
            const ids = data.planes
              .map((p) => p.plane_id)
              .filter((id) => /^[a-z0-9_]{1,64}$/.test(id));
            assignments =
              ids.length > 0
                ? Object.fromEntries(ids.map((id) => [id, shadeCode]))
                : { [STUB_WALL_PLANE_ID]: shadeCode };
          } else {
            assignments = { [STUB_WALL_PLANE_ID]: shadeCode };
          }
        } catch {
          assignments = { [STUB_WALL_PLANE_ID]: shadeCode };
        }
      }

      const renderMode = mode === 'true_colour' ? 'true_colour' : 'realistic';

      let jpegBytes: Uint8Array;
      let filename = 'SpectraPaint-Render.jpg';
      try {
        const resp = await fetch(`${sidecar.baseUrl}/sessions/${sessionId}/exports`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${sidecar.secret}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ assignments, mode: renderMode }),
        });
        if (!resp.ok) {
          const body = (await resp.json().catch(() => null)) as {
            code?: string;
            message?: string;
          } | null;
          return {
            status: 'failed',
            code: body?.code ?? 'export_failed',
            message: body?.message ?? EXPORT_FAILED_MESSAGE,
          };
        }
        // Filename comes from Content-Disposition or the export-specific header.
        const disposition = resp.headers.get('Content-Disposition') ?? '';
        const headerFilename = resp.headers.get('X-SpectraPaint-Export-Filename');
        const match = disposition.match(/filename="([^"]+)"/);
        if (match?.[1]) filename = match[1];
        else if (headerFilename) filename = headerFilename;
        jpegBytes = new Uint8Array(await resp.arrayBuffer());
      } catch (error) {
        console.error('[export] the export request failed:', error);
        return {
          status: 'failed',
          code: 'service_unavailable',
          message: SERVICE_UNAVAILABLE_MESSAGE,
        };
      }

      // Write to a temporary file first so the share sheet has a file to hand out.
      const tempDir = os.tmpdir();
      const tempPath = path.join(tempDir, `spectrapaint-${Date.now()}-${filename}`);
      try {
        await fs.writeFile(tempPath, jpegBytes);
      } catch (error) {
        console.error('[export] could not write temp file:', error);
        return { status: 'failed', code: 'export_failed', message: EXPORT_FAILED_MESSAGE };
      }

      const win = getWindow();
      // Native save dialog — the file is handed to the system share sheet via the dialog's location;
      // WhatsApp, email or print can consume it from there. The dialog is the OS's own, so the Dealer
      // chooses where the file goes and the app never hands out the PNG archive.
      // Whether the temp copy may still be cleaned up: the dialog-throw fallback below returns the
      // temp file itself as the deliverable, so it must survive the cleanup.
      let tempFileIsTheDeliverable = false;
      try {
        const result = win
          ? await dialog.showSaveDialog(win, {
              title: 'Export render',
              defaultPath: path.join(os.homedir(), 'Downloads', filename),
              filters: [{ name: 'JPEG Image', extensions: ['jpg', 'jpeg'] }],
            })
          : { canceled: true, filePath: '' };

        if (result.canceled || !result.filePath) {
          // Walking away is a decision, not a failure — report cancelled. The temp copy is cleaned
          // up below; the next export renders a fresh JPEG, so there is nothing to retry against.
          return { status: 'cancelled' };
        }

        await fs.copyFile(tempPath, result.filePath);
        // Reveal in the OS so the Dealer can share via WhatsApp/email/print — the system share sheet
        // consumes files from the filesystem, not from an in-memory blob.
        shell.showItemInFolder(result.filePath);
        return {
          status: 'ready',
          filePath: result.filePath,
          filename: path.basename(result.filePath),
        };
      } catch (error) {
        console.error('[export] save dialog failed:', error);
        // Never dead-end: the JPEG already exists, so hand back the temp copy itself rather than
        // refusing an export that succeeded. It becomes the deliverable — cleanup must spare it.
        tempFileIsTheDeliverable = true;
        try {
          shell.showItemInFolder(tempPath);
        } catch (revealError) {
          console.error('[export] could not reveal the exported file:', revealError);
        }
        return { status: 'ready', filePath: tempPath, filename };
      } finally {
        // The chosen path now holds the JPEG, so the temp copy can go — unless it *is* the file the
        // Dealer was just shown. Not awaited: the IPC reply must not wait on temp cleanup.
        if (!tempFileIsTheDeliverable) {
          void fs.unlink(tempPath).catch(() => {});
        }
      }
    },
  );
}
