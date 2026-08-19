# ui — React renderer

Talks only to the inference service HTTP contract. Holds no Node or filesystem access.

Surfaces: Boot, Bundles, Consultation (with the Catalogue panel), Storage, Settings.

Requests a ~1 MP preview per Shade change while browsing; full resolution only on save or export.
See the latency evidence in [spikes/latency/RESULTS.md](../../spikes/latency/RESULTS.md).

---

## The Catalogue panel (`src/catalogue/`)

A panel inside Consultation, never a screen of its own: the Dealer is choosing a Shade **for the room
on screen**, and sending them elsewhere to do it loses the photo they are choosing against.

| | |
|---|---|
| `useCatalogue.ts` | Fetches from the contract and holds only what is on screen — the page window, the current search, and the recently-used row. Browsing is fetched a page at a time as the list scrolls into it. |
| `ShadeList.tsx` | The virtualised list. Fixed row height, a window of rows, and padding standing in for the rest so the scrollbar stays honest. `ROW_HEIGHT` and `--shade-row-height` must agree. |
| `ShadeSwatch.tsx` | One Shade. The **Shade Code is the loudest thing on it**, so the Dealer can pull the physical chip and confirm. |
| `colour.ts` | Lab to sRGB, pinned to D65 / 2° and the piecewise transfer function. Pure, and tested against reference values. |
| `virtualise.ts` | Which rows to draw and which pages to fetch. Pure, and tested. |
| `recentShades.ts` | The recently-used row, in `localStorage`, keyed by Catalogue identity. |

Swatches are the one place saturated colour is allowed — that is the paint. Everything around them
stays grey, including the selected state, which is carried by border and weight rather than hue
(`docs/ui-guidelines.md`).

