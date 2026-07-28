/**
 * The knowledge graph, drawn as SVG.
 *
 * Written by hand rather than pulling in a graph library. Two reasons: the npm
 * registry is unreachable on the target network, and what this view needs is
 * narrow — bounded rings, click to focus, double-click to expand, and a visual
 * difference between a fact and an inference. That last one is the product's
 * whole promise, so it is worth controlling directly: confirmed edges are solid,
 * inferred ones are dashed and dimmer, and no amount of styling can make an
 * inference look like a proof.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { Neighborhood } from '@hana/shared-types';

import {
  boundsOf,
  colorOf,
  layoutNeighborhood,
  relationLabel,
  type PositionedEdge,
  type PositionedNode,
} from '../lib/graph';
import styles from './GraphCanvas.module.css';

interface Props {
  graph: Neighborhood | null;
  focusId: string | null;
  expanded: Set<string>;
  loading: boolean;
  onSelect: (entityId: string) => void;
  onExpand: (entityId: string) => void;
}

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2.5;

export function GraphCanvas({
  graph,
  focusId,
  expanded,
  loading,
  onSelect,
  onExpand,
}: Props): JSX.Element {
  const layout = useMemo(
    () => (graph ? layoutNeighborhood(graph) : null),
    [graph],
  );
  const bounds = useMemo(
    () => (layout ? boundsOf(layout) : { minX: 0, minY: 0, width: 100, height: 100 }),
    [layout],
  );

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hovered, setHovered] = useState<string | null>(null);
  const dragging = useRef<{ x: number; y: number } | null>(null);

  // A new graph is a new picture: recentre rather than leaving the viewport
  // wherever the last one happened to be.
  useEffect(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, [focusId]);

  const onWheel = useCallback((event: React.WheelEvent) => {
    event.preventDefault();
    setZoom((current) =>
      Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current * (event.deltaY < 0 ? 1.12 : 0.89))),
    );
  }, []);

  const onPointerDown = (event: React.PointerEvent) => {
    dragging.current = { x: event.clientX - pan.x, y: event.clientY - pan.y };
    (event.target as Element).setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent) => {
    if (!dragging.current) return;
    setPan({
      x: event.clientX - dragging.current.x,
      y: event.clientY - dragging.current.y,
    });
  };

  const onPointerUp = () => {
    dragging.current = null;
  };

  if (!layout || layout.nodes.length === 0) {
    return (
      <div className={styles.empty}>
        <p className={styles.emptyTitle}>Sin nada que mostrar todavía</p>
        <p className={styles.emptyText}>
          Busca una tabla, un item APEX o un reporte y selecciónalo para ver su
          vecindario en el grafo.
        </p>
      </div>
    );
  }

  const viewBox = `${bounds.minX} ${bounds.minY} ${bounds.width} ${bounds.height}`;

  return (
    <div className={styles.wrapper}>
      <div className={styles.toolbar}>
        <button className={styles.tool} onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z * 1.2))}>
          +
        </button>
        <button className={styles.tool} onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z / 1.2))}>
          −
        </button>
        <button
          className={styles.tool}
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
          title="Centrar"
        >
          ⌂
        </button>
        <span className={styles.count}>
          {layout.nodes.length} nodos · {layout.edges.length} relaciones
          {layout.truncated && ' · truncado'}
        </span>
        {loading && <span className={styles.loading}>cargando…</span>}
      </div>

      <svg
        className={styles.canvas}
        viewBox={viewBox}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#3a4d61" />
          </marker>
        </defs>

        <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
          {layout.edges.map((edge) => (
            <Edge key={edge.id} edge={edge} dimmed={hovered !== null && !touches(edge, hovered)} />
          ))}
          {layout.nodes.map((node) => (
            <Node
              key={node.id}
              node={node}
              isFocus={node.id === focusId}
              isExpanded={expanded.has(node.id)}
              dimmed={hovered !== null && hovered !== node.id && !neighbours(layout.edges, hovered).has(node.id)}
              onSelect={onSelect}
              onExpand={onExpand}
              onHover={setHovered}
            />
          ))}
        </g>
      </svg>

      <p className={styles.hint}>
        Clic para enfocar · doble clic para expandir vecinos · rueda para acercar ·
        arrastra para mover
      </p>
    </div>
  );
}

function touches(edge: PositionedEdge, id: string): boolean {
  return edge.source.id === id || edge.target.id === id;
}

function neighbours(edges: PositionedEdge[], id: string): Set<string> {
  const found = new Set<string>();
  for (const edge of edges) {
    if (edge.source.id === id) found.add(edge.target.id);
    if (edge.target.id === id) found.add(edge.source.id);
  }
  return found;
}

function Edge({ edge, dimmed }: { edge: PositionedEdge; dimmed: boolean }): JSX.Element {
  const midX = (edge.source.x + edge.target.x) / 2;
  const midY = (edge.source.y + edge.target.y) / 2;
  return (
    <g opacity={dimmed ? 0.15 : 1}>
      <line
        x1={edge.source.x}
        y1={edge.source.y}
        x2={edge.target.x}
        y2={edge.target.y}
        stroke={edge.inferred ? '#d29922' : '#2b3b4c'}
        strokeWidth={edge.inferred ? 1.4 : 2}
        // Dashed means inferred. A convention, not a proof — and the picture
        // says so without anyone having to read a tooltip.
        strokeDasharray={edge.inferred ? '6 5' : undefined}
        markerEnd="url(#arrow)"
      />
      <text className={styles.edgeLabel} x={midX} y={midY - 6} textAnchor="middle">
        {relationLabel(edge.relation)}
      </text>
    </g>
  );
}

function Node({
  node,
  isFocus,
  isExpanded,
  dimmed,
  onSelect,
  onExpand,
  onHover,
}: {
  node: PositionedNode;
  isFocus: boolean;
  isExpanded: boolean;
  dimmed: boolean;
  onSelect: (id: string) => void;
  onExpand: (id: string) => void;
  onHover: (id: string | null) => void;
}): JSX.Element {
  const radius = isFocus ? 26 : 20;
  const color = colorOf(node.type);

  return (
    <g
      className={styles.node}
      opacity={dimmed ? 0.2 : 1}
      transform={`translate(${node.x} ${node.y})`}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(node.id);
      }}
      onDoubleClick={(event) => {
        event.stopPropagation();
        onExpand(node.id);
      }}
      onPointerEnter={() => onHover(node.id)}
      onPointerLeave={() => onHover(null)}
    >
      <circle
        r={radius}
        fill={color}
        fillOpacity={node.inferred ? 0.25 : 0.9}
        stroke={isFocus ? '#e6edf3' : color}
        strokeWidth={isFocus ? 3 : 1.5}
        strokeDasharray={node.inferred ? '5 4' : undefined}
      />
      {!isExpanded && (
        <circle className={styles.expandDot} r={4} cx={radius - 3} cy={-radius + 3} />
      )}
      <text className={styles.nodeType} y={-radius - 16} textAnchor="middle">
        {node.type}
      </text>
      <text className={styles.nodeLabel} y={radius + 16} textAnchor="middle">
        {node.label.length > 26 ? `${node.label.slice(0, 25)}…` : node.label}
      </text>
      {node.inferred && (
        <text className={styles.nodeConfidence} y={radius + 30} textAnchor="middle">
          inferido {node.confidence.toFixed(2)}
        </text>
      )}
    </g>
  );
}
