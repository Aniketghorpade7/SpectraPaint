import type { Page } from 'playwright-core';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { startBrowserHarness, type BrowserHarness } from './browserHarness';

/**
 * Undo and Redo through the real hook and the real menu routing (issue #50).
 *
 * The issue asks for hook-level coverage; the repo has no component-testing packages, so these ran
 * as pure functions only (technical-difficulties.md #28) — which cannot say how many requests the
 * hook makes, or that the right history is cleared. The browser harness (layoutHarness.tsx) can: it
 * is the real `useConsultation` over a scripted bridge that counts render requests and answers an
 * empty paint the way the service does, and `window.__menu` is what main's menu click sends.
 */

const VIEWPORT = { width: 1280, height: 720 };
const RETRIES = 2;

let harness: BrowserHarness;

beforeAll(async () => {
  harness = await startBrowserHarness();
}, 60_000);

afterAll(async () => {
  await harness?.close();
});

/** A Consultation with its walls on screen and nothing painted yet. */
async function openConsultation(): Promise<Page> {
  const page = await harness.open(VIEWPORT, { ratio: '1.33' });
  await page.getByRole('button', { name: 'Choose a Room Photo' }).click();
  await page.waitForFunction(
    () =>
      document.querySelectorAll('.consultation__wall-overlay').length === 2 &&
      window.__menuState !== null,
  );
  return page;
}

/** Tap a Shade and wait for its repaint to land. */
async function applyShade(page: Page, shadeCode: string): Promise<void> {
  await page.evaluate((code) => window.__live.applyShade(code), shadeCode);
  await page.waitForFunction(
    (code) => window.__live.render.phase === 'ready' && window.__live.render.shadeCode === code,
    shadeCode,
  );
}

const assignments = (page: Page) => page.evaluate(() => window.__live.paint.assignments);
const target = (page: Page) => page.evaluate(() => window.__live.paint.target);
const renderCalls = (page: Page) => page.evaluate(() => window.__renderCalls.length);
const menuState = (page: Page) => page.evaluate(() => window.__menuState);
const settle = (page: Page) => page.waitForTimeout(100);

/** Choose a wall, and wait until the Consultation has published the history that choice made. */
async function chooseWall(page: Page, planeId: string): Promise<void> {
  await page.evaluate((id) => window.__live.selectWall(id), planeId);
  // The menu click is only as good as the render it follows: wait for the effect that publishes
  // canUndo, which runs after the commit that holds the new history.
  await page.waitForFunction(() => window.__menuState?.canUndo === true);
}

async function press(page: Page, command: 'undo' | 'redo'): Promise<void> {
  await page.evaluate((c) => window.__menu(c), command);
  await settle(page);
}

