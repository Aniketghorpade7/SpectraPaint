/**
 * The photo the Dealer picked, turned into what the service and the renderer each need.
 *
 * Pure functions, kept free of Electron and Node imports so a silent regression in them is cheap to
 * test — see docs/design-decisions.md §9d. The dialog, the file read and the upload live in
 * create-consultation.ts.
 */

export const PHOTO_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp'] as const;

const EXTENSION_TO_MIME: Record<(typeof PHOTO_EXTENSIONS)[number], string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
};

/** The MIME type the service and the renderer both need to interpret the bytes. */
export function photoMimeFor(extension: string): string {
  return (
    EXTENSION_TO_MIME[extension.toLowerCase() as (typeof PHOTO_EXTENSIONS)[number]] ?? 'image/jpeg'
  );
}

/** A base64 data URL, so the renderer can show the photo without any filesystem access. */
export function photoDataUrl(bytes: Uint8Array, mime: string): string {
  return `data:${mime};base64,${Buffer.from(bytes).toString('base64')}`;
}
