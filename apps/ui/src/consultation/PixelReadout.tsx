import { useCallback, useEffect, useRef, useState, type PointerEvent, type RefObject } from 'react';

import { pointerToSourcePixel, rgbToApproxCmyk, tooltipPlacement, type Rgb } from './pixelColour';

/** One sample: the colour under the cursor, and where the cursor is within the frame. */
export interface Reading {
  /** The image it was read from, so a reading never outlives a swap between photo and repaint. */
  src: string;
  rgb: Rgb;
  x: number;
  y: number;
  frameWidth: number;
  frameHeight: number;
}

interface Sampler {
  src: string;
  ctx: CanvasRenderingContext2D;
  width: number;
  height: number;
}

/**
 * The Pixel Readout's behaviour (issue #58): while `active`, follow the cursor over the frame and
 * read the one source pixel under it from the image on screen.
 *
 * The image is drawn once into an offscreen canvas at its natural size — only while the readout is
 * on, since a large photo is not worth decoding for a mode that is off — and redrawn only when `src`
 * changes, so a move costs one `getImageData`, not a decode. Both images are data URLs, so the
 * canvas is never tainted; if it somehow is, the readout simply shows nothing.
 *
 * The pointer is read from the frame and the pixel from the image's own box, so the overlays above
 * the photo (wash, outline, chips) never get in the way: they are `pointer-events: none` or bubble
 * up to the frame.
 */
export function usePixelReadout(
  src: string,
  active: boolean,
  imageRef: RefObject<HTMLImageElement | null>,
) {
  const [reading, setReading] = useState<Reading | null>(null);
  const samplerRef = useRef<Sampler | null>(null);
  const frameRequest = useRef<number | null>(null);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const image = new Image();
    image.onload = () => {
      if (cancelled || image.naturalWidth <= 0 || image.naturalHeight <= 0) return;
      const canvas = document.createElement('canvas');
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      if (!ctx) return;
      ctx.drawImage(image, 0, 0);
      samplerRef.current = { src, ctx, width: canvas.width, height: canvas.height };
    };
    image.src = src;
    return () => {
      cancelled = true;
      samplerRef.current = null;
      if (frameRequest.current !== null) cancelAnimationFrame(frameRequest.current);
      frameRequest.current = null;
    };
  }, [src, active]);

  const onPointerMove = useCallback(
    (event: PointerEvent<HTMLElement>) => {
      const frame = event.currentTarget;
      const { clientX, clientY } = event;
      // One read per animation frame, however fast the pointer reports.
      if (frameRequest.current !== null) cancelAnimationFrame(frameRequest.current);
      frameRequest.current = requestAnimationFrame(() => {
        frameRequest.current = null;
        const sampler = samplerRef.current;
        const image = imageRef.current;
        if (!sampler || sampler.src !== src || !image) return setReading(null);
        const box = image.getBoundingClientRect();
        const pixel = pointerToSourcePixel(clientX, clientY, box, sampler.width, sampler.height);
        if (!pixel) return setReading(null);
        let data: Uint8ClampedArray;
        try {
          data = sampler.ctx.getImageData(pixel.x, pixel.y, 1, 1).data;
        } catch {
          return setReading(null);
        }
        const frameBox = frame.getBoundingClientRect();
        setReading({
          src,
          rgb: { r: data[0] ?? 0, g: data[1] ?? 0, b: data[2] ?? 0 },
          x: clientX - frameBox.left,
          y: clientY - frameBox.top,
          frameWidth: frameBox.width,
          frameHeight: frameBox.height,
        });
      });
    },
    [src, imageRef],
  );

  const onPointerLeave = useCallback(() => {
    if (frameRequest.current !== null) cancelAnimationFrame(frameRequest.current);
    frameRequest.current = null;
    setReading(null);
  }, []);

  return {
    reading: active && reading !== null && reading.src === src ? reading : null,
    onPointerMove: active ? onPointerMove : undefined,
    onPointerLeave: active ? onPointerLeave : undefined,
  };
}

/**
 * The tooltip: a swatch of the pixel's colour, its RGB, and its approximate CMYK.
 *
 * It reads the simulated image, never a Shade — so it carries no Shade Code and says "approx." —
 * the Fandeck is what settles real colour (CONTEXT.md). `pointer-events: none` so it can never take
 * the hover from the pixel it describes, and `aria-hidden` because it follows a pointer: announcing
 * every move would drown a screen reader.
 */
export function PixelTooltip({ reading }: { reading: Reading }) {
  const { rgb } = reading;
  const cmyk = rgbToApproxCmyk(rgb);
  const { left, top } = tooltipPlacement(
    reading.x,
    reading.y,
    reading.frameWidth,
    reading.frameHeight,
  );
  return (
    <div className="pixel-tooltip" style={{ left, top }} aria-hidden="true">
      <span
        className="pixel-tooltip__swatch"
        style={{ background: `rgb(${rgb.r} ${rgb.g} ${rgb.b})` }}
      />
      <span className="pixel-tooltip__values">
        <span>
          RGB {rgb.r}, {rgb.g}, {rgb.b}
        </span>
        <span>
          CMYK {cmyk.c}, {cmyk.m}, {cmyk.y}, {cmyk.k} (approx.)
        </span>
      </span>
    </div>
  );
}
