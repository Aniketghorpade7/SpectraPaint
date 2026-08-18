import { app, BrowserWindow, type WebContents } from 'electron';
import path from 'node:path';

import { bootStatusFor } from './boot-messages';
import { BootStatusHub, registerBootStatusBridge } from './boot-status';
import { registerCreateConsultationBridge } from './create-consultation';
import { registerServiceBridge } from './service-bridge';
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

async function startService(): Promise<void> {
  if (sidecar) return;

  try {
    bootStatus.set(bootStatusFor('starting'));
    sidecar = await startSidecar({
      onPhase: (phase) => {
        console.log(`[sidecar] ${phase}`);
        bootStatus.set(bootStatusFor(phase));
      },
    });
    console.log(`[sidecar] listening on ${sidecar.baseUrl}`);
  } catch (error) {
    const code = error instanceof SidecarStartError ? error.code : undefined;
    console.error('[sidecar] failed to start:', error);
    bootStatus.set(bootStatusFor('failed', code));
  }
}

void app.whenReady().then(async () => {
  registerServiceBridge(() => sidecar, isTrustedSender);
  registerCreateConsultationBridge(
    () => sidecar,
    () => mainWindow,
    isTrustedSender,
  );
  registerBootStatusBridge(bootStatus, startService, isTrustedSender);
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
