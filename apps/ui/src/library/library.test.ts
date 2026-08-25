import { describe, expect, it } from 'vitest';

import { shadesOf } from './types';
import type { RenderRecord } from './types';

function render(assignments: Record<string, string>): RenderRecord {
  return {
    render_id: 'r1',
    created_at: new Date().toISOString(),
    execution_profile: 'preview',
    mode: 'realistic',
    assignments,
    resolved_lab: {},
    catalogue_id: 'c1',
    catalogue_name: 'Test',
    catalogue_version: '1',
    width: 100,
    height: 100,
  };
}

describe('shadesOf', () => {
  it('returns each shade once in plane order', () => {
    const r = render({ p1: 'AP-100', p2: 'AP-200', p3: 'AP-100' });
    expect(shadesOf(r)).toEqual(['AP-100', 'AP-200']);
  });

  it('returns empty for no assignments', () => {
    expect(shadesOf(render({}))).toEqual([]);
  });

  it('deduplicates via Set insertion order', () => {
    const r = render({ a: 'X-1', b: 'X-2', c: 'X-1', d: 'X-3', e: 'X-2' });
    expect(shadesOf(r)).toEqual(['X-1', 'X-2', 'X-3']);
  });
});
