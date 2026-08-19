import { Button } from '../components/Button';
import { ErrorState } from '../components/ErrorState';
import { ProgressMessage } from '../components/ProgressMessage';
import { ShadeList } from './ShadeList';
import { ShadeSwatch } from './ShadeSwatch';
import type { Catalogue } from './useCatalogue';

/**
 * The Catalogue panel: search, Shade Family browsing, and the recently-used row.
 *
 * A panel inside Consultation, not a screen of its own (docs/specs/v1-spectrapaint.md) — the Dealer
 * is choosing a Shade *for the room on screen*, and sending them somewhere else to do it loses the
 * photo they are choosing against.
 *
 * Every state is defined, not just the happy path: loading, loaded, nothing typed, nothing found,
 * and a failure that always offers the next action.
 */
export function CataloguePanel({ catalogue }: { catalogue: Catalogue }) {
  const {
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
    recentShades,
    selectedShadeCode,
    select,
    retry,
  } = catalogue;

  if (phase === 'loading') {
    return (
      <aside className="catalogue">
        <ProgressMessage>Fetching the Shade Catalogue…</ProgressMessage>
      </aside>
    );
  }

  if (phase === 'failed' || !metadata) {
    return (
      <aside className="catalogue">
        <ErrorState
          message={message ?? 'The Shade Catalogue could not be loaded.'}
          actionLabel="Try again"
          onAction={retry}
        />
      </aside>
    );
  }

  const searched = query.trim().length > 0;

  return (
    <aside className="catalogue" aria-label="Shade Catalogue">
      <div className="catalogue__header">
        <h2 className="catalogue__title">Shades</h2>
        {/* Which Catalogue is on screen. A Dealer serving two manufacturers needs to know before
            reading a code out to a Customer, and a saved Render records it either way. */}
        <p className="catalogue__source">
          {metadata.catalogue_name} · {metadata.shade_count} Shades · version {metadata.version}
        </p>
      </div>

      <div className="catalogue__search">
        <label className="catalogue__label" htmlFor="catalogue-search">
          Search by Shade Code or name
        </label>
        <input
          id="catalogue-search"
          className="catalogue__input"
          type="search"
          value={query}
          autoComplete="off"
          spellCheck={false}
          placeholder="AP-2140, or “linen”"
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {recentShades.length > 0 && !searched ? (
        <div className="catalogue__recent">
          <h3 className="catalogue__subtitle">Recently used</h3>
          <ul className="catalogue__recent-row">
            {recentShades.map((shade) => (
              <li key={shade.shade_code}>
                <ShadeSwatch
                  shade={shade}
                  selected={shade.shade_code === selectedShadeCode}
                  onSelect={select}
                />
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {!searched ? (
        <div className="catalogue__families">
          <h3 className="catalogue__subtitle">Browse by Shade Family</h3>
          <ul className="catalogue__family-row">
            <li>
              <Button
                className={`catalogue__family${shadeFamily === null ? ' catalogue__family--on' : ''}`}
                aria-pressed={shadeFamily === null}
                onClick={() => setShadeFamily(null)}
              >
                All ({metadata.shade_count})
              </Button>
            </li>
            {metadata.shade_families.map((family) => (
              <li key={family.shade_family}>
                <Button
                  className={`catalogue__family${
                    shadeFamily === family.shade_family ? ' catalogue__family--on' : ''
                  }`}
                  aria-pressed={shadeFamily === family.shade_family}
                  onClick={() => setShadeFamily(family.shade_family)}
                >
                  {family.shade_family} ({family.shade_count})
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {searched && searching && rowCount === 0 ? <ProgressMessage>Looking…</ProgressMessage> : null}

      {searched && !searching && rowCount === 0 ? (
        // Not a dead end: an empty result still leaves the Dealer somewhere to go.
        <div className="catalogue__empty">
          <p className="catalogue__empty-message">
            No Shade matches “{query.trim()}”. Check the code on the chip, or try part of the name.
          </p>
          <Button onClick={() => setQuery('')}>Browse the whole Catalogue</Button>
        </div>
      ) : null}

      {rowCount > 0 ? (
        <ShadeList
          rowCount={rowCount}
          shadeAt={shadeAt}
          onShowRows={showRows}
          onSelect={select}
          selectedShadeCode={selectedShadeCode}
          label={
            searched
              ? `Shades matching ${query.trim()}`
              : `Shades in ${shadeFamily ?? 'the whole Catalogue'}`
          }
        />
      ) : null}
    </aside>
  );
}
