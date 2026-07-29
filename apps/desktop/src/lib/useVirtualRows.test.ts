import { describe, expect, it } from 'vitest';

import { visibleRange } from './useVirtualRows';

const ROW = 24;
const VIEWPORT = 240; // ten rows

describe('visibleRange', () => {
  it('renders a slice, not the whole list', () => {
    const { start, end } = visibleRange(1000, ROW, 0, VIEWPORT);
    expect(start).toBe(0);
    expect(end - start).toBeLessThan(40);
  });

  it('covers the whole viewport', () => {
    const { start, end } = visibleRange(1000, ROW, 0, VIEWPORT);
    expect(end - start).toBeGreaterThanOrEqual(VIEWPORT / ROW);
  });

  it('moves the window down as the container scrolls', () => {
    const { start, end } = visibleRange(1000, ROW, 100 * ROW, VIEWPORT);
    expect(start).toBeLessThanOrEqual(100);
    expect(end).toBeGreaterThan(100 + VIEWPORT / ROW);
  });

  it('keeps rows above the viewport, so a fling does not show a gap', () => {
    expect(visibleRange(1000, ROW, 100 * ROW, VIEWPORT).start).toBeLessThan(100);
  });

  it('never runs past the end of the list', () => {
    expect(visibleRange(12, ROW, 5000, VIEWPORT).end).toBe(12);
  });

  it('never starts before the beginning', () => {
    expect(visibleRange(1000, ROW, 0, VIEWPORT).start).toBe(0);
  });

  it('renders a screenful before the container has been measured', () => {
    // Height is 0 on the first pass; windowing to nothing would blank the panel.
    expect(visibleRange(1000, ROW, 0, 0).end).toBeGreaterThan(0);
  });

  it('an empty list asks for no rows', () => {
    expect(visibleRange(0, ROW, 0, VIEWPORT)).toEqual({ start: 0, end: 0 });
  });

  it('a list shorter than the viewport asks for all of it and no more', () => {
    expect(visibleRange(3, ROW, 0, VIEWPORT).end).toBe(3);
  });
});
