import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RenderResult } from './bridge-types';
import { RENDER_CHANNEL } from './channels';
import { registerRenderBridge } from './render-bridge';

// The module under test imports Electron's `ipcMain`; the handler wiring is the unit under test, so
// the whole runtime is faked. This is the shell logic neither seam reaches (docs/conventions.md §6):
// the render contract itself is exercised through Seam 1.
const handlers = vi.hoisted(() => ({ render: undefined as unknown }));

vi.mock('electron', () => ({
  ipcMain: {
    handle: (channel: string, handler: unknown) => {
      if (channel === RENDER_CHANNEL) handlers.render = handler;
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

function invokeRender(
  sender: FakeSender,
  sessionId: unknown,
  shadeCode: unknown,
  mode: unknown = undefined,
): Promise<RenderResult> {
  const handler = handlers.render as (
    event: { sender: FakeSender },
    sessionId: unknown,
    shadeCode: unknown,
    mode: unknown,
  ) => Promise<RenderResult>;
  return mode === undefined ? handler({ sender }, sessionId, shadeCode) : handler({ sender }, sessionId, shadeCode, mode);
}

function mockPlanesThenRender(planeIds: string[] = ['wall_plane_1']) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.includes('/planes') && (!init || init.method === undefined || init.method === 'GET')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ planes: planeIds.map((id) => ({ plane_id: id })) }),
      } as unknown as Response;
    }
    // renders POST
    return {
      ok: true,
      status: 201,
      arrayBuffer: async () => new Uint8Array([137, 80, 78, 71]).buffer,
    } as unknown as Response;
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  // Trust every sender by default; the untrusted case re-registers with a real check.
  registerRenderBridge(
    () => SIDECAR,
    () => true,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('registerRenderBridge', () => {
  it('refuses an untrusted sender, without touching the service', async () => {
    registerRenderBridge(
      () => SIDECAR,
      () => false,
    );

    const result = await invokeRender({ destroyed: false }, VALID_SESSION_ID, 'AP-2140');

    expect(result).toEqual({ status: 'failed', code: 'unauthorised', message: expect.any(String) });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses a session id that fails the pattern, never reaching a path', async () => {
    const result = await invokeRender({ destroyed: false }, '../../etc/passwd', 'AP-2140');

    expect(result).toEqual({
      status: 'failed',
      code: 'malformed_request',
      message: expect.any(String),
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses an empty Shade Code', async () => {
    const result = await invokeRender({ destroyed: false }, VALID_SESSION_ID, '');

    expect(result).toEqual({
      status: 'failed',
      code: 'malformed_request',
      message: expect.any(String),
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses when there is no sidecar to render through', async () => {
    registerRenderBridge(
      () => null,
      () => true,
    );

    const result = await invokeRender({ destroyed: false }, VALID_SESSION_ID, 'AP-2140');

    expect(result).toEqual({
      status: 'failed',
      code: 'service_unavailable',
      message: expect.any(String),
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('POSTs the assignment to the session and returns the repaint as a data URL', async () => {
    mockPlanesThenRender(['wall_plane_1']);

    const result = await invokeRender({ destroyed: false }, VALID_SESSION_ID, 'AP-2140');

    expect(result).toEqual({
      status: 'ready',
      imageDataUrl: 'data:image/png;base64,iVBORw==',
    });

    // First call is planes, second is renders
    const renderCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/renders')) as [string, RequestInit];
    const [url, init] = renderCall;
    expect(url).toBe(`http://127.0.0.1:1/sessions/${VALID_SESSION_ID}/renders`);
    expect(init.method).toBe('POST');
    expect(init.headers).toMatchObject({ Authorization: 'Bearer test-secret' });
    expect(JSON.parse(init.body as string)).toEqual({
      assignments: { wall_plane_1: 'AP-2140' },
      mode: 'realistic',
    });
  });

  it('paints every plane when a single Shade Code is given', async () => {
    mockPlanesThenRender(['wall_plane_1', 'wall_plane_2']);

    const result = await invokeRender({ destroyed: false }, VALID_SESSION_ID, 'AP-2140');

    expect(result.status).toBe('ready');
    const renderCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/renders')) as [string, RequestInit];
    expect(JSON.parse((renderCall[1].body as string)).assignments).toEqual({
      wall_plane_1: 'AP-2140',
      wall_plane_2: 'AP-2140',
    });
  });

  it('posts a per-plane map for an Accent Wall', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 201,
      arrayBuffer: async () => new Uint8Array([137, 80, 78, 71]).buffer,
    } as unknown as Response);

    const assignments = { wall_plane_1: 'PS-1001', wall_plane_2: 'PS-2001' };
    const result = await invokeRender({ destroyed: false }, VALID_SESSION_ID, assignments);

    expect(result.status).toBe('ready');
    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({ assignments, mode: 'realistic' });
  });

  it('returns the service error body as-is so the UI can show it', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      const u = String(url);
      if (u.includes('/planes')) {
        return { ok: true, status: 200, json: async () => ({ planes: [{ plane_id: 'wall_plane_1' }] }) } as unknown as Response;
      }
      return {
        ok: false,
        status: 404,
        json: async () => ({
          code: 'shade_not_found',
          message: 'That Shade Code is not in this Catalogue. Please check the code on the chip.',
        }),
      } as unknown as Response;
    });

    const result = await invokeRender({ destroyed: false }, VALID_SESSION_ID, 'NOPE-0000');

    expect(result).toEqual({
      status: 'failed',
      code: 'shade_not_found',
      message: 'That Shade Code is not in this Catalogue. Please check the code on the chip.',
    });
  });

  it('turns an unparseable error body into a generic failure, never a dead end', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).includes('/planes')) {
        return { ok: true, status: 200, json: async () => ({ planes: [{ plane_id: 'wall_plane_1' }] }) } as unknown as Response;
      }
      return { ok: false, status: 500, json: async () => null } as unknown as Response;
    });

    const result = await invokeRender({ destroyed: false }, VALID_SESSION_ID, 'AP-2140');

    expect(result).toEqual({
      status: 'failed',
      code: 'render_failed',
      message: expect.any(String),
    });
  });

  it('a network failure returns a service_unavailable result, not a hanging promise', async () => {
    fetchMock.mockRejectedValue(new Error('connection refused'));

    const result = await invokeRender({ destroyed: false }, VALID_SESSION_ID, 'AP-2140');

    expect(result).toEqual({
      status: 'failed',
      code: 'service_unavailable',
      message: expect.any(String),
    });
  });
});
