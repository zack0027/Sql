import { describe, expect, it } from 'vitest';

import { clampWidth } from './useResizable';

describe('clampWidth', () => {
  it('keeps a value inside its bounds', () => {
    expect(clampWidth(300, 200, 500)).toBe(300);
  });

  it('clamps below the minimum', () => {
    // Otherwise a panel can be dragged to nothing and never recovered.
    expect(clampWidth(10, 200, 500)).toBe(200);
  });

  it('clamps above the maximum', () => {
    expect(clampWidth(9000, 200, 500)).toBe(500);
  });

  it('rounds to whole pixels', () => {
    expect(clampWidth(300.6, 200, 500)).toBe(301);
  });
});