describe('Undo and Redo', { retry: RETRIES }, () => {
  it('Shade A then Shade B, then Undo: the post-A paint, and exactly one render request', async () => {
    const page = await openConsultation();
    try {
      await applyShade(page, 'PS-1001');
      const postA = await assignments(page);
      await applyShade(page, 'PS-1002');
      expect(await renderCalls(page)).toBe(2);

      await press(page, 'undo');

      expect(await assignments(page)).toEqual(postA);
      expect(await renderCalls(page)).toBe(3); // exactly one more
      expect(await page.evaluate(() => window.__live.render.phase)).toBe('ready');

      await press(page, 'redo');
      expect(await page.evaluate(() => Object.values(window.__live.paint.assignments))).toEqual([
        'PS-1002',
        'PS-1002',
      ]);
      expect(await renderCalls(page)).toBe(4);
      expect(harness.problemsOn(page)).toEqual([]);
    } finally {
      await page.close();
    }
  }, 60_000);

  it('Undo and Redo are disabled with nothing to undo or redo, and follow the history', async () => {
    const page = await openConsultation();
    try {
      expect(await menuState(page)).toEqual({ canUndo: false, canRedo: false });
      await applyShade(page, 'PS-1001');
      expect(await menuState(page)).toEqual({ canUndo: true, canRedo: false });
      await press(page, 'undo');
      expect(await menuState(page)).toEqual({ canUndo: false, canRedo: true });
      await press(page, 'redo');
      expect(await menuState(page)).toEqual({ canUndo: true, canRedo: false });
    } finally {
      await page.close();
    }
  }, 60_000);

  it('Undo back to the start returns the original photo, with no repaint requested', async () => {
    const page = await openConsultation();
    try {
      await applyShade(page, 'PS-1001');
      await press(page, 'undo');

      expect(await assignments(page)).toEqual({});
      expect(await page.evaluate(() => window.__live.render.showingRender)).toBe(false);
      expect(await renderCalls(page)).toBe(1); // only the original tap
    } finally {
      await page.close();
    }
  }, 60_000);

  it('a wall chosen before any Shade survives Undo then Redo with no failed repaint', async () => {
    // The sequence that used to ask the service to paint nothing, and be refused.
    const page = await openConsultation();
    try {
      await chooseWall(page, 'wall_plane_1');
      await press(page, 'undo');
      expect(await target(page)).toEqual({ kind: 'all' });
      await press(page, 'redo');

      expect(await target(page)).toEqual({ kind: 'plane', planeId: 'wall_plane_1' });
      expect(await renderCalls(page)).toBe(0);
      expect(await page.evaluate(() => window.__live.render.phase)).toBe('idle');
    } finally {
      await page.close();
    }
  }, 60_000);

  it('undoing only a wall choice does not ask for the same picture again', async () => {
    const page = await openConsultation();
    try {
      await applyShade(page, 'PS-1001');
      await chooseWall(page, 'wall_plane_1');
      expect(await renderCalls(page)).toBe(1);

      await press(page, 'undo');

      expect(await target(page)).toEqual({ kind: 'all' });
      expect(await renderCalls(page)).toBe(1);
      expect(await page.evaluate(() => window.__live.render.showingRender)).toBe(true);
    } finally {
      await page.close();
    }
  }, 60_000);

  it('a wall correction clears the history: nothing to undo, nothing replayed', async () => {
    const page = await openConsultation();
    try {
      await applyShade(page, 'PS-1001');
      expect(await menuState(page)).toEqual({ canUndo: true, canRedo: false });

      await page.evaluate(() => window.__live.armTool('split'));
      // A tap before the commit that arms the tool is a no-op: wait for the hook to say it is armed.
      await page.waitForFunction(() => window.__live.armedTool === 'split');
      await page.evaluate(() => window.__live.correctWallsAt({ x: 100, y: 100 }));
      await page.waitForFunction(() => window.__menuState?.canUndo === false);

      const calls = await renderCalls(page);
      await press(page, 'undo');
      expect(await renderCalls(page)).toBe(calls);
      expect(harness.problemsOn(page)).toEqual([]);
    } finally {
      await page.close();
    }
  }, 60_000);

  it('discarding the photo clears the history', async () => {
    const page = await openConsultation();
    try {
      await applyShade(page, 'PS-1001');
      await page.evaluate(() => window.__live.discard());
      await page.waitForFunction(() => window.__menuState?.canUndo === false);
    } finally {
      await page.close();
    }
  }, 60_000);

  it('in the Catalogue search box, Undo acts on the text and never on the Shades', async () => {
    const page = await openConsultation();
    try {
      await applyShade(page, 'PS-1001');
      const postA = await assignments(page);
      await applyShade(page, 'PS-1002');
      const postB = await assignments(page);

      await page.getByRole('searchbox').click();
      await page.keyboard.type('linen');
      await press(page, 'undo');

      expect(await assignments(page)).toEqual(postB);
      expect(await assignments(page)).not.toEqual(postA);
      expect(await renderCalls(page)).toBe(2);
      // The text itself was undone by the browser's own edit history.
      expect(await page.getByRole('searchbox').inputValue()).not.toBe('linen');
    } finally {
      await page.close();
    }
  }, 60_000);

  it('Tapping a Shade after Undo drops the redo branch', async () => {
    const page = await openConsultation();
    try {
      await applyShade(page, 'PS-1001');
      await applyShade(page, 'PS-1002');
      await press(page, 'undo');
      expect((await menuState(page))?.canRedo).toBe(true);
      await applyShade(page, 'PS-1003');
      expect(await menuState(page)).toEqual({ canUndo: true, canRedo: false });
    } finally {
      await page.close();
    }
  }, 60_000);
});
