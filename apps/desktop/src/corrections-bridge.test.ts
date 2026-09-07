import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { WallsResult } from './bridge-types';
import { CORRECTIONS_CHANNEL } from './channels';
import { registerCorrectionsBridge } from './corrections-bridge';

// The module under test imports Electron's `ipcMain`; the handler wiring is the unit under test,
// so the whole runtime is faked — same model as render-bridge.test.ts. The correction contract
// itself is exercised through Seam 1 (tests/api/test_corrections.py).
const handlers = vi.hoisted(() => ({ correct: undefined as unknown }));

vi.mock('electron', () => ({
  ipcMain: {
    handle: (channel: string, handler: unknown) => {
      if (channel === CORRECTIONS_CHANNEL) handlers.correct = handler;
    },
  },
}));

const VALID_SESSION_ID = '0123456789abcdef0123456789abcdef';

const SIDECAR = {
  baseUrl: 'http://127.0.0.1:1',
  secret: 'test-secret',
  stop: async () => {},
};

interface FakeSender {
  destroyed: boolean;
}

function invokeCorrection(
  sender: FakeSender,
  sessionId: unknown,
  tool: unknown,
  point: unknown,
): Promise<WallsResult> {
  const handler = handlers.correct as (
    event: { sender: FakeSender },
    sessionId: unknown,
    tool: unknown,
    point: unknown,
  ) => Promise<WallsResult>;
  return handler({ sender }, sessionId, tool, point);
}

function mockPlanesResponse(planeIds: string[]) {
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).endsWith('/matte')) {
      return {
        ok: true,
        arrayBuffer: async () => new Uint8Array([137, 80, 78, 71]).buffer,
      } as unknown as Response;
    }
    return {
      ok: true,
      status: planeIds.length > 0 ? 201 : 200,
      json: async () => ({
        planes: planeIds.map((id) => ({
          plane_id: id,
          coverage: 0.5,
          bounds: null,
          photo_width: 640,
          photo_height: 480,
        })),
        note: null,
        photo_width: 640,
        photo_height: 480,
      }),
    } as unknown as Response;
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  registerCorrectionsBridge(
    () => SIDECAR,
    () => true,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('registerCorrectionsBridge', () => {
  it('refuses an untrusted sender, without touching the service', async () => {
    registerCorrectionsBridge(
      () => SIDECAR,
      () => false,
    );

    const result = await invokeCorrection({ destroyed: false }, VALID_SESSION_ID, 'add', {
      x: 1,
      y: 1,
    });

    expect(result).toEqual({ status: 'failed', code: 'unauthorised', message: expect.any(String) });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses a session id that fails the pattern', async () => {
    const result = await invokeCorrection({ destroyed: false }, '../../etc/passwd', 'add', {
      x: 1,
      y: 1,
    });

    expect(result).toEqual({
      status: 'failed',
      code: 'malformed_request',
      message: expect.any(String),
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses a tool that is not add, split or merge', async () => {
    const result = await invokeCorrection({ destroyed: false }, VALID_SESSION_ID, 'delete', {
      x: 1,
      y: 1,
    });

    expect(result).toEqual({
      status: 'failed',
      code: 'malformed_request',
      message: expect.any(String),
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ['missing y', { x: 1 }],
    ['a negative coordinate', { x: -1, y: 1 }],
    ['a fractional coordinate', { x: 1.5, y: 1 }],
    ['a string coordinate', { x: '1', y: 1 }],
    ['not an object at all', 'nope'],
    ['null', null],
  ])('refuses a point that is %s', async (_label, point) => {
    const result = await invokeCorrection({ destroyed: false }, VALID_SESSION_ID, 'add', point);

    expect(result).toEqual({
      status: 'failed',
      code: 'malformed_request',
      message: expect.any(String),
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses when there is no sidecar to correct through', async () => {
    registerCorrectionsBridge(
      () => null,
      () => true,
    );

    const result = await invokeCorrection({ destroyed: false }, VALID_SESSION_ID, 'add', {
      x: 1,
      y: 1,
    });

    expect(result).toEqual({
      status: 'failed',
      code: 'service_unavailable',
      message: expect.any(String),
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ['add', 'planes'],
    ['split', 'planes/split'],
    ['merge', 'planes/merge'],
  ])('POSTs %s to the right route with the tapped point', async (tool, route) => {
    mockPlanesResponse(['wall_plane_1']);

    await invokeCorrection({ destroyed: false }, VALID_SESSION_ID, tool, { x: 12, y: 34 });

    const call = fetchMock.mock.calls.find(([url]) => !String(url).endsWith('/matte')) as [
      string,
      RequestInit,
    ];
    const [url, init] = call;
    expect(url).toBe(`http://127.0.0.1:1/sessions/${VALID_SESSION_ID}/${route}`);
    expect(init.method).toBe('POST');
    expect(init.headers).toMatchObject({ Authorization: 'Bearer test-secret' });
    expect(JSON.parse(init.body as string)).toEqual({ x: 12, y: 34 });
  });

  it('resolves the updated planes into overlays with data URLs', async () => {
    mockPlanesResponse(['wall_plane_1', 'wall_plane_2']);

    const result = await invokeCorrection({ destroyed: false }, VALID_SESSION_ID, 'split', {
      x: 12,
      y: 34,
    });

    expect(result).toEqual({
      status: 'ready',
      note: null,
      photoWidth: 640,
      photoHeight: 480,
      planes: [
        expect.objectContaining({ planeId: 'wall_plane_1' }),
        expect.objectContaining({ planeId: 'wall_plane_2' }),
      ],
    });
  });

  it('passes through the service’s own refusal message, naming the right tool', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => ({
        code: 'malformed_request',
        message: "That's already part of a wall. To split it into two, use Split instead.",
      }),
    } as unknown as Response);

    const result = await invokeCorrection({ destroyed: false }, VALID_SESSION_ID, 'add', {
      x: 1,
      y: 1,
    });

    expect(result).toEqual({
      status: 'failed',
      code: 'malformed_request',
      message: "That's already part of a wall. To split it into two, use Split instead.",
    });
  });

  it('never dead-ends when the service cannot be reached at all', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));

    const result = await invokeCorrection({ destroyed: false }, VALID_SESSION_ID, 'merge', {
      x: 1,
      y: 1,
    });

    expect(result).toEqual({
      status: 'failed',
      code: 'service_unavailable',
      message: expect.any(String),
    });
  });
});
