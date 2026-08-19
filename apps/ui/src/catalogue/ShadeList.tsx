import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { ShadeSwatch, ShadeSwatchPlaceholder } from './ShadeSwatch';
import type { Shade } from './shade';
import { visibleWindow } from './virtualise';

/**
 * The virtualised list.
 *
 * A Fandeck runs past a thousand Shades, and drawing them all stalls a floor-tier machine
 * (docs/specs/v1-spectrapaint.md). Only the rows in view are rendered; the rest are two blocks of
 * padding standing in for the space they would occupy, so the scrollbar still tells the truth about
 * how much Catalogue there is.
 *
 * Rows are a fixed height, which is what makes the arithmetic possible without measuring anything.
 * Keep `--shade-row-height` in catalogue.css and `ROW_HEIGHT` here in step.
 */
export const ROW_HEIGHT = 56;

export function ShadeList({
  rowCount,
  shadeAt,
  onShowRows,
  onSelect,
  selectedShadeCode,
  label,
}: {
  rowCount: number;
  shadeAt: (index: number) => Shade | undefined;
  onShowRows: (start: number, end: number) => void;
  onSelect: (shade: Shade) => void;
  selectedShadeCode?: string;
  label: string;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);

  // Measured after layout, and again whenever the panel is resized: the number of rows that fit is
  // the one input this component cannot be told.
  useLayoutEffect(() => {
    const element = viewport.current;
    if (!element) return;

    const measure = () => setViewportHeight(element.clientHeight);
    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const window_ = visibleWindow({ scrollTop, viewportHeight, rowHeight: ROW_HEIGHT, rowCount });

  useEffect(() => {
    if (window_.end > window_.start) onShowRows(window_.start, window_.end);
  }, [onShowRows, window_.start, window_.end]);

  // A shorter list after a search must not stay scrolled past its own end. Only the DOM is touched
  // here: the scroll itself raises the event that updates the window, so there is nothing to set.
  useEffect(() => {
    viewport.current?.scrollTo({ top: 0 });
  }, [rowCount]);

  const rows = [];
  for (let index = window_.start; index < window_.end; index += 1) {
    const shade = shadeAt(index);
    rows.push(
      <li className="shade-list__row" key={shade?.shade_code ?? `row-${index}`}>
        {shade ? (
          <ShadeSwatch
            shade={shade}
            selected={shade.shade_code === selectedShadeCode}
            onSelect={onSelect}
          />
        ) : (
          <ShadeSwatchPlaceholder />
        )}
      </li>,
    );
  }

  return (
    <div
      className="shade-list"
      ref={viewport}
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
    >
      <ul className="shade-list__rows" aria-label={label}>
        <li style={{ height: window_.paddingTop }} aria-hidden="true" />
        {rows}
        <li style={{ height: window_.paddingBottom }} aria-hidden="true" />
      </ul>
    </div>
  );
}
