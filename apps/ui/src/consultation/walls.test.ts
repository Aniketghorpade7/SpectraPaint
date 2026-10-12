import { describe, expect, it } from 'vitest';

import type { CorrectionTool, WallPlaneOverlay } from '../../../desktop/src/bridge-types';
import {
  applyWallsEvent,
  INITIAL_WALLS_STATE,
  matteOutline,
  overlayVisible,
  type MatteImage,
} from './walls';

const plane: WallPlaneOverlay = {
  planeId: 'wall_plane_1',
  surface: 'wall',
  coverage: 0.42,
  photoWidth: 1280,
  photoHeight: 720,
  bounds: { left: 0, top: 0, right: 1280, bottom: 500 },
  matteDataUrl: 'data:image/png;base64,AAAA',
};

describe('applyWallsEvent', () => {
  it('holds the planes the service found', () => {
    const state = applyWallsEvent(INITIAL_WALLS_STATE, {
      type: 'found',
      planes: [plane],
      note: null,
      photoWidth: 1280,
      photoHeight: 720,
    });

    expect(state.planes).toEqual([plane]);
    expect(state.message).toBeUndefined();
    expect(state.photoWidth).toBe(1280);
    expect(state.photoHeight).toBe(720);
  });

  it('holds the photo’s own dimensions even when no plane was found at all', () => {
    // Ticket #10: automatic detection finding nothing is not a failure — the Add tool still
    // needs the photo's pixel space to turn a tap into a point in it.
    const state = applyWallsEvent(INITIAL_WALLS_STATE, {
      type: 'found',
      planes: [],
      note: 'No wall could be found in that photo automatically.',
      photoWidth: 1280,
      photoHeight: 720,
    });

    expect(state.planes).toEqual([]);
    expect(state.message).toBe('No wall could be found in that photo automatically.');
    expect(state.photoWidth).toBe(1280);
    expect(state.photoHeight).toBe(720);
  });

  it('holds the photo’s own quality note, independent of the wall note', () => {
    // Ticket #15: a poor photo still has its wall found — the two notes describe different things.
    const state = applyWallsEvent(INITIAL_WALLS_STATE, {
      type: 'found',
      planes: [plane],
      note: null,
      qualityNote: 'This photo is quite dark, so the colours shown may look muted.',
      photoWidth: 1280,
      photoHeight: 720,
    });

    expect(state.message).toBeUndefined();
    expect(state.qualityNote).toBe(
      'This photo is quite dark, so the colours shown may look muted.',
    );
  });

  it('keeps the Dealer’s choice to hide the overlay when new planes arrive', () => {
    const hidden = applyWallsEvent(INITIAL_WALLS_STATE, { type: 'toggle' });

    const state = applyWallsEvent(hidden, {
      type: 'found',
      planes: [plane],
      note: null,
      photoWidth: 1280,
      photoHeight: 720,
    });

    expect(state.wanted).toBe(false);
  });

  it('clears a stale note once a correction leaves the photo with planes again', () => {
    const noted = applyWallsEvent(INITIAL_WALLS_STATE, {
      type: 'found',
      planes: [],
      note: 'No wall could be found in that photo automatically.',
      photoWidth: 1280,
      photoHeight: 720,
    });

    const state = applyWallsEvent(noted, {
      type: 'found',
      planes: [plane],
      note: null,
      photoWidth: 1280,
      photoHeight: 720,
    });

    expect(state.message).toBeUndefined();
  });

  it('records why there is no overlay without discarding the preference', () => {
    const state = applyWallsEvent(INITIAL_WALLS_STATE, {
      type: 'unavailable',
      message: 'No wall could be found in that photo.',
    });

    expect(state.planes).toEqual([]);
    expect(state.message).toBe('No wall could be found in that photo.');
    expect(state.wanted).toBe(true);
  });

  it('clears back to the initial state when the photo is put down', () => {
    const state = applyWallsEvent(
      { planes: [plane], wanted: false, message: 'x', photoWidth: 1280, photoHeight: 720 },
      {
        type: 'cleared',
      },
    );

    expect(state).toEqual(INITIAL_WALLS_STATE);
  });
});

function found(planes: WallPlaneOverlay[]) {
  return {
    type: 'found' as const,
    planes,
    note: null,
    photoWidth: 1280,
    photoHeight: 720,
  };
}

