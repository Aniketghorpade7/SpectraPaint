import { isLightShade, labToCssColour } from './colour';
import type { Shade } from './shade';

/**
 * One Shade, as a row the Dealer can pick.
 *
 * The **Shade Code is the loudest thing on it**, deliberately: the screen narrows the choice down
 * and the Fandeck settles it, so the code is what lets the Dealer pull the physical chip and confirm
 * the real colour (docs/design-decisions.md §8). A swatch that showed only a colour would invite the
 * Customer to judge paint on a monitor, which is the mistake this whole panel is arranged to avoid.
 *
 * A real `<button>`: this is the primary action of the panel, and a div with a click handler cannot
 * be reached from a keyboard.
 */
export function ShadeSwatch({
  shade,
  selected,
  onSelect,
}: {
  shade: Shade;
  selected: boolean;
  onSelect: (shade: Shade) => void;
}) {
  const colour = labToCssColour(shade.lab);

  return (
    <button
      type="button"
      className={`shade-swatch${selected ? ' shade-swatch--selected' : ''}`}
      aria-pressed={selected}
      onClick={() => onSelect(shade)}
    >
      <span
        className={`shade-swatch__chip${isLightShade(shade.lab) ? ' shade-swatch__chip--light' : ''}`}
        style={{ background: colour }}
      >
        {/* The code sits on the colour itself, where the eye already is. */}
        <span className="shade-swatch__code">{shade.shade_code}</span>
      </span>

      <span className="shade-swatch__text">
        <span className="shade-swatch__name">{shade.name}</span>
        <span className="shade-swatch__meta">
          {shade.shade_family}
          {shade.finishes.length > 0 ? ` · ${shade.finishes.join(', ')}` : ''}
        </span>
      </span>
    </button>
  );
}

/** A row whose page has not arrived yet. Keeps the list's height honest while it fetches. */
export function ShadeSwatchPlaceholder() {
  return <span className="shade-swatch shade-swatch--placeholder" aria-hidden="true" />;
}
