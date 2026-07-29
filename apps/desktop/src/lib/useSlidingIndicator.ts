/**
 * Slide one underline between tabs instead of switching two on and off.
 *
 * A border that simply moves from one tab to another gives no sense of
 * direction; a bar that travels does, and in a view with seven tabs that is the
 * difference between noticing you changed panel and wondering why the content
 * changed.
 *
 * The bar cannot be styled by CSS alone because the tabs have different widths —
 * their labels carry counts. So the active tab is measured and its position is
 * published as two custom properties the stylesheet animates.
 */

import { useCallback, useLayoutEffect, useRef, type RefObject } from 'react';

/** Marks the tab the indicator should sit under. */
export const ACTIVE_TAB_ATTRIBUTE = 'data-active';

export function useSlidingIndicator<T extends HTMLElement>(
  activeKey: string,
): RefObject<T> {
  const container = useRef<T>(null);

  const place = useCallback(() => {
    const element = container.current;
    if (!element) return;

    const active = element.querySelector<HTMLElement>(
      `[${ACTIVE_TAB_ATTRIBUTE}="true"]`,
    );
    if (!active) return;

    // offsetLeft is relative to the offset parent, which is the container as
    // long as it is positioned. Reading it costs one layout, once per change.
    element.style.setProperty('--tab-x', `${active.offsetLeft}px`);
    element.style.setProperty('--tab-w', `${active.offsetWidth}px`);
  }, []);

  // Before paint, or the bar shows for one frame at its previous position.
  useLayoutEffect(() => {
    place();
  }, [activeKey, place]);

  // Tab labels carry counts that arrive after the first render, and the window
  // is resizable; both change where the bar belongs.
  useLayoutEffect(() => {
    const element = container.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(place);
    observer.observe(element);
    for (const child of Array.from(element.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [place]);

  return container;
}
