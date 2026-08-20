import { describe, expect, it } from 'vitest';

import type { WallPlaneOverlay } from '../../../desktop/src/bridge-types';
import { applyWallsEvent, INITIAL_WALLS_STATE, overlayVisible } from './walls';

const plane: WallPlaneOverlay = {
  planeId: 'wall_plane_1',
  coverage: 0.42,
  photoWidth: 1280,
  photoHeight: 720,
  bounds: { left: 0, top: 0, right: 1280, bottom: 500 },
  matteDataUrl: 'data:image/png;base64,AAAA',
};

describe('applyWallsEvent', () => {
  it('holds the planes the service found', () => {
    const state = applyWallsEvent(INITIAL_WALLS_STATE, { type: 'found', planes: [plane] });

    expect(state.planes).toEqual([plane]);
    expect(state.message).toBeUndefined();
  });

  it('keeps the Dealer’s choice to hide the overlay when new planes arrive', () => {
    const hidden = applyWallsEvent(INITIAL_WALLS_STATE, { type: 'toggle' });

    const state = applyWallsEvent(hidden, { type: 'found', planes: [plane] });

    expect(state.wanted).toBe(false);
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
      { planes: [plane], wanted: false, message: 'x' },
      {
        type: 'cleared',
      },
    );

    expect(state).toEqual(INITIAL_WALLS_STATE);
  });
});

describe('overlayVisible', () => {
  it('shows the overlay once planes are known', () => {
    const state = applyWallsEvent(INITIAL_WALLS_STATE, { type: 'found', planes: [plane] });

    expect(overlayVisible(state, false)).toBe(true);
  });

  it('never shows the overlay over a repaint', () => {
    // ui-guidelines.md: nothing may sit between the Customer and the colour they are judging.
    const state = applyWallsEvent(INITIAL_WALLS_STATE, { type: 'found', planes: [plane] });

    expect(overlayVisible(state, true)).toBe(false);
  });

  it('stays off when the Dealer has hidden it', () => {
    const found = applyWallsEvent(INITIAL_WALLS_STATE, { type: 'found', planes: [plane] });

    expect(overlayVisible(applyWallsEvent(found, { type: 'toggle' }), false)).toBe(false);
  });

  it('has nothing to show when no plane was found', () => {
    expect(overlayVisible(INITIAL_WALLS_STATE, false)).toBe(false);
  });
});
