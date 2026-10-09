import { app, BrowserWindow, Menu, type WebContents, ipcMain } from 'electron';
import path from 'node:path';

import {
  MENU_REDO_ITEM_ID,
  MENU_REDO_SHIFT_ITEM_ID,
  MENU_UNDO_ITEM_ID,
  appMenuTemplate,
} from './app-menu';
import { bootStatusFor } from './boot-messages';
import { BootStatusHub, registerBootStatusBridge } from './boot-status';
import { registerCorrectionsBridge } from './corrections-bridge';
import {
  EXECUTION_PROFILE_GET_CHANNEL,
  EXECUTION_PROFILE_SET_CHANNEL,
  MENU_COMMAND_CHANNEL,
  MENU_STATE_CHANNEL,
  QUALITY_TIER_GET_CHANNEL,
  QUALITY_TIER_SET_CHANNEL,
} from './channels';
import { registerCreateConsultationBridge } from './create-consultation';
import { registerExportBridge } from './export-bridge';
import {
  getExecutionProfile,
  getHardwareProfile,
  getQualityTier,
  restoreQualityTier,
  setHardwareProfile,
  setOnProfileChange,
  setQualityTier,
} from './execution-profile';
import { registerPreparedPhotoBridge } from './prepared-photo-bridge';
import { registerProgressStreamBridge } from './progress-stream';
import { registerRenderBridge } from './render-bridge';
import { registerServiceBridge } from './service-bridge';
import { registerDiskBridge } from './disk-bridge';
import { registerStorageBridge } from './storage-bridge';
import { registerStoredImageBridge } from './stored-image-bridge';
import { registerWallsBridge } from './walls-bridge';
import { SidecarStartError, startSidecar, type Sidecar } from './sidecar';

/**
 * Electron main process.
 *
 * Owns everything the renderer must not — see docs/specs/v1-spectrapaint.md. The window, the
 * sidecar, the secret and the only channel between them.
 */

const isDev = process.env.SPECTRAPAINT_DEV === '1';
const UI_DEV_SERVER_URL = 'http://localhost:5273';
const UI_BUILD_ENTRY = path.join(__dirname, '..', '..', 'ui', 'dist', 'index.html');
const PRELOAD_SCRIPT = path.join(__dirname, 'preload.js');

let sidecar: Sidecar | null = null;
let mainWindow: BrowserWindow | null = null;
const bootStatus = new BootStatusHub();

// A profile change needs a service restart to take effect: the sidecar reads its hardware and
// quality settings from the environment it is launched with (sidecar.ts).
function restartSidecar(): void {
  if (!sidecar) return;
  const stopping = sidecar;
  sidecar = null;
  stopping.stop().then(() => {
    startService();
  });
}

setOnProfileChange(restartSidecar);

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    // Neutral grey, so launch does not flash white next to a render.
    backgroundColor: '#1a1a1a',
    webPreferences: {
      // Security posture is an acceptance criterion of ticket #1, not a default to drift from.
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: PRELOAD_SCRIPT,
    },
  });

  window.once('ready-to-show', () => window.show());

  if (isDev) {
    // Without this a renderer error goes only to devtools, which nobody has open.
    window.webContents.on('console-message', (details) => {
      console.log(`[renderer] ${details.message}`);
    });
  }

  if (isDev) {
    void window.loadURL(UI_DEV_SERVER_URL);
  } else {
    void window.loadFile(UI_BUILD_ENTRY);
  }

  return window;
}

/** Only our own window may drive the bridge — not a devtools extension, not a stray frame. */
function isTrustedSender(sender: WebContents): boolean {
  return mainWindow !== null && !mainWindow.isDestroyed() && sender === mainWindow.webContents;
}

/**
 * The custom application menu (issue #50). Electron's default menu would ship text-editing roles
 * that do nothing on the Consultation, plus Reload and DevTools in packaged builds. The template is
 * built by the pure `appMenuTemplate`, so only this wiring touches Electron. Menu clicks travel to
 * the renderer on `MENU_COMMAND_CHANNEL` — Undo/Redo are the Consultation's commands there, and the
 * renderer routes each one to paint or to text editing.
 */
