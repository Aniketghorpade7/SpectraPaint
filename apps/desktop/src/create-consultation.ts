import { dialog, ipcMain, type BrowserWindow, type WebContents } from 'electron';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

import type { CreateConsultationResult } from './bridge-types';
import { CREATE_CONSULTATION_CHANNEL } from './channels';
import { PHOTO_EXTENSIONS, photoDataUrl, photoMimeFor } from './photo-upload';
import type { Sidecar } from './sidecar';

/**
 * The main-process half of "start a new Consultation".
 *
 * Everything the renderer must not touch happens here: the native dialog, the file read, the
 * secret, the upload. The renderer gets back either "cancelled", or the session id plus the photo
 * as a data URL to display. A photo enters the system only through POST /sessions — there is no
 * path here that sends an image anywhere else.
 */

const DIALOG_TITLE = 'Choose a Room Photo';

const UNAVAILABLE_MESSAGE = 'SpectraPaint could not reach its own service. Please restart the app.';

export function registerCreateConsultationBridge(
  getSidecar: () => Sidecar | null,
  getWindow: () => BrowserWindow | null,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  ipcMain.handle(CREATE_CONSULTATION_CHANNEL, async (event): Promise<CreateConsultationResult> => {
    if (!isTrustedSender(event.sender)) {
      return {
        status: 'failed',
        code: 'unauthorised',
        message: 'SpectraPaint could not reach its own service. Please restart the app.',
      };
    }
    return createConsultation(getSidecar, getWindow);
  });
}

export async function createConsultation(
  getSidecar: () => Sidecar | null,
  getWindow: () => BrowserWindow | null,
): Promise<CreateConsultationResult> {
  const picked = await openPhotoDialog(getWindow);
  if (picked.status === 'cancelled') {
    return { status: 'cancelled' };
  }

  const filePath = picked.filePath;
  const bytes = await readPhoto(filePath);
  if (!bytes) {
    return {
      status: 'failed',
      code: 'file_unreadable',
      message: 'That photo could not be read from the disk. Please choose another file.',
    };
  }

  const sidecar = getSidecar();
  if (!sidecar) {
    return { status: 'failed', code: 'service_unavailable', message: UNAVAILABLE_MESSAGE };
  }

  const sessionId = await uploadPhoto(sidecar, filePath, bytes);
  if (!sessionId.ok) {
    return sessionId.result;
  }

  const mime = photoMimeFor(path.extname(filePath).slice(1));
  return {
    status: 'ready',
    sessionId: sessionId.id,
    imageDataUrl: photoDataUrl(bytes, mime),
  };
}

async function openPhotoDialog(
  getWindow: () => BrowserWindow | null,
): Promise<{ status: 'cancelled' } | { status: 'picked'; filePath: string }> {
  const parent = getWindow();
  const options: Electron.OpenDialogOptions = {
    title: DIALOG_TITLE,
    properties: ['openFile'],
    filters: [{ name: 'Photos', extensions: [...PHOTO_EXTENSIONS] }],
  };

  const result = parent
    ? await dialog.showOpenDialog(parent, options)
    : await dialog.showOpenDialog(options);

  const filePath = result.filePaths[0];
  if (result.canceled || !filePath) {
    return { status: 'cancelled' };
  }
  return { status: 'picked', filePath };
}

async function readPhoto(filePath: string): Promise<Buffer | null> {
  try {
    return await readFile(filePath);
  } catch (error) {
    console.error('[consultation] could not read the chosen photo:', error);
    return null;
  }
}

async function uploadPhoto(
  sidecar: Sidecar,
  filePath: string,
  bytes: Buffer,
): Promise<{ ok: true; id: string } | { ok: false; result: CreateConsultationResult }> {
  const form = new FormData();
  // A fresh copy over a concrete ArrayBuffer, so the Blob constructor accepts it.
  form.append(
    'photo',
    new Blob([new Uint8Array(bytes)], { type: photoMimeFor(path.extname(filePath).slice(1)) }),
    path.basename(filePath),
  );

  let response: Response;
  try {
    response = await fetch(`${sidecar.baseUrl}/sessions`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${sidecar.secret}` },
      body: form,
    });
  } catch (error) {
    console.error('[consultation] upload failed:', error);
    return {
      ok: false,
      result: { status: 'failed', code: 'service_unavailable', message: UNAVAILABLE_MESSAGE },
    };
  }

  const body = (await response.json().catch(() => null)) as {
    session_id?: string;
    code?: string;
    message?: string;
  } | null;

  if (!response.ok) {
    return {
      ok: false,
      result: {
        status: 'failed',
        code: body?.code ?? 'upload_failed',
        message: body?.message ?? 'The photo could not be loaded. Please try another file.',
      },
    };
  }

  if (!body?.session_id) {
    return {
      ok: false,
      result: {
        status: 'failed',
        code: 'malformed_response',
        message: 'The photo could not be loaded. Please try another file.',
      },
    };
  }

  return { ok: true, id: body.session_id };
}
