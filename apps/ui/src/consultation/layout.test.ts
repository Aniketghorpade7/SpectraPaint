import type { Page } from 'playwright-core';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { startBrowserHarness, type BrowserHarness } from './browserHarness';

/**
 * The Room Photo's layout, measured in a real browser (issue #49).
 *
 * Every other test here is a pure function; this one cannot be, because the thing under test is CSS:
 * the frame is the largest box of the photo's own ratio that fits the stage, and the overlay,
 * outline, chips and tap layer all align to it. Technical difficulty #23's check — two elements
 * agreeing on a box — passed while that box was simply too tall for the stage, so this one measures
 * the box against the *stage*, with real `getBoundingClientRect()`.
 *
 * It renders the real `ConsultationSurface` and `useConsultation` (see layoutHarness.tsx) in
 * headless Chromium served by an in-process Vite. The browser is a dev dependency's download, not
 * the app's: `npm run browsers` fetches it once (CI does the same before `npm run check`).
 */

const TOLERANCE_PX = 1.5;
// Layout is deterministic, but a loaded CI runner is not: a cold browser can stall a single step.
// Two retries absorb that without hiding a real failure, which fails every attempt.
const RETRIES = 2;

const VIEWPORTS = [
  { width: 1280, height: 720 },
  { width: 1920, height: 1080 },
] as const;
// Portrait 1:2 and 3:4, landscape 4:3 and 16:9.
const RATIOS = [0.5, 0.75, 1.33, 1.78] as const;

let harness: BrowserHarness;

beforeAll(async () => {
  harness = await startBrowserHarness();
}, 60_000);

afterAll(async () => {
  await harness?.close();
});

const open: BrowserHarness['open'] = (...args) => harness.open(...args);

interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

const problemsOn = (page: Page) => harness.problemsOn(page);

/** A Dealer's flow up to the walls being on screen: choose a photo, wait for the prepared one. */
async function loadRoomPhoto(page: Page, ratio: number): Promise<void> {
  await page.getByRole('button', { name: 'Choose a Room Photo' }).click();
  await page.waitForSelector('.consultation__frame');
  // The prepared photo has replaced the placeholder once the frame's ratio is the prepared one and
  // the walls are drawn over it.
  await page.waitForFunction(
    (expected) => {
      const img = document.querySelector<HTMLImageElement>('.consultation__photo');
      return (
        img !== null &&
        img.naturalHeight > 0 &&
        Math.abs(img.naturalWidth / img.naturalHeight - expected) < 0.01 &&
        document.querySelectorAll('.consultation__wall-overlay').length === 2
      );
    },
    ratio,
    { timeout: 10_000 },
  );
}

/** The boxes this layout is about, in CSS pixels, read live from the page. */
function measure(page: Page) {
  return page.evaluate(() => {
    const box = (element: Element | null): Box | null => {
      if (element === null) return null;
      const r = element.getBoundingClientRect();
      return {
        left: r.left,
        top: r.top,
        right: r.right,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      };
    };
    const boxes = (selector: string) => [...document.querySelectorAll(selector)].map(box);

    const stage = document.querySelector('.consultation__stage');
    if (stage === null) throw new Error('no stage');
    const style = getComputedStyle(stage);
    const stageBox = box(stage);
    if (stageBox === null) throw new Error('no stage box');
    const inset = (side: string) => parseFloat(style.getPropertyValue(`padding-${side}`));
    const stageContent: Box = {
      left: stageBox.left + inset('left'),
      top: stageBox.top + inset('top'),
      right: stageBox.right - inset('right'),
      bottom: stageBox.bottom - inset('bottom'),
      width: stageBox.width - inset('left') - inset('right'),
      height: stageBox.height - inset('top') - inset('bottom'),
    };

    const slot = document.querySelector('.consultation__frame-slot');
    return {
      stageContent,
      slot: box(slot),
      frame: box(document.querySelector('.consultation__frame')),
      photo: box(document.querySelector('.consultation__photo')),
      overlays: boxes('.consultation__wall-overlay'),
      outlines: boxes('.consultation__wall-outline'),
      chips: boxes('.consultation__wall-chip'),
      tapLayers: boxes('.consultation__tap-layer'),
      notesInsideSlot: slot === null ? 0 : slot.querySelectorAll('.consultation__wall-note').length,
      notes: document.querySelectorAll('.consultation__wall-note').length,
    };
  });
}