function installApplicationMenu(): void {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate(
      appMenuTemplate({
        isPackaged: app.isPackaged,
        platform: process.platform,
        send: (command) => mainWindow?.webContents.send(MENU_COMMAND_CHANNEL, command),
      }),
    ),
  );

  // The Consultation reports what Undo/Redo have to act on; the menu items follow it, so they are
  // never grey lies (or live lies) about what the command would do. The hidden Windows-only
  // Redo sibling follows the same state — a disabled item's accelerator never fires, so leaving
  // it disabled would silently drop Ctrl+Shift+Z (issue #50).
  ipcMain.on(MENU_STATE_CHANNEL, (event, state: unknown) => {
    if (!isTrustedSender(event.sender)) return;
    // The sender is trusted, the shape still is not: an item's enabled flag is only ever set from a
    // real boolean, never from whatever arrived.
    const { canUndo, canRedo } = (state ?? {}) as { canUndo?: unknown; canRedo?: unknown };
    const menu = Menu.getApplicationMenu();
    const undo = menu?.getMenuItemById(MENU_UNDO_ITEM_ID);
    const redo = menu?.getMenuItemById(MENU_REDO_ITEM_ID);
    const redoShift = menu?.getMenuItemById(MENU_REDO_SHIFT_ITEM_ID);
    if (undo) undo.enabled = canUndo === true;
    if (redo) redo.enabled = canRedo === true;
    if (redoShift) redoShift.enabled = canRedo === true;
  });
}

async function startService(): Promise<void> {
  if (sidecar) return;

  try {
    bootStatus.set(bootStatusFor('starting'));
    sidecar = await startSidecar({
      onPhase: (phase) => {
        console.log(`[sidecar] ${phase}`);
        bootStatus.set(bootStatusFor(phase));
      },
      hardwareProfile: getHardwareProfile(),
      qualityTier: getQualityTier(),
    });
    console.log(`[sidecar] listening on ${sidecar.baseUrl}`);
  } catch (error) {
    const code = error instanceof SidecarStartError ? error.code : undefined;
    console.error('[sidecar] failed to start:', error);
    bootStatus.set(bootStatusFor('failed', code));
  }
}

void app.whenReady().then(async () => {
  // The persisted tier is in place before the sidecar starts, so the service is launched with
  // the tier the Dealer actually chose rather than the default (issue #14 AC3).
  restoreQualityTier();
  installApplicationMenu();
  registerServiceBridge(() => sidecar, isTrustedSender);
  registerProgressStreamBridge(() => sidecar, isTrustedSender);
  registerRenderBridge(() => sidecar, isTrustedSender);
  registerExportBridge(
    () => sidecar,
    () => mainWindow,
    isTrustedSender,
  );
  registerWallsBridge(() => sidecar, isTrustedSender);
  registerCorrectionsBridge(() => sidecar, isTrustedSender);
  registerStoredImageBridge(() => sidecar, isTrustedSender);
  registerPreparedPhotoBridge(() => sidecar, isTrustedSender);
  registerStorageBridge(() => sidecar, isTrustedSender);
  registerDiskBridge(isTrustedSender);
  registerCreateConsultationBridge(
    () => sidecar,
    () => mainWindow,
    isTrustedSender,
  );
  registerBootStatusBridge(bootStatus, startService, isTrustedSender);

  ipcMain.handle(EXECUTION_PROFILE_GET_CHANNEL, (event): string => {
    return isTrustedSender(event.sender) ? getExecutionProfile() : 'cpu-better';
  });

  ipcMain.handle(EXECUTION_PROFILE_SET_CHANNEL, async (event, profile: string): Promise<void> => {
    // The composite is set by splitting it back into the two settings the Dealer actually
    // overrides — hardware and tier — each of which validates its own value and restarts the
    // sidecar when either changes.
    if (!isTrustedSender(event.sender)) return;
    const [hardware, tier] = profile.split('-');
    if (hardware === undefined || tier === undefined) return;
    setHardwareProfile(hardware);
    setQualityTier(tier);
  });

  ipcMain.handle(QUALITY_TIER_GET_CHANNEL, (event): string => {
    return isTrustedSender(event.sender) ? getQualityTier() : 'better';
  });

  ipcMain.handle(QUALITY_TIER_SET_CHANNEL, async (event, tier: string): Promise<void> => {
    if (!isTrustedSender(event.sender)) return;
    setQualityTier(tier);
  });
  mainWindow = createWindow();
  bootStatus.attach(mainWindow);

  // The window comes up first and the service starts behind it: the boot screen is what the Dealer
  // watches while this happens, so a slow start is visible progress rather than a frozen app.
  await startService();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      mainWindow = createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// The service is a child process, not a daemon: it must not outlive the app that started it.
// `before-quit` rather than `will-quit`, so the kill is issued while there is still time to await.
app.on('before-quit', async (event) => {
  if (!sidecar) return;

  event.preventDefault();
  const stopping = sidecar;
  sidecar = null;
  await stopping.stop();
  app.quit();
});

// Ctrl+C in a development terminal does not go through `before-quit` on every platform, and an
// orphaned service still holding its port is the exact failure §9c warns about.
for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    void (async () => {
      const stopping = sidecar;
      sidecar = null;
      await stopping?.stop();
      app.exit(0);
    })();
  });
}