describe('overlayVisible', () => {
  const everyTool: (CorrectionTool | null)[] = ['add', 'add-ceiling', 'split', 'merge', null];

  it('shows the overlay once planes are known', () => {
    const state = applyWallsEvent(INITIAL_WALLS_STATE, found([plane]));

    expect(overlayVisible(state, false, null)).toBe(true);
  });

  it('never shows the overlay over a repaint, whatever tool is armed', () => {
    // ui-guidelines.md: nothing may sit between the Customer and the colour they are judging.
    // Issue #49: the armed tool's old override put the wash back over the painted render, where
    // the tool buttons (hidden while a render shows) gave the Dealer no way to disarm it — so the
    // render gate comes first, for every tool and none.
    const state = applyWallsEvent(INITIAL_WALLS_STATE, found([plane]));

    for (const armedTool of everyTool) {
      expect(overlayVisible(state, true, armedTool)).toBe(false);
    }
  });

  it('stays up for an armed tool even when the Dealer had hidden the overlay', () => {
    // Ticket #10: correcting walls that are not visible is not a thing a Dealer can do. Only over
    // the photo, though — the render gate above wins.
    const state = { ...INITIAL_WALLS_STATE, planes: [plane], wanted: false };

    expect(overlayVisible(state, false, 'add')).toBe(true);
  });

  it('stays off when the Dealer has hidden it and nothing is armed', () => {
    const found_ = applyWallsEvent(INITIAL_WALLS_STATE, found([plane]));

    expect(overlayVisible(applyWallsEvent(found_, { type: 'toggle' }), false, null)).toBe(false);
  });

  it('has nothing to show when no plane was found and nothing is armed', () => {
    expect(overlayVisible(INITIAL_WALLS_STATE, false, null)).toBe(false);
  });

  it('shows the overlay for an armed tool even with zero planes', () => {
    // Ticket #10's Add tool on a photo with nothing detected at all: the correction surface needs
    // its overlay context on screen.
    for (const armedTool of ['add', 'add-ceiling', 'split', 'merge'] as const) {
      expect(overlayVisible(INITIAL_WALLS_STATE, false, armedTool)).toBe(true);
    }
  });
});

/**
 * A synthetic matte, in the shape the service actually serves: an 8-bit mode-L greyscale PNG
 * (planes.py ``_encode_matte``), so coverage sits in every colour channel and alpha is opaque
 * *everywhere*. A filled disc, grey 255 inside the radius and 0 outside.
 */
function discMatte(size: number, radius: number): MatteImage {
  const data = new Uint8ClampedArray(size * size * 4);
  const centre = (size - 1) / 2;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const level = (x - centre) ** 2 + (y - centre) ** 2 <= radius ** 2 ? 255 : 0;
      const o = (y * size + x) * 4;
      data[o] = level;
      data[o + 1] = level;
      data[o + 2] = level;
      data[o + 3] = 255;
    }
  }
  return { width: size, height: size, data };
}

/** The grey level the threshold reads — one channel, since the matte is greyscale by contract. */
function levelOf(matte: MatteImage, x: number, y: number): number {
  return matte.data[(y * matte.width + x) * 4] ?? 0;
}

