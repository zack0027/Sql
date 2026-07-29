/**
 * Count a number up to its new value instead of swapping it.
 *
 * The point is not decoration. These figures change as a side effect of work
 * happening elsewhere — an analysis finishing, a project being selected — and a
 * number that jumps from 70 to 4 210 gives no sign that anything happened. A
 * counter that travels draws the eye to the one tile that moved.
 *
 * Driven by `requestAnimationFrame` against the wall clock rather than by a
 * per-frame increment, so the duration holds whatever frame rate the machine
 * manages, and the final value is assigned exactly rather than accumulated.
 */

import { useEffect, useRef, useState } from 'react';

/** Fast enough to feel like a reaction, slow enough to read. */
const DURATION = 620;

/** Decelerating: quick off the mark, gentle at the end. */
function easeOut(t: number): number {
  return 1 - (1 - t) ** 3;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

export function useCountUp(target: number | null | undefined): number | null {
  const [value, setValue] = useState<number | null>(target ?? null);
  const from = useRef(0);
  const frame = useRef(0);

  useEffect(() => {
    if (target === null || target === undefined) {
      setValue(null);
      return;
    }

    // Someone who asked for less motion wants the number, not the journey.
    if (prefersReducedMotion() || target === from.current) {
      from.current = target;
      setValue(target);
      return;
    }

    const start = performance.now();
    const origin = from.current;
    const distance = target - origin;

    const step = (now: number): void => {
      const progress = Math.min(1, (now - start) / DURATION);
      if (progress >= 1) {
        from.current = target;
        setValue(target);
        return;
      }
      setValue(Math.round(origin + distance * easeOut(progress)));
      frame.current = requestAnimationFrame(step);
    };

    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [target]);

  return value;
}
