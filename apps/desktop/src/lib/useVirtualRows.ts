/**
 * Render only the rows a scroll container can actually show.
 *
 * The file panel used to mount one element per file. At a thousand-odd files
 * that is a thousand-odd buttons in the document, and every re-render — a new
 * filter keystroke, a selection, a finished analysis — walks all of them. The
 * user's real project has 1239 files and typing in the filter box stuttered.
 *
 * Written by hand rather than pulled from a library: the whole windowing rule is
 * the twenty lines below, and this project cannot reach the npm registry anyway
 * (see docs/OFFLINE_DEPENDENCIES.md).
 */

import { useCallback, useLayoutEffect, useRef, useState } from 'react';

export interface VirtualWindow {
  /** Attach to the scrolling element. */
  ref: React.RefObject<HTMLDivElement>;
  onScroll: () => void;
  /** First row to render, and one past the last. */
  start: number;
  end: number;
  /** Height of the full list, so the scrollbar reflects everything. */
  totalHeight: number;
  /** Pixels to push the rendered slice down by. */
  offsetY: number;
}

/**
 * Rows outside the viewport still rendered above and below.
 *
 * Without this a fast scroll or a wheel fling shows blank space for one frame,
 * because scroll events arrive after the paint.
 */
const OVERSCAN = 8;

/**
 * Which rows to render, given where the container is scrolled to.
 *
 * Pulled out of the hook so it can be tested as what it is — arithmetic — rather
 * than through a rendered component. Everything that can be wrong here is off by
 * a row or runs past an end.
 */
export function visibleRange(
  count: number,
  rowHeight: number,
  scrollTop: number,
  viewportHeight: number,
): { start: number; end: number } {
  // Before the first measurement the container height is 0, which would window
  // the list down to nothing. Assume a screenful instead — too many rows for one
  // frame is invisible; too few is a blank panel.
  const visible = viewportHeight > 0 ? Math.ceil(viewportHeight / rowHeight) : 40;
  const first = Math.floor(Math.max(0, scrollTop) / rowHeight);

  return {
    start: Math.max(0, Math.min(first - OVERSCAN, Math.max(0, count - 1))),
    end: Math.min(count, first + visible + OVERSCAN),
  };
}

export function useVirtualRows(count: number, rowHeight: number): VirtualWindow {
  const ref = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(0);

  const measure = useCallback(() => {
    const element = ref.current;
    if (!element) return;
    setScrollTop(element.scrollTop);
    setHeight(element.clientHeight);
  }, []);

  // Layout effect, not a plain effect: the panel is resizable, and measuring
  // after paint would show one frame windowed to the old height.
  useLayoutEffect(() => {
    measure();
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);

  const { start, end } = visibleRange(count, rowHeight, scrollTop, height);

  return {
    ref,
    onScroll: measure,
    start,
    end,
    totalHeight: count * rowHeight,
    offsetY: start * rowHeight,
  };
}