function expectSameBox(actual: Box | null, expected: Box | null, what: string): void {
  expect(actual, `${what} is on screen`).not.toBeNull();
  expect(expected).not.toBeNull();
  if (actual === null || expected === null) return;
  for (const side of ['left', 'top', 'right', 'bottom'] as const) {
    expect(
      Math.abs(actual[side] - expected[side]),
      `${what} ${side}: ${actual[side]} vs the frame's ${expected[side]}`,
    ).toBeLessThanOrEqual(TOLERANCE_PX);
  }
}

describe('the Room Photo fits the stage', { retry: RETRIES }, () => {
  for (const viewport of VIEWPORTS) {
    for (const ratio of RATIOS) {
      it(`${viewport.width}×${viewport.height}, photo ratio ${ratio}: whole photo visible, everything aligned`, async () => {
        const page = await open(viewport, { ratio: String(ratio) });
        try {
          await loadRoomPhoto(page, ratio);
          // Choose a wall, so the outline exists; then arm a tool, so the tap layer does.
          await page
            .getByRole('button', { name: /wall 1|left/i })
            .first()
            .click();
          await page.waitForSelector('.consultation__wall-outline');
          await page.evaluate(() => window.__live.armTool('add'));
          await page.waitForSelector('.consultation__tap-layer');
          // The outline and the matte are drawn asynchronously; let them settle.
          await page.waitForTimeout(150);

          const m = await measure(page);
          const { frame, stageContent, slot } = m;
          expect(frame).not.toBeNull();
          if (frame === null || slot === null) return;

          // Nothing clipped: the frame lies inside the stage's content box, on both axes.
          expect(frame.left).toBeGreaterThanOrEqual(stageContent.left - TOLERANCE_PX);
          expect(frame.top).toBeGreaterThanOrEqual(stageContent.top - TOLERANCE_PX);
          expect(frame.right).toBeLessThanOrEqual(stageContent.right + TOLERANCE_PX);
          expect(frame.bottom).toBeLessThanOrEqual(stageContent.bottom + TOLERANCE_PX);

          // The frame is the photo's own shape, and fills the slot on at least one axis (it is the
          // *largest* box that fits, not merely one that fits).
          expect(frame.width / frame.height).toBeCloseTo(ratio, 1);
          const fillsWidth = Math.abs(frame.width - slot.width) <= TOLERANCE_PX;
          const fillsHeight = Math.abs(frame.height - slot.height) <= TOLERANCE_PX;
          expect(fillsWidth || fillsHeight, 'frame is the largest box that fits').toBe(true);

          // Everything the photo carries is the frame's exact box (difficulty #23's invariant).
          expectSameBox(m.photo, frame, 'the photo');
          expect(m.overlays).toHaveLength(2);
          m.overlays.forEach((box, index) => expectSameBox(box, frame, `overlay ${index}`));
          expect(m.outlines).toHaveLength(1);
          expectSameBox(m.outlines[0] ?? null, frame, 'the outline');
          expect(m.tapLayers).toHaveLength(1);
          expectSameBox(m.tapLayers[0] ?? null, frame, 'the tap layer');

          // Status line and notes live outside the slot, never over the photo.
          expect(m.notes).toBeGreaterThan(0);
          expect(m.notesInsideSlot).toBe(0);

          expect(problemsOn(page)).toEqual([]);
        } finally {
          await page.close();
        }
      }, 60_000);
    }
  }
});

describe('chips', { retry: RETRIES }, () => {
  it('sit inside the frame at every ratio', async () => {
    for (const ratio of RATIOS) {
      const page = await open(VIEWPORTS[0], { ratio: String(ratio) });
      try {
        await loadRoomPhoto(page, ratio);
        const { frame, chips } = await measure(page);
        expect(chips).toHaveLength(2);
        for (const chip of chips) {
          if (chip === null || frame === null) throw new Error('chip or frame missing');
          expect(chip.left).toBeGreaterThanOrEqual(frame.left - TOLERANCE_PX);
          expect(chip.right).toBeLessThanOrEqual(frame.right + TOLERANCE_PX);
          expect(chip.top).toBeGreaterThanOrEqual(frame.top - TOLERANCE_PX);
          expect(chip.bottom).toBeLessThanOrEqual(frame.bottom + TOLERANCE_PX);
        }
      } finally {
        await page.close();
      }
    }
  }, 60_000);
});

