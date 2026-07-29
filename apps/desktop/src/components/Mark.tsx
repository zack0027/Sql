/**
 * HANA's mark: a hub with three satellites — a knowledge graph at its smallest.
 *
 * Drawn as SVG rather than by loading the .ico, so it scales cleanly and takes
 * its colours from the theme. The geometry matches `scripts/make_icons.py`,
 * which renders the same shape into the application icon; if one moves, the
 * other has to move with it or the badge in the header stops being the thing in
 * the taskbar.
 */

import styles from './Mark.module.css';

/** Satellites at the top, lower-left and lower-right. */
const SATELLITES = [
  { x: 32, y: 12.4, className: styles.nodePale },
  { x: 14.9, y: 42.3, className: styles.nodeViolet },
  { x: 49.1, y: 42.3, className: styles.nodeAccent },
];

export function Mark({ size = 42 }: { size?: number }): JSX.Element {
  return (
    <svg
      className={styles.mark}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="HANA"
    >
      <rect width="64" height="64" rx="12" className={styles.plate} />
      <circle cx="32" cy="32" r="23.4" fill="none" className={styles.ring} />

      {SATELLITES.map((satellite) => (
        <line
          key={`${satellite.x}-${satellite.y}`}
          x1="32"
          y1="32"
          x2={satellite.x}
          y2={satellite.y}
          className={styles.spoke}
        />
      ))}

      <circle cx="32" cy="32" r="6.7" className={styles.nodeAccent} />
      {SATELLITES.map((satellite) => (
        <circle
          key={`node-${satellite.x}-${satellite.y}`}
          cx={satellite.x}
          cy={satellite.y}
          r="5"
          className={satellite.className}
        />
      ))}
    </svg>
  );
}
