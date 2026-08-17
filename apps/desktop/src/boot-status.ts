import { ipcMain, type BrowserWindow, type WebContents } from 'electron';

import {
  BOOT_STATUS_CHANNEL,
  BOOT_STATUS_GET_CHANNEL,
  BOOT_STATUS_RETRY_CHANNEL,
} from './channels';
import type { BootStatus } from './bridge-types';

/**
 * Boot progress, from main to the boot screen.
 *
 * Holds the current status as well as broadcasting it. Pushing alone would lose a race the Dealer
 * sees on every fast launch: the service can reach 'ready' before the renderer has finished
 * loading and subscribed, leaving a boot screen that waits forever for an event already sent. The
 * renderer therefore reads the current status on mount and subscribes for the rest.
 */
export class BootStatusHub {
  private status: BootStatus = { phase: 'starting' };
  private window: BrowserWindow | null = null;

  attach(window: BrowserWindow): void {
    this.window = window;
  }

  current(): BootStatus {
    return this.status;
  }

  set(status: BootStatus): void {
    this.status = status;
    if (this.window && !this.window.isDestroyed()) {
      this.window.webContents.send(BOOT_STATUS_CHANNEL, status);
    }
  }
}

export function registerBootStatusBridge(
  hub: BootStatusHub,
  retry: () => Promise<void>,
  isTrustedSender: (sender: WebContents) => boolean,
): void {
  ipcMain.handle(BOOT_STATUS_GET_CHANNEL, (event): BootStatus => {
    return isTrustedSender(event.sender) ? hub.current() : { phase: 'starting' };
  });

  ipcMain.handle(BOOT_STATUS_RETRY_CHANNEL, async (event): Promise<void> => {
    if (!isTrustedSender(event.sender)) return;
    await retry();
  });
}
