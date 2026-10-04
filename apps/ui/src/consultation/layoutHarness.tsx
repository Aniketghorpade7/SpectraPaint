import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';

import type {
  SpectraPaintBridge,
  WallPlaneOverlay,
  WallsResult,
} from '../../../desktop/src/bridge-types';
import '../tokens.css';
import '../components/components.css';
import './consultation.css';
import '../catalogue/catalogue.css';
import { ConsultationSurface } from './ConsultationSurface';
import { useConsultation, type Consultation } from './useConsultation';

/**
 * The page layout.test.ts drives in a real browser (issue #49).
 *
 * The real `ConsultationSurface` and the real `useConsultation` over a scripted bridge, so what is
 * measured is the shipped CSS and the shipped swap from the raw upload to the prepared photo — not
 * a copy of either. Nothing here is shipped: Vite's build only bundles `index.html`.
 *
 * Query parameters choose the case:
 * - `ratio` — the prepared photo's width / height (default 1.33).
 * - `placeholder` — the raw upload's ratio, when it differs: an EXIF-rotated phone photo shows
 *   landscape until the prepared, portrait photo replaces it.
 * - `failPrepared` — the prepared photo cannot be fetched.
 *
 * `window.__live` is the hook's current return value, re-read on every render, so a test reads it
 * fresh each time (a copy taken earlier answers a question that has already changed).
 */

declare global {
  interface Window {
    __live: Consultation;
  }
}

const SESSION_ID = 'a'.repeat(32);
const PHOTO_HEIGHT = 400;

const query = new URLSearchParams(window.location.search);
const preparedRatio = Number(query.get('ratio') ?? '1.33');
const placeholderRatio = Number(query.get('placeholder') ?? preparedRatio);
const preparedPhotoFails = query.has('failPrepared');

function canvasOf(ratio: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(PHOTO_HEIGHT * ratio);
  canvas.height = PHOTO_HEIGHT;
  return canvas;
}

/** A recognisable photo: a warm gradient, so a clipped or stretched frame shows in the pixels. */
function photoOf(ratio: number, tint: string): string {
  const canvas = canvasOf(ratio);
  const context = canvas.getContext('2d');
  if (!context) throw new Error('no 2d context');
  const gradient = context.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, tint);
  gradient.addColorStop(1, '#d8cbb8');
  context.fillStyle = gradient;
  context.fillRect(0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/png');
}

/** A greyscale Alpha Matte, as the service serves it: coverage in the grey level, alpha opaque. */
function matteOf(ratio: number, side: 'left' | 'right'): string {
  const canvas = canvasOf(ratio);
  const context = canvas.getContext('2d');
  if (!context) throw new Error('no 2d context');
  context.fillStyle = '#000';
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = '#fff';
  const half = canvas.width / 2;
  context.fillRect(side === 'left' ? 0 : half, 0, half, canvas.height);
  return canvas.toDataURL('image/png');
}

function wallsFor(ratio: number): WallsResult {
  const width = Math.round(PHOTO_HEIGHT * ratio);
  const plane = (planeId: string, side: 'left' | 'right'): WallPlaneOverlay => ({
    planeId,
    surface: 'wall',
    coverage: 0.5,
    photoWidth: width,
    photoHeight: PHOTO_HEIGHT,
    bounds:
      side === 'left'
        ? { left: 0, top: 0, right: width / 2, bottom: PHOTO_HEIGHT }
        : { left: width / 2, top: 0, right: width, bottom: PHOTO_HEIGHT },
    matteDataUrl: matteOf(ratio, side),
  });
  return {
    status: 'ready',
    planes: [plane('wall_plane_1', 'left'), plane('wall_plane_2', 'right')],
    note: null,
    qualityNote: null,
    photoWidth: width,
    photoHeight: PHOTO_HEIGHT,
  };
}

const later = (milliseconds: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, milliseconds));

// The methods the Consultation reaches. Anything else is a bridge call this harness does not
// script, and must fail loudly rather than answer something plausible.
const bridge: Partial<SpectraPaintBridge> = {
  // The Catalogue panel's own requests: an empty Catalogue, which leaves the panel in its normal
  // ready state at its normal width. The layout under test is the stage's.
  request: <T,>(request: { path: string }) =>
    Promise.resolve({
      status: 200,
      ok: true,
      body: (request.path.startsWith('/catalogue/shades')
        ? { shades: [], total: 0, limit: 200, offset: 0, searched: false }
        : {
            catalogue_id: 'layout-harness',
            catalogue_name: 'Layout harness',
            version: '0',
            shade_count: 0,
            shade_families: [],
          }) as T,
    }),
  createConsultation: () =>
    Promise.resolve({
      status: 'ready',
      sessionId: SESSION_ID,
      imageDataUrl: photoOf(placeholderRatio, '#7a8a9a'),
    }),
  onProgress: (_sessionId, listener) => {
    setTimeout(() => listener({ phase: 'done' }), 0);
    return () => undefined;
  },
  preparedPhoto: async () => {
    // Slow enough that the placeholder is genuinely on screen first.
    await later(150);
    return preparedPhotoFails
      ? { status: 'failed', code: 'service_error', message: 'offline' }
      : { status: 'ready', imageDataUrl: photoOf(preparedRatio, '#9a8a7a') };
  },
  walls: () => Promise.resolve(wallsFor(preparedRatio)),
  correctWalls: () => Promise.resolve(wallsFor(preparedRatio)),
  render: () =>
    Promise.resolve({
      status: 'ready',
      imageDataUrl: photoOf(preparedRatio, '#5a7a5a'),
      executionProfile: 'cpu-faster',
    }),
};

window.spectrapaint = new Proxy(bridge, {
  get(target, property: string) {
    const method = (target as Record<string, unknown>)[property];
    if (method === undefined) throw new Error(`layout harness: bridge.${property} is not scripted`);
    return method;
  },
}) as SpectraPaintBridge;

function Harness() {
  const consultation = useConsultation();
  // Re-read by the test on every call, so it is set after each render rather than during one.
  useEffect(() => {
    window.__live = consultation;
  });
  return <ConsultationSurface consultation={consultation} />;
}

const container = document.getElementById('root');
if (!container) throw new Error('Root element missing from layout-harness.html');
createRoot(container).render(<Harness />);
