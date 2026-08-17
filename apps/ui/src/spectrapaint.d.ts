/**
 * `window.spectrapaint` — the entire surface the renderer can see.
 *
 * The type is imported from the desktop package rather than restated here, so the bridge cannot
 * drift out of step with the preload script that implements it. Type-only, so nothing is bundled
 * and the two packages stay independent at runtime.
 */
import type { SpectraPaintBridge } from '../../desktop/src/bridge-types';

declare global {
  interface Window {
    spectrapaint: SpectraPaintBridge;
  }
}

export {};
