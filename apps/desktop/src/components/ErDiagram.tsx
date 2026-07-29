/**
 * Entity-relationship diagram, drawn from what the SQL actually does.
 *
 * An important honesty constraint runs through this view: the links are **join
 * conditions found in queries**, not declared foreign keys. HANA never connects
 * to Oracle, so it cannot know the real constraints. What it can know — and what
 * is often more useful — is how the code actually relates these tables. The
 * header says so, and every link can be opened at the line that proves it.
 *
 * Tables are laid out on a grid rather than by a force simulation: a diagram
 * that rearranges itself every time you open it cannot be learned, and people
 * navigate schemas from memory of where things sat.
 */

import { useMemo, useState, type CSSProperties } from 'react';

import type { ErModel, ErTable } from '@hana/shared-types';

import styles from './ErDiagram.module.css';

interface Props {
  model: ErModel | null;
  loading: boolean;
  onOpenEvidence: (path: string, line: number | null) => void;
}

const BOX_WIDTH = 210;
const COLUMN_HEIGHT = 17;
const HEADER_HEIGHT = 30;
const GAP_X = 90;
const GAP_Y = 70;
/** Columns listed per table before the rest are summarised. */
const MAX_COLUMNS = 12;

interface Placed {
  table: ErTable;
  x: number;
  y: number;
  height: number;
}

export function ErDiagram({ model, loading, onOpenEvidence }: Props): JSX.Element {
  const [zoom, setZoom] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);

  const placed = useMemo<Placed[]>(() => {
    if (!model) return [];
    // Tables come back sorted by name, so the grid is stable between openings.
    const perRow = Math.max(1, Math.ceil(Math.sqrt(model.tables.length)));
    return model.tables.map((table, index) => {
      const shown = Math.min(table.columns.length, MAX_COLUMNS);
      return {
        table,
        x: (index % perRow) * (BOX_WIDTH + GAP_X),
        y: Math.floor(index / perRow) * (HEADER_HEIGHT + MAX_COLUMNS * COLUMN_HEIGHT + GAP_Y),
        height: HEADER_HEIGHT + Math.max(1, shown) * COLUMN_HEIGHT + 8,
      };
    });
  }, [model]);

  const byId = useMemo(
    () => new Map(placed.map((item) => [item.table.id, item])),
    [placed],
  );

  if (loading) {
    return <p className={styles.placeholder}>Construyendo el diagrama…</p>;
  }
  if (!model || model.tables.length === 0) {
    return (
      <p className={styles.placeholder}>
        No hay tablas Oracle en este proyecto todavía. Analiza una carpeta con
        SQL, PL/SQL o comandos MOCA.
      </p>
    );
  }

  const width = Math.max(...placed.map((item) => item.x + BOX_WIDTH)) + 60;
  const height = Math.max(...placed.map((item) => item.y + item.height)) + 60;

  return (
    <div className={styles.wrapper}>
      <div className={styles.toolbar}>
        <button className={styles.tool} onClick={() => setZoom((z) => Math.min(2, z * 1.2))}>
          +
        </button>
        <button className={styles.tool} onClick={() => setZoom((z) => Math.max(0.3, z / 1.2))}>
          −
        </button>
        <button className={styles.tool} onClick={() => setZoom(1)} title="Tamaño original">
          ⌂
        </button>
        <span className={styles.count}>
          {model.tables.length} tablas · {model.links.length} relaciones
        </span>
        {/* Said plainly, where it cannot be missed. */}
        <span className={styles.caveat}>
          relaciones deducidas de condiciones JOIN, no de claves foráneas
        </span>
      </div>

      <div className={styles.scroll}>
        <svg
          width={width * zoom}
          height={height * zoom}
          viewBox={`-30 -30 ${width} ${height}`}
          className={styles.canvas}
        >
          <defs>
            <marker id="erArrow" viewBox="0 0 10 10" refX="9" refY="5"
                    markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--border-strong)" />
            </marker>
          </defs>

          {model.links.map((link, index) => {
            const from = byId.get(link.source_id);
            const to = byId.get(link.target_id);
            if (!from || !to) return null;
            const x1 = from.x + BOX_WIDTH / 2;
            const y1 = from.y + from.height / 2;
            const x2 = to.x + BOX_WIDTH / 2;
            const y2 = to.y + to.height / 2;
            const active =
              selected === null || selected === link.source_id || selected === link.target_id;

            return (
              <g key={index} opacity={active ? 1 : 0.15}>
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke="var(--border-strong)"
                  strokeWidth={1.8}
                  markerEnd="url(#erArrow)"
                />
                <text
                  className={styles.linkLabel}
                  x={(x1 + x2) / 2}
                  y={(y1 + y2) / 2 - 5}
                  textAnchor="middle"
                  onClick={() =>
                    link.evidence.file_path &&
                    onOpenEvidence(link.evidence.file_path, link.evidence.start_line)
                  }
                >
                  {link.left_column} = {link.right_column}
                </text>
              </g>
            );
          })}

          {placed.map((item, index) => (
            <TableBox
              key={item.table.id}
              item={item}
              order={index}
              dimmed={selected !== null && selected !== item.table.id}
              onSelect={() =>
                setSelected((current) => (current === item.table.id ? null : item.table.id))
              }
            />
          ))}
        </svg>
      </div>

      <p className={styles.hint}>
        Clic en una tabla para aislar sus relaciones · clic en la etiqueta de una
        relación para abrir el SQL que la prueba
      </p>
    </div>
  );
}

function TableBox({
  item,
  dimmed,
  order,
  onSelect,
}: {
  item: Placed;
  dimmed: boolean;
  /** Position in the grid, which decides when this box animates in. */
  order: number;
  onSelect: () => void;
}): JSX.Element {
  const shown = item.table.columns.slice(0, MAX_COLUMNS);
  const hidden = item.table.columns.length - shown.length;

  return (
    <g
      transform={`translate(${item.x} ${item.y})`}
      opacity={dimmed ? 0.25 : 1}
      className={styles.box}
      style={{ '--delay': `${Math.min(order, 14) * 35}ms` } as CSSProperties}
      onClick={onSelect}
    >
      <rect
        width={BOX_WIDTH}
        height={item.height}
        rx={6}
        fill="var(--surface-panel)"
        stroke="var(--border-strong)"
        strokeWidth={1.5}
      />
      <rect width={BOX_WIDTH} height={HEADER_HEIGHT} rx={6} fill="var(--surface-raised)" />
      <text className={styles.tableName} x={10} y={20}>
        {item.table.name.length > 24
          ? `${item.table.name.slice(0, 23)}…`
          : item.table.name}
      </text>

      {shown.map((column, index) => (
        <text
          key={column.id}
          className={styles.columnName}
          x={12}
          y={HEADER_HEIGHT + 13 + index * COLUMN_HEIGHT}
        >
          {column.name.length > 26 ? `${column.name.slice(0, 25)}…` : column.name}
        </text>
      ))}

      {shown.length === 0 && (
        <text className={styles.noColumns} x={12} y={HEADER_HEIGHT + 13}>
          sin columnas detectadas
        </text>
      )}
      {hidden > 0 && (
        <text
          className={styles.noColumns}
          x={12}
          y={HEADER_HEIGHT + 13 + shown.length * COLUMN_HEIGHT}
        >
          +{hidden} más
        </text>
      )}
    </g>
  );
}
