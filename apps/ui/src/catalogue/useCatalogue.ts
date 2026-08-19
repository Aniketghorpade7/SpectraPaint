/**
 * The state behind the Catalogue panel.
 *
 * Server state is fetched from the contract rather than mirrored (docs/specs/v1-spectrapaint.md):
 * the service owns the Catalogue, and this holds only what the panel is currently showing — the page
 * window on screen, the current search, and the recently-used row, which is the one piece of state
 * the service does not have.
 *
 * Browsing is fetched a page at a time as the virtualised list scrolls into it, so opening the panel
 * costs one small request rather than a thousand Shades the Dealer will never scroll to.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  MAX_RECENT_SHADES,
  readRecentShades,
  withMostRecent,
  writeRecentShades,
} from './recentShades';
import type { CatalogueMetadata, Shade, ShadePage } from './shade';
import { pagesCovering } from './virtualise';

/**
 * Rows per request. Comfortably more than a screenful, so ordinary scrolling stays ahead of the
 * fetch, and well inside the service's ceiling of 500 (services/inference/spectrapaint/api).
 */
export const PAGE_SIZE = 200;

/**
 * How long the panel waits after a keystroke before searching.
 *
 * A Dealer types a Shade Code in one burst while the Customer reads it out. Searching every
 * keystroke would send seven requests to answer the last one; waiting much longer than this makes
 * the panel feel like it is thinking.
 */
export const SEARCH_DEBOUNCE_MS = 150;

/** Search returns a ranked shortlist, not a page — beyond this the ranking has failed, not the cap. */
const SEARCH_LIMIT = 50;

export type CataloguePhase = 'loading' | 'ready' | 'failed';

export interface Catalogue {
  phase: CataloguePhase;
  /** Plain language, safe to show as-is. Present when the phase is 'failed'. */
  message?: string;
  metadata?: CatalogueMetadata;

  query: string;
  setQuery: (query: string) => void;
  searching: boolean;

  shadeFamily: string | null;
  setShadeFamily: (shadeFamily: string | null) => void;

  /** How many rows the list has, whether searching or browsing. */
  rowCount: number;
  /** The Shade at a row, or undefined while its page is still being fetched. */
  shadeAt: (index: number) => Shade | undefined;
  /** Tell the Catalogue which rows are on screen, so their pages can be fetched. */
  showRows: (start: number, end: number) => void;

  recentShades: Shade[];
  selectedShadeCode?: string;
  select: (shade: Shade) => void;

  retry: () => void;
}

interface ServiceFailure {
  code?: string;
  message?: string;
}

async function get<T>(path: string): Promise<T> {
  const response = await window.spectrapaint.request<T | ServiceFailure>({ path });

  if (!response.ok) {
    const failure = response.body as ServiceFailure | null;
    throw new Error(failure?.message ?? 'SpectraPaint could not reach its own service.');
  }

  return response.body as T;
}

function shadesPath(parameters: Record<string, string>): string {
  return `/catalogue/shades?${new URLSearchParams(parameters).toString()}`;
}

