import { describe, expect, it } from 'vitest';

import { formatBytes, formatCount, formatRelativeTime, truncatePath } from './format';

describe('formatCount', () => {
  it('distinguishes missing data from zero', () => {
    // "—" and "0" mean very different things on a screen reporting knowledge.
    expect(formatCount(undefined)).toBe('—');
    expect(formatCount(null)).toBe('—');
    expect(formatCount(0)).toBe('0');
  });

  it('groups thousands', () => {
    expect(formatCount(1234567)).toMatch(/1.234.567|1,234,567/);
  });
});

describe('formatBytes', () => {
  it('keeps small sizes exact', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
  });

  it('scales to larger units', () => {
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });

  it('drops the decimal once the number is big enough to be unhelpful', () => {
    expect(formatBytes(20 * 1024 * 1024)).toBe('20 MB');
  });

  it('handles missing values', () => {
    expect(formatBytes(undefined)).toBe('—');
  });
});

describe('formatRelativeTime', () => {
  const now = new Date('2026-07-24T12:00:00Z');

  it('reports never for missing timestamps', () => {
    expect(formatRelativeTime(null, now)).toBe('nunca');
  });

  it('reports coarse buckets', () => {
    expect(formatRelativeTime('2026-07-24T11:59:30Z', now)).toBe('hace instantes');
    expect(formatRelativeTime('2026-07-24T11:30:00Z', now)).toBe('hace 30 min');
    expect(formatRelativeTime('2026-07-24T09:00:00Z', now)).toBe('hace 3 h');
    expect(formatRelativeTime('2026-07-20T12:00:00Z', now)).toBe('hace 4 d');
  });

  it('falls back to a date for anything older than a month', () => {
    expect(formatRelativeTime('2025-01-01T12:00:00Z', now)).toMatch(/2025/);
  });

  it('does not produce negative durations for clock skew', () => {
    expect(formatRelativeTime('2026-07-24T12:00:30Z', now)).toBe('ahora');
  });

  it('survives an unparseable timestamp', () => {
    expect(formatRelativeTime('not-a-date', now)).toBe('—');
  });
});

describe('truncatePath', () => {
  it('leaves short paths alone', () => {
    expect(truncatePath('sql/a.sql')).toBe('sql/a.sql');
  });

  it('keeps the filename visible', () => {
    const result = truncatePath('a/very/deep/nested/folder/structure/report.jrxml', 20);
    expect(result.endsWith('report.jrxml')).toBe(true);
    expect(result.startsWith('…')).toBe(true);
  });
});
