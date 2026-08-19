/**
 * The Catalogue as the contract serves it.
 *
 * Field names are the service's, `snake_case` and unrenamed, so a Shade can be read across the whole
 * app without anyone having to remember which layer calls it what (docs/conventions.md §1 and §4).
 */

import type { Lab } from './colour';

export interface Shade {
  shade_code: string;
  name: string;
  shade_family: string;
  lab: Lab;
  /** Matte, satin, gloss. Metadata in V1: shown beside a Shade, never used in a render. */
  finishes: string[];
}

export interface ShadeFamilySummary {
  shade_family: string;
  shade_count: number;
}

/** `GET /catalogue` — which Catalogue is loaded, and what it can be browsed by. */
export interface CatalogueMetadata {
  catalogue_id: string;
  catalogue_name: string;
  version: string;
  shade_count: number;
  shade_families: ShadeFamilySummary[];
}

/** `GET /catalogue/shades` — a page of the Catalogue, or a ranked shortlist. */
export interface ShadePage {
  shades: Shade[];
  total: number;
  limit: number;
  offset: number;
  /** True when the service ranked a search rather than paging a browse. */
  searched: boolean;
}