export function useCatalogue(): Catalogue {
  const [phase, setPhase] = useState<CataloguePhase>('loading');
  const [message, setMessage] = useState<string>();
  const [metadata, setMetadata] = useState<CatalogueMetadata>();

  const [query, setQueryState] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<Shade[] | null>(null);

  const [shadeFamily, setShadeFamilyState] = useState<string | null>(null);
  const [pages, setPages] = useState<Record<number, Shade[]>>({});

  const [recentShades, setRecentShades] = useState<Shade[]>([]);
  const [selectedShadeCode, setSelectedShadeCode] = useState<string>();

  // Which pages have been asked for. A ref, not state: it must be true the moment a request goes
  // out, and a state update lands a render too late to stop the same page being fetched twice.
  const requestedPages = useRef(new Set<number>());
  const [reloads, setReloads] = useState(0);

  // Loading the Catalogue happens once, and again when the Dealer retries. The work is done inside
  // the effect rather than in a callback it calls, so the first thing that happens is the await —
  // nothing sets state synchronously while React is rendering.
  useEffect(() => {
    let abandoned = false;

    void (async () => {
      try {
        const loaded = await get<CatalogueMetadata>('/catalogue');
        if (abandoned) return;
        setMetadata(loaded);
        setRecentShades(readRecentShades(loaded.catalogue_id));
        setPhase('ready');
      } catch (error) {
        console.error('[catalogue] could not load the Catalogue:', error);
        if (abandoned) return;
        setMessage(
          error instanceof Error && error.message
            ? error.message
            : 'The Shade Catalogue could not be loaded.',
        );
        setPhase('failed');
      }
    })();

    return () => {
      abandoned = true;
    };
  }, [reloads]);

  // Derived, not stored: the family counts came with the metadata, so keeping a copy in state would
  // be a second answer to a question already answered.
  const browseTotal = useMemo(() => {
    if (!metadata) return 0;
    if (shadeFamily === null) return metadata.shade_count;
    return (
      metadata.shade_families.find((family) => family.shade_family === shadeFamily)?.shade_count ??
      0
    );
  }, [metadata, shadeFamily]);

  // -- searching ------------------------------------------------------------------------------

  // Searching is driven by the Dealer typing, so it hangs off the change rather than off a render.
  // The token is what makes a slow reply from an earlier keystroke unable to overwrite a later one.
  const searchTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const latestSearch = useRef(0);

  const setQuery = useCallback((typed: string) => {
    setQueryState(typed);
    clearTimeout(searchTimer.current);

    const wanted = typed.trim();
    const token = (latestSearch.current += 1);

    if (!wanted) {
      setResults(null);
      setSearching(false);
      return;
    }

    setSearching(true);
    searchTimer.current = setTimeout(() => {
      void (async () => {
        try {
          const page = await get<ShadePage>(shadesPath({ q: wanted, limit: String(SEARCH_LIMIT) }));
          if (token === latestSearch.current) setResults(page.shades);
        } catch (error) {
          // A failed search must not clear the panel: the Dealer keeps what they had and can type
          // again. Logged, because a search that never works is a fault, not an inconvenience.
          console.error('[catalogue] could not search the Catalogue:', error);
          if (token === latestSearch.current) setResults([]);
        } finally {
          if (token === latestSearch.current) setSearching(false);
        }
      })();
    }, SEARCH_DEBOUNCE_MS);
  }, []);

  useEffect(() => () => clearTimeout(searchTimer.current), []);

  // -- browsing -------------------------------------------------------------------------------

  const fetchPage = useCallback(
    async (page: number) => {
      const parameters: Record<string, string> = {
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
      };
      if (shadeFamily !== null) parameters.shade_family = shadeFamily;

      try {
        const fetched = await get<ShadePage>(shadesPath(parameters));
        setPages((existing) => ({ ...existing, [page]: fetched.shades }));
      } catch (error) {
        // Let it be asked for again: a page that failed once should retry when it scrolls back into
        // view, rather than leaving a permanent hole in the list.
        requestedPages.current.delete(page);
        console.error('[catalogue] could not load a page of Shades:', error);
      }
    },
    [shadeFamily],
  );

  const showRows = useCallback(
    (start: number, end: number) => {
      if (results !== null) return; // a search is already in hand; nothing to page

      for (const page of pagesCovering(start, end, PAGE_SIZE)) {
        if (requestedPages.current.has(page)) continue;
        requestedPages.current.add(page);
        void fetchPage(page);
      }
    },
    [fetchPage, results],
  );

  const shadeAt = useCallback(
    (index: number): Shade | undefined => {
      if (results !== null) return results[index];

      const page = pages[Math.floor(index / PAGE_SIZE)];
      return page?.[index % PAGE_SIZE];
    },
    [pages, results],
  );

  // -- what the Dealer picked -------------------------------------------------------------------

  const select = useCallback(
    (shade: Shade) => {
      setSelectedShadeCode(shade.shade_code);
      setRecentShades((existing) => {
        const updated = withMostRecent(existing, shade);
        if (metadata) writeRecentShades(metadata.catalogue_id, updated);
        return updated;
      });
    },
    [metadata],
  );

  const setShadeFamily = useCallback(
    (family: string | null) => {
      // Browsing a family and searching are two ways of narrowing the same list; doing both at once
      // would leave the Dealer looking at results the family buttons do not explain.
      setQuery('');

      // Every fetched page belonged to the old family: row 40 is a different Shade now.
      requestedPages.current = new Set();
      setPages({});
      setShadeFamilyState(family);
    },
    [setQuery],
  );

  const retry = useCallback(() => {
    requestedPages.current = new Set();
    setPages({});
    setPhase('loading');
    setReloads((count) => count + 1);
  }, []);

  const rowCount = results !== null ? results.length : browseTotal;

  return useMemo(
    () => ({
      phase,
      message,
      metadata,
      query,
      setQuery,
      searching,
      shadeFamily,
      setShadeFamily,
      rowCount,
      shadeAt,
      showRows,
      recentShades: recentShades.slice(0, MAX_RECENT_SHADES),
      selectedShadeCode,
      select,
      retry,
    }),
    [
      phase,
      message,
      metadata,
      query,
      searching,
      shadeFamily,
      setShadeFamily,
      rowCount,
      shadeAt,
      showRows,
      recentShades,
      selectedShadeCode,
      select,
      setQuery,
      retry,
    ],
  );
}
