/**
 * The shapes the library endpoints return (issue #11).
 *
 * Mirrors the service's JSON exactly — snake_case on the wire, because conventions.md §4 keeps
 * HTTP fields snake_case and this is where it is translated into what React draws.
 */

export interface BundleSummary {
  bundle_id: string;
  name: string;
  created_at: string;
  consultation_count: number;
  is_default: number;
}

export interface ConsultationSummary {
  consultation_id: string;
  created_at: string;
  render_count: number;
}

/** One saved repaint, with everything recorded about how it was made. */
export interface RenderRecord {
  render_id: string;
  created_at: string;
  execution_profile: string;
  mode: string;
  assignments: Record<string, string>;
  resolved_lab: Record<string, [number, number, number]>;
  catalogue_id: string;
  catalogue_name: string;
  catalogue_version: string;
  width: number;
  height: number;
}

/** The shade codes a render used, once each, in plane order. */
export function shadesOf(render: RenderRecord): string[] {
  return [...new Set(Object.values(render.assignments))];
}
