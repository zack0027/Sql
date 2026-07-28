/**
 * Drag-to-resize for the explorer's side panels.
 *
 * Widths persist in localStorage: a layout the user adjusted should still be
 * there next time, and re-dragging the same panel on every launch is exactly
 * the kind of small friction that makes a tool feel unfinished.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export interface Resizable {
  width: number;
  /** Attach to the drag handle. */
  onPointerDown: (event: React.PointerEvent) => void;
  dragging: boolean;
  reset: () => void;
}

export function clampWidth(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

function stored(key: string, fallback: number): number {
  if (typeof localStorage === 'undefined') return fallback;
  const raw = localStorage.getItem(key);
  const parsed = raw === null ? Number.NaN : Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function useResizable(
  key: string,
  initial: number,
  { min = 180, max = 640, side = 'left' as 'left' | 'right' } = {},
): Resizable {
  const [width, setWidth] = useState(() => clampWidth(stored(key, initial), min, max));
  const [dragging, setDragging] = useState(false);
  const origin = useRef<{ x: number; width: number } | null>(null);

  const onPointerDown = useCallback(
    (event: React.PointerEvent) => {
      event.preventDefault();
      origin.current = { x: event.clientX, width };
      setDragging(true);
    },
    [width],
  );

  useEffect(() => {
    if (!dragging) return;

    const move = (event: PointerEvent) => {
      if (!origin.current) return;
      const delta = event.clientX - origin.current.x;
      // A right-hand panel grows when the handle moves left, so its delta is
      // inverted. Getting this backwards makes the panel fight the cursor.
      const next = origin.current.width + (side === 'left' ? delta : -delta);
      setWidth(clampWidth(next, min, max));
    };

    const stop = () => {
      setDragging(false);
      origin.current = null;
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
    };
  }, [dragging, min, max, side]);

  useEffect(() => {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(key, String(width));
    }
  }, [key, width]);

  const reset = useCallback(() => setWidth(clampWidth(initial, min, max)), [initial, min, max]);

  return { width, onPointerDown, dragging, reset };
}
