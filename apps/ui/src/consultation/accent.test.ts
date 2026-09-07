import { describe, expect, it } from 'vitest';

import type { WallPlaneOverlay } from '../../../desktop/src/bridge-types';
import {
  ALL_WALLS,
  describeTarget,
  describeWall,
  isTargeted,
  nextAssignments,
  renderPayload,
  toggleTarget,
} from './accent';

function planeAt(planeId: string): WallPlaneOverlay {
  return {
    planeId,
    coverage: 0.4,
    photoWidth: 1280,
    photoHeight: 720,
    bounds: { left: 0, top: 0, right: 640, bottom: 720 },
    matteDataUrl: 'data:image/png;base64,AAAA',
  };
}

const twoWalls = [planeAt('wall_plane_1'), planeAt('wall_plane_2')];

describe('toggleTarget', () => {
  it('selects a wall, and deselects the same wall', () => {
    const selected = toggleTarget(ALL_WALLS, 'wall_plane_2');
    expect(selected).toEqual({ kind: 'plane', planeId: 'wall_plane_2' });
    expect(toggleTarget(selected, 'wall_plane_2')).toEqual(ALL_WALLS);
  });

  it('moves the selection when a different wall is tapped', () => {
    const selected = toggleTarget(ALL_WALLS, 'wall_plane_1');
    expect(toggleTarget(selected, 'wall_plane_2')).toEqual({
      kind: 'plane',
      planeId: 'wall_plane_2',
    });
  });
});

describe('nextAssignments', () => {
  it('paints every wall when no single wall is selected', () => {
    expect(nextAssignments({}, ALL_WALLS, 'PS-1001', twoWalls)).toEqual({
      wall_plane_1: 'PS-1001',
      wall_plane_2: 'PS-1001',
    });
  });

  it('keeps the other wall’s Shade when one wall is painted — the Accent Wall', () => {
    const first = nextAssignments({}, ALL_WALLS, 'PS-1001', twoWalls);
    const accent = nextAssignments(
      first,
      { kind: 'plane', planeId: 'wall_plane_2' },
      'PS-6010',
      twoWalls,
    );

    expect(accent).toEqual({ wall_plane_1: 'PS-1001', wall_plane_2: 'PS-6010' });
  });

  it('drops a stale Accent Wall when every wall is painted again', () => {
    const accent = { wall_plane_1: 'PS-1001', wall_plane_2: 'PS-6010' };

    expect(nextAssignments(accent, ALL_WALLS, 'PS-9011', twoWalls)).toEqual({
      wall_plane_1: 'PS-9011',
      wall_plane_2: 'PS-9011',
    });
  });

  it('paints a wall that has no Shade yet without touching the rest', () => {
    const partial = { wall_plane_1: 'PS-1001' };

    expect(
      nextAssignments(partial, { kind: 'plane', planeId: 'wall_plane_2' }, 'PS-6010', twoWalls),
    ).toEqual({ wall_plane_1: 'PS-1001', wall_plane_2: 'PS-6010' });
  });
});

describe('renderPayload', () => {
  it('sends a bare Shade Code when every wall carries the same one', () => {
    expect(renderPayload({ wall_plane_1: 'PS-1001', wall_plane_2: 'PS-1001' }, twoWalls)).toBe(
      'PS-1001',
    );
  });

  it('sends a map when the walls differ', () => {
    expect(renderPayload({ wall_plane_1: 'PS-1001', wall_plane_2: 'PS-6010' }, twoWalls)).toEqual({
      wall_plane_1: 'PS-1001',
      wall_plane_2: 'PS-6010',
    });
  });

  it('never collapses a single targeted wall into "paint every plane" — the Accent Wall regression', () => {
    // A room with two planes; only one has a Shade so far (the Dealer targeted it deliberately).
    // A one-entry map trivially "agrees with itself", which used to be read as "every wall wants
    // this Shade" and sent a bare Shade Code — painting the *other* wall too, though nothing was
    // ever asked to give it a colour.
    expect(renderPayload({ wall_plane_2: 'PS-6010' }, twoWalls)).toEqual({
      wall_plane_2: 'PS-6010',
    });
  });

  it('names only the walls a Shade was chosen for, so the rest stay as photographed', () => {
    const threeWalls = [...twoWalls, planeAt('wall_plane_3')];
    expect(renderPayload({ wall_plane_1: 'PS-1001', wall_plane_3: 'PS-6010' }, threeWalls)).toEqual(
      {
        wall_plane_1: 'PS-1001',
        wall_plane_3: 'PS-6010',
      },
    );
  });

  it('sends an empty map with nothing assigned yet', () => {
    expect(renderPayload({}, twoWalls)).toEqual({});
  });
});

describe('describeWall', () => {
  it('points at a wall the way somebody in the room would', () => {
    expect(describeWall(0, 1)).toBe('the wall');
    expect(describeWall(0, 2)).toBe('the left wall');
    expect(describeWall(1, 2)).toBe('the right wall');
    expect(describeWall(1, 3)).toBe('the middle wall');
    expect(describeWall(3, 4)).toBe('wall 4');
  });
});

describe('describeTarget', () => {
  it('says nothing when there is only one wall to paint', () => {
    expect(describeTarget(ALL_WALLS, [planeAt('wall_plane_1')])).toBe('');
  });

  it('offers the choice when there are two, and names the chosen wall', () => {
    expect(describeTarget(ALL_WALLS, twoWalls)).toContain('every wall');
    expect(describeTarget({ kind: 'plane', planeId: 'wall_plane_2' }, twoWalls)).toContain(
      'the right wall',
    );
  });

  it('says nothing about a wall the photo no longer has', () => {
    expect(describeTarget({ kind: 'plane', planeId: 'wall_plane_9' }, twoWalls)).toBe('');
  });
});

describe('isTargeted', () => {
  it('is true only for the selected wall', () => {
    expect(isTargeted(ALL_WALLS, 'wall_plane_1')).toBe(false);
    expect(isTargeted({ kind: 'plane', planeId: 'wall_plane_1' }, 'wall_plane_1')).toBe(true);
    expect(isTargeted({ kind: 'plane', planeId: 'wall_plane_1' }, 'wall_plane_2')).toBe(false);
  });
});
