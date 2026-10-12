import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { chromium, type Browser, type Page } from 'playwright-core';
import { createServer, type ViteDevServer } from 'vite';

/**
 * A real browser on the real surface, shared by the tests that need one (design-decisions.md §9d).
 *
 * Serves `layout-harness.html` — the real `ConsultationSurface` and `useConsultation` over a
 * scripted bridge, see layoutHarness.tsx — from an in-process Vite on any free port, and drives it
 * with headless Chromium. The browser is a dev dependency's download, not the app's:
 * `npm run browsers` fetches it once (CI does the same before `npm run check`).
 */

const UI_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

export interface BrowserHarness {
  /** A fresh page on the harness, with the case chosen by query parameters (layoutHarness.tsx). */
  open(viewport: { width: number; height: number }, search?: Record<string, string>): Promise<Page>;
  /** Page errors and console errors so far: a test that "passes" with the app throwing is not one. */
  problemsOn(page: Page): string[];
  close(): Promise<void>;
}

export async function startBrowserHarness(): Promise<BrowserHarness> {
  const server: ViteDevServer = await createServer({
    configFile: false,
    root: UI_ROOT,
    plugins: [react()],
    logLevel: 'silent',
    // Port 0: any free port, so a dev server already running on this machine is no obstacle.
    server: { host: '127.0.0.1', port: 0, hmr: false },
  });
  await server.listen();
  const address = server.httpServer?.address();
  if (address === null || address === undefined || typeof address === 'string') {
    await server.close();
    throw new Error('the browser test server did not bind to a port');
  }
  const baseUrl = `http://127.0.0.1:${address.port}`;

  let browser: Browser;
  try {
    browser = await chromium.launch();
  } catch (error) {
    await server.close();
    throw new Error(
      'These tests need Chromium and could not start it. Run `npm run browsers` once.',
      { cause: error },
    );
  }

  const problems = new WeakMap<Page, string[]>();

  return {
    async open(viewport, search = {}) {
      const page = await browser.newPage({ viewport });
      // A step that cannot proceed fails in seconds and says which step, rather than sitting until
      // the test's own timeout (a Windows runner once hung a click for the full 30 s).
      page.setDefaultTimeout(10_000);
      const seen: string[] = [];
      page.on('pageerror', (error) => seen.push(error.message));
      page.on('console', (message) => {
        if (message.type() === 'error') seen.push(message.text());
      });
      problems.set(page, seen);
      await page.goto(`${baseUrl}/layout-harness.html?${new URLSearchParams(search)}`);
      return page;
    },
    problemsOn: (page) => problems.get(page) ?? [],
    async close() {
      await browser.close();
      await server.close();
    },
  };
}
