import { useEffect, useRef } from 'react';

import { matteOutline } from './walls';

/**
 * The chosen wall's outline, drawn along its Alpha Matte's own edge (issue #49).
 *
 * Selection used to be a 45% white wash over the chosen wall — which made the one wall the
 * Customer is about to judge paler than the others. The outline shows which wall the next Shade
 * will land on without touching its colour: a 2 px `--grey-6` line with a 1 px `--grey-0` halo, so
 * it reads on both light and dark walls (the halo is what keeps a light line visible on a light
 * wall). Both colours come from the token set at draw time — this is canvas pixel data, where CSS
 * custom properties do not reach, but the values must still live in tokens.css with the rest of the
 * greys (ui-guidelines.md).
 *
 * The ring itself is the pure `matteOutline` (walls.ts), so its geometry is unit-tested. This
 * component only moves pixels between spaces: the matte arrives as a PNG at the photo's own scale,
 * the line must be 2 px *on screen*, so the matte is drawn into a backing store the size of the
 * frame and the outline is computed there — once per (matte, frame size), re-measured by a
 * `ResizeObserver`, since the frame resizes with the window. Out of that flow come two rules the
 * CSS cannot express: the canvas is `pointer-events: none` (it sits over the photo and, while a
 * tool is armed, over the tap layer — taps meant for either must pass to them), and it draws
 * nothing at all when its box has no area yet, rather than sizing to a default.
 */

/** The line and its halo, in on-screen pixels (ui-guidelines.md tokens are px-based). */
const OUTLINE_WIDTH_PX = 2;
const HALO_WIDTH_PX = 1;

export function WallOutlineCanvas({ matteDataUrl }: { matteDataUrl: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // The decoded matte, at the photo's own scale. Loaded once per matte; redrawn against it whenever
  // the frame's size changes.
  const matteRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;

    const image = new Image();
    image.src = matteDataUrl;
    image
      .decode()
      .then(() => {
        if (disposed) return;
        matteRef.current = image;
        draw(canvas, image);
      })
      .catch((error: unknown) => {
        // A matte PNG that will not decode leaves the choice unmarked but the consultation alive —
        // the chip still names the chosen wall, and the next Shade still lands on it.
        console.error('[consultation] could not draw the wall outline:', error);
      });

    // The frame — and so this canvas — resizes with the window. Re-measuring rather than scaling a
    // cached outline is what keeps the line 2 px at every size.
    const observer = new ResizeObserver(() => {
      const matte = matteRef.current;
      if (matte && !disposed) draw(canvas, matte);
    });
    observer.observe(canvas);

    return () => {
      disposed = true;
      observer.disconnect();
    };
  }, [matteDataUrl]);

  return <canvas ref={canvasRef} className="consultation__wall-outline" aria-hidden="true" />;
}

/** Draw the outline for one (matte, frame size) pair. Never runs on a zero-area canvas. */
function draw(canvas: HTMLCanvasElement, matte: HTMLImageElement): void {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (width < 1 || height < 1) return;
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) return;

  // The matte, scaled to the frame — the frame is the photo's box (consultation.css), so this is
  // the matte in the space the Dealer actually sees.
  context.clearRect(0, 0, width, height);
  context.drawImage(matte, 0, 0, width, height);
  const scaled = context.getImageData(0, 0, width, height);

  // The line at the requested width, and the halo one step wider underneath it: drawing the halo
  // first and the line over it leaves exactly HALO_WIDTH_PX of halo visible either side.
  const line = matteOutline(scaled, OUTLINE_WIDTH_PX);
  const halo = matteOutline(scaled, OUTLINE_WIDTH_PX + HALO_WIDTH_PX);

  const [lineGrey, haloGrey] = [
    readGrey(canvas, '--grey-6', 0xec),
    readGrey(canvas, '--grey-0', 0x1a),
  ];
  const composed = new Uint8ClampedArray(line.data);
  for (let i = 0; i < composed.length; i += 4) {
    if (composed[i + 3] === 0) {
      if (halo.data[i + 3] !== 0) {
        composed[i] = haloGrey;
        composed[i + 1] = haloGrey;
        composed[i + 2] = haloGrey;
        composed[i + 3] = 255;
      }
      continue;
    }
    composed[i] = lineGrey;
    composed[i + 1] = lineGrey;
    composed[i + 2] = lineGrey;
  }
  context.putImageData(new ImageData(composed, line.width, line.height), 0, 0);
}

/**
 * One grey channel value for the outline, read from the token set so the canvas matches the CSS
 * chrome without a second copy of the scale. Tokens are `#rrggbb`, so one read serves all three
 * channels; the fallback is only reached if the custom property is missing, and is neutral on
 * purpose.
 */
function readGrey(element: Element, token: string, fallbackChannel: number): number {
  const value = getComputedStyle(element).getPropertyValue(token).trim();
  const hex = /^#([0-9a-f]{6})$/i.exec(value)?.[1];
  if (hex === undefined) return fallbackChannel;
  const channels = parseInt(hex, 16);
  return (channels >> 8) & 0xff;
}
