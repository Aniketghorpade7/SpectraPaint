import { describe, expect, it } from 'vitest';

import { photoDataUrl, photoMimeFor } from './photo-upload';

/**
 * Pure shell logic (docs/design-decisions.md §9d): a wrong MIME type would make the service or the
 * renderer misread the photo, and a wrong data URL would show nothing at all.
 */
describe('photo helpers', () => {
  it('maps the extensions the dialog offers to the MIME the service expects', () => {
    expect(photoMimeFor('jpg')).toBe('image/jpeg');
    expect(photoMimeFor('jpeg')).toBe('image/jpeg');
    expect(photoMimeFor('png')).toBe('image/png');
    expect(photoMimeFor('webp')).toBe('image/webp');
  });

  it('is case-insensitive, since the filesystem is', () => {
    expect(photoMimeFor('PNG')).toBe('image/png');
  });

  it('builds a data URL the renderer can put in an <img> without touching the filesystem', () => {
    expect(photoDataUrl(new Uint8Array([1, 2, 3]), 'image/png')).toBe('data:image/png;base64,AQID');
  });
});
