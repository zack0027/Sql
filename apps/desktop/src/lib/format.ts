/** Presentation helpers. Pure functions, no engine knowledge, easy to test. */

/** Format a count for display, with `—` for missing data (which is not zero). */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('es').format(value);
}

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const;

/** Human-readable byte size using 1024-based units. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;

  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${UNITS[unit]}`;
}

/**
 * Coarse relative time in Spanish.
 *
 * Deliberately coarse: "hace 3 h" is more useful in this UI than a precise
 * duration, and it avoids re-rendering every second.
 */
export function formatRelativeTime(
  iso: string | null | undefined,
  now: Date = new Date(),
): string {
  if (!iso) return 'nunca';
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return '—';

  const seconds = Math.floor((now.getTime() - then.getTime()) / 1000);
  if (seconds < 0) return 'ahora';
  if (seconds < 60) return 'hace instantes';
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)} min`;
  if (seconds < 86_400) return `hace ${Math.floor(seconds / 3600)} h`;
  if (seconds < 2_592_000) return `hace ${Math.floor(seconds / 86_400)} d`;
  return then.toLocaleDateString('es');
}

/** Shorten a path from the left, keeping the filename readable. */
export function truncatePath(path: string, maxLength = 48): string {
  if (path.length <= maxLength) return path;
  return `…${path.slice(path.length - maxLength + 1)}`;
}