describe('an oriented phone photo', { retry: RETRIES }, () => {
  it('re-fits the frame to the prepared photo and never draws the walls on the placeholder', async () => {
    // The raw upload is landscape, the prepared photo portrait — an EXIF Orientation 6 photo.
    const page = await open(VIEWPORTS[0], { ratio: '0.75', placeholder: '1.33' });
    try {
      // Watch every frame from the click on: any moment the walls are on screen while the frame's
      // ratio is not the ratio of the image shown is a misaligned overlay.
      await page.evaluate(() => {
        const w = window as unknown as { __violations: string[] };
        w.__violations = [];
        const check = (again = true) => {
          const frame = document.querySelector<HTMLElement>('.consultation__frame');
          const img = document.querySelector<HTMLImageElement>('.consultation__photo');
          const drawn = document.querySelectorAll(
            '.consultation__wall-overlay, .consultation__wall-chip, .consultation__wall-outline, .consultation__tap-layer',
          );
          if (frame && img && drawn.length > 0) {
            // While the new image is still decoding, the element keeps the old pixels (and the old
            // natural size), so the frame and the image agree with each other and both are wrong
            // for the mattes. "Not complete" is the tell.
            const rect = frame.getBoundingClientRect();
            const shown = img.naturalWidth / img.naturalHeight;
            if (!img.complete) {
              w.__violations.push('walls drawn while the photo on screen is still decoding');
            } else if (Math.abs(rect.width / rect.height - shown) > 0.02) {
              w.__violations.push(`frame ${rect.width / rect.height} vs image ${shown}`);
            }
          }
          if (again) requestAnimationFrame(() => check());
        };
        requestAnimationFrame(() => check());
        // A frame sample can miss a commit that lasts less than a frame; the observer sees every
        // commit, in the microtask after it.
        new MutationObserver(() => check(false)).observe(document.body, {
          subtree: true,
          childList: true,
          attributes: true,
        });
      });

      await loadRoomPhoto(page, 0.75);
      await page.waitForTimeout(300);

      const violations = await page.evaluate(
        () => (window as unknown as { __violations: string[] }).__violations,
      );
      expect(violations).toEqual([]);

      const { frame, stageContent } = await measure(page);
      expect(frame).not.toBeNull();
      if (frame === null) return;
      expect(frame.width / frame.height).toBeCloseTo(0.75, 1);
      expect(frame.bottom).toBeLessThanOrEqual(stageContent.bottom + TOLERANCE_PX);
    } finally {
      await page.close();
    }
  }, 60_000);

  it('says so on screen when the prepared photo cannot be fetched', async () => {
    const page = await open(VIEWPORTS[0], {
      ratio: '0.75',
      placeholder: '1.33',
      failPrepared: '1',
    });
    try {
      await page.getByRole('button', { name: 'Choose a Room Photo' }).click();
      await page.waitForSelector('.consultation__frame');
      await page.waitForFunction(
        () => document.body.innerText.includes('Try loading the photo again'),
        undefined,
        { timeout: 10_000 },
      );
      // The raw upload is still on screen, and still whole.
      const { frame, stageContent } = await measure(page);
      expect(frame).not.toBeNull();
      if (frame === null) return;
      expect(frame.bottom).toBeLessThanOrEqual(stageContent.bottom + TOLERANCE_PX);
    } finally {
      await page.close();
    }
  }, 60_000);
});

describe('a repaint', { retry: RETRIES }, () => {
  it('shows with no wash, no outline and no tap layer, even after a tool was armed', async () => {
    const page = await open(VIEWPORTS[0], { ratio: '1.33' });
    try {
      await loadRoomPhoto(page, 1.33);
      await page.evaluate(() => window.__live.armTool('split'));
      await page.waitForSelector('.consultation__tap-layer');

      await page.evaluate(() => window.__live.applyShade('PS-1001'));
      await page.waitForFunction(() => window.__live.render.showingRender === true, undefined, {
        timeout: 10_000,
      });
      await page.waitForTimeout(100);

      const live = await page.evaluate(() => ({
        armed: window.__live.armedTool,
        overlays: document.querySelectorAll('.consultation__wall-overlay').length,
        outlines: document.querySelectorAll('.consultation__wall-outline').length,
        taps: document.querySelectorAll('.consultation__tap-layer').length,
      }));
      expect(live).toEqual({ armed: null, overlays: 0, outlines: 0, taps: 0 });
    } finally {
      await page.close();
    }
  }, 60_000);
});