describe('matteOutline', () => {
  // A 33×33 disc of radius 10: interior wide enough that the outline's two sides never meet.
  const size = 33;
  const radius = 10;

  it('reads the grey level, never the alpha byte a mode-L matte sets to 255 everywhere', () => {
    // The regression the headless-Chrome layout check caught (issue #49). The Alpha Matte is served
    // as a greyscale PNG, so it decodes with alpha opaque on *every* pixel; thresholding alpha saw
    // one wall covering the whole photo, and the chosen-wall outline came out as a rectangle around
    // the room's frame instead of the wall's edge.
    const matte = discMatte(size, radius);
    for (let i = 3; i < matte.data.length; i += 4) expect(matte.data[i]).toBe(255);

    const outline = matteOutline(matte, 2);
    // Coverage was read from the grey level at all — the wall's rim is drawn.
    expect(outline.data.some((v) => v === 255)).toBe(true);
    // And it is the wall's rim, not the photo's frame, which is what reading alpha produced.
    for (const [x, y] of [
      [0, 0],
      [size - 1, 0],
      [0, size - 1],
      [size - 1, size - 1],
    ]) {
      expect(levelOf(outline, x!, y!)).toBe(0);
    }
  });

  it('counts a half-covered pixel as the wall and a dimmer one as outside', () => {
    // The Alpha Matte is soft-edged by definition: boundary pixels are partially covered, which is
    // why 128 is the halfway point rather than "any coverage at all".
    const softMatte: MatteImage = {
      width: 3,
      height: 1,
      data: new Uint8ClampedArray([0, 0, 0, 255, 127, 127, 127, 255, 128, 128, 128, 255]),
    };

    const outline = matteOutline(softMatte, 1);
    expect(outline.data.slice(0, 4).every((v) => v === 0)).toBe(true); // not covered
    expect(outline.data.slice(4, 8).every((v) => v === 0)).toBe(true); // under half: outside
    expect(Array.from(outline.data.slice(8, 12))).toEqual([255, 255, 255, 255]); // half: inside
  });

  it('marks a closed ring: every edge pixel of the matte is on the outline', () => {
    const matte = discMatte(size, radius);
    const outline = matteOutline(matte, 2);

    let edges = 0;
    let marked = 0;
    const neighbours: [number, number][] = [];
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const i = y * size + x;
        const isInside = levelOf(matte, x, y) >= 128;
        neighbours.length = 0;
        neighbours.push([x - 1, y], [x + 1, y], [x, y - 1], [x, y + 1]);
        const neighbourOutside = neighbours.some(([nx, ny]) =>
          nx < 0 || ny < 0 || nx >= size || ny >= size ? false : levelOf(matte, nx!, ny!) < 128,
        );
        if (isInside && neighbourOutside) {
          edges++;
          if (outline.data[i * 4 + 3] === 255) marked++;
        }
      }
    }

    expect(edges).toBeGreaterThan(0);
    expect(marked).toBe(edges); // no gaps: the ring is closed
  });

  it('marks only pixels of the matte itself, in the matte’s own dimensions', () => {
    const matte = discMatte(size, radius);
    const outline = matteOutline(matte, 2);

    expect(outline.width).toBe(size);
    expect(outline.height).toBe(size);
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const o = (y * size + x) * 4;
        if (outline.data[o + 3] === 255) {
          expect(levelOf(matte, x, y)).toBeGreaterThanOrEqual(128);
        } else {
          expect(outline.data[o]).toBe(0);
          expect(outline.data[o + 1]).toBe(0);
          expect(outline.data[o + 2]).toBe(0);
        }
      }
    }
  });

  it('is exactly the requested width along the boundary', () => {
    const matte = discMatte(size, radius);
    const centreRow = (size - 1) / 2;

    for (const width of [1, 2, 4]) {
      const outline = matteOutline(matte, width);
      const onRow: number[] = [];
      for (let x = 0; x < size; x++) {
        if (outline.data[(centreRow * size + x) * 4 + 3] === 255) onRow.push(x);
      }
      // Two runs — one per side of the disc — of exactly `width` contiguous pixels each.
      expect(onRow.length).toBe(width * 2);
      const leftStart = onRow[0] ?? 0;
      const rightStart = onRow[width] ?? 0;
      for (let k = 0; k < width; k++) {
        expect(onRow[k]).toBe(leftStart + k); // left run
        expect(onRow[width + k]).toBe(rightStart + k); // right run
      }
    }
  });

  it('leaves the matte’s interior and the photo’s borders alone', () => {
    const matte = discMatte(size, radius);
    const outline = matteOutline(matte, 2);

    // The centre of the disc is nowhere near the boundary.
    expect(outline.data[(((size - 1) / 2) * size + (size - 1) / 2) * 4 + 3]).toBe(0);
    // A wall running off the edge of the photo has no edge there: nothing is outlined merely for
    // touching the frame.
    const borderMatte: MatteImage = {
      width: 4,
      height: 4,
      data: new Uint8ClampedArray(4 * 4 * 4).fill(255),
    };
    expect(matteOutline(borderMatte, 2).data.every((v) => v === 0)).toBe(true);
  });

  it('answers a degenerate request with an empty image of the same size', () => {
    const matte = discMatte(size, radius);

    for (const width of [0, -1]) {
      const outline = matteOutline(matte, width);
      expect(outline.width).toBe(size);
      expect(outline.height).toBe(size);
      expect(outline.data.every((v) => v === 0)).toBe(true);
    }
  });
});
