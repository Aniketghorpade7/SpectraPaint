import { app, ipcMain, type WebContents } from 'electron';
import fs from 'node:fs';

import { DISK_CHANNEL } from './channels';

/**
 * Low-disk probe from the Electron shell (issue #13).
 *
 * The spec says the Dealer is warned *well before* the disk is critically
 * full — the service can probe its own storage directory, but the shell
 * owns the per-user application data directory on every platform, and
 * `app.getPath('userData')` is the one place both halves agree the
 * library lives. Probing here means the warning works even if the
 * service is down.
 *
 * `fs.statfsSync` is available on Node 19+ and reports free/total in
 * bytes for the volume containing the path.
 */

const LOW_DISK_BYTES = 2 * 1024 * 1024 * 1024;
const LOW_DISK_RATIO = 0.1;

function probe(): { freeBytes: number; totalBytes: number; low: boolean } {
  try {
    const dir = app.getPath('userData');
    fs.mkdirSync(dir, { recursive: true });
    const stat = fs.statfsSync(dir);
    const freeBytes = Number(stat.bfree) * Number(stat.bsize);
    const totalBytes = Number(stat.blocks) * Number(stat.bsize);
    const low =
      freeBytes < LOW_DISK_BYTES || (totalBytes > 0 && freeBytes / totalBytes < LOW_DISK_RATIO);
    return { freeBytes, totalBytes, low };
  } catch {
    return { freeBytes: 0, totalBytes: 0, low: false };
  }
}

export function registerDiskBridge(isTrustedSender: (sender: WebContents) => boolean): void {
  ipcMain.handle(DISK_CHANNEL, (event) => {
    if (!isTrustedSender(event.sender)) {
      return { freeBytes: 0, totalBytes: 0, low: false };
    }
    return probe();
  });
}
