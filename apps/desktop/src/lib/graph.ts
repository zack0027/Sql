/**
 * Graph layout and file-tree shaping.
 *
 * Pure functions, no React and no DOM, so the parts that are easy to get subtly
 * wrong are the parts that are easy to test.
 *
 * The layout is radial by depth: the entity you asked about sits at the centre,
 * its immediate neighbours form a ring, their neighbours form an outer ring.
 * That mirrors how the engine returns a neighbourhood — bounded and expanded on
 * demand — instead of trying to draw a whole project at once.
 *
 * Positions are derived from each node's index, never from randomness or a
 * simulation, so the same graph always renders identically. A node that jumped
 * between renders would make the picture impossible to reason about.
 */

import type {
  EntityType,
  FileTreeItem,
  GraphEdgeHit,
  Neighborhood,
} from '@hana/shared-types';

export interface PositionedNode {
  id: string;
  label: string;
  type: EntityType;
  depth: number;
  confidence: number;
  inferred: boolean;
  filePath: string | null;
  startLine: number | null;
  x: number;
  y: number;
}

export interface PositionedEdge {
  id: string;
  source: PositionedNode;
  target: PositionedNode;
  relation: string;
  inferred: boolean;
  confidence: number;
  edge: GraphEdgeHit;
}

export interface GraphLayout {
  nodes: PositionedNode[];
  edges: PositionedEdge[];
  width: number;
  height: number;
  truncated: boolean;
}

export interface LayoutOptions {
  /** Distance between consecutive rings. */
  ringGap?: number;
  /** Where the centre sits; the canvas is sized around it. */
  centre?: { x: number; y: number };
}

const DEFAULT_RING_GAP = 190;

/**
 * Place a neighbourhood on a plane.
 *
 * Rings are spread evenly, with a half-step rotation per level so nodes on
 * successive rings do not line up and hide their edges behind one another.
 */
export function layoutNeighborhood(
  neighborhood: Neighborhood,
  options: LayoutOptions = {},
): GraphLayout {
  const ringGap = options.ringGap ?? DEFAULT_RING_GAP;
  const centre = options.centre ?? { x: 0, y: 0 };

  const byDepth = new Map<number, typeof neighborhood.nodes>();
  for (const node of neighborhood.nodes) {
    const bucket = byDepth.get(node.depth) ?? [];
    bucket.push(node);
    byDepth.set(node.depth, bucket);
  }

  const positioned = new Map<string, PositionedNode>();

  for (const [depth, bucket] of [...byDepth.entries()].sort((a, b) => a[0] - b[0])) {
    // Sorting by name keeps the picture stable when the engine returns the same
    // set in a different order.
    const ordered = [...bucket].sort((a, b) =>
      a.entity.normalized_name.localeCompare(b.entity.normalized_name),
    );

    ordered.forEach((node, index) => {
      const radius = depth * ringGap;
      const angle =
        depth === 0
          ? 0
          : (index / ordered.length) * Math.PI * 2 + (depth % 2) * (Math.PI / ordered.length);

      positioned.set(node.entity.id, {
        id: node.entity.id,
        label: node.entity.name,
        type: node.entity.entity_type,
        depth: node.depth,
        confidence: node.entity.confidence,
        inferred: node.entity.verification_status !== 'confirmed',
        filePath: node.entity.file_path,
        startLine: node.entity.start_line,
        x: centre.x + radius * Math.cos(angle),
        y: centre.y + radius * Math.sin(angle),
      });
    });
  }

  const edges: PositionedEdge[] = [];
  for (const edge of neighborhood.edges) {
    const source = positioned.get(edge.source_id);
    const target = positioned.get(edge.target_id);
    // An edge with an end outside the returned nodes would render as a line to
    // nowhere. The engine already filters these; this is the second guard.
    if (!source || !target) continue;
    edges.push({
      id: `${edge.source_id}|${edge.relation_type}|${edge.target_id}`,
      source,
      target,
      relation: edge.relation_type,
      inferred: edge.status !== 'confirmed',
      confidence: edge.confidence,
      edge,
    });
  }

  const nodes = [...positioned.values()];
  const maxRadius = Math.max(
    ringGap,
    ...nodes.map((node) => Math.hypot(node.x - centre.x, node.y - centre.y)),
  );
  const span = (maxRadius + ringGap) * 2;

  return { nodes, edges, width: span, height: span, truncated: neighborhood.truncated };
}

/** Bounding box of a layout, with padding, for fitting the viewport. */
export function boundsOf(
  layout: GraphLayout,
  padding = 120,
): { minX: number; minY: number; width: number; height: number } {
  if (layout.nodes.length === 0) {
    return { minX: -padding, minY: -padding, width: padding * 2, height: padding * 2 };
  }
  const xs = layout.nodes.map((node) => node.x);
  const ys = layout.nodes.map((node) => node.y);
  const minX = Math.min(...xs) - padding;
  const minY = Math.min(...ys) - padding;
  return {
    minX,
    minY,
    width: Math.max(...xs) + padding - minX,
    height: Math.max(...ys) + padding - minY,
  };
}

// ---------------------------------------------------------------------------
// File tree
// ---------------------------------------------------------------------------

export interface TreeNode {
  name: string;
  path: string;
  isDirectory: boolean;
  children: TreeNode[];
  file?: FileTreeItem;
}

/**
 * Turn the engine's flat, sorted file list into a tree.
 *
 * The engine sends a flat list on purpose — it keeps the payload small and lets
 * the UI decide what is expanded. Building the tree here is that decision.
 */
export function buildFileTree(items: FileTreeItem[]): TreeNode[] {
  const root: TreeNode = { name: '', path: '', isDirectory: true, children: [] };

  for (const item of items) {
    const parts = item.relative_path.split('/').filter(Boolean);
    let current = root;

    parts.forEach((part, index) => {
      const isLeaf = index === parts.length - 1;
      const path = parts.slice(0, index + 1).join('/');
      let child = current.children.find((node) => node.name === part);

      if (!child) {
        child = {
          name: part,
          path,
          isDirectory: !isLeaf,
          children: [],
          ...(isLeaf ? { file: item } : {}),
        };
        current.children.push(child);
      }
      current = child;
    });
  }

  sortTree(root);
  return root.children;
}

/** Directories first, then files, each alphabetically — the usual expectation. */
function sortTree(node: TreeNode): void {
  node.children.sort((a, b) => {
    if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  node.children.forEach(sortTree);
}

/** One visible line of the tree: what to draw and how far to indent it. */
export interface TreeRow {
  node: TreeNode;
  depth: number;
}

/**
 * Flatten the visible part of the tree into rows.
 *
 * Virtualising needs a list, not a recursion: to draw only the rows on screen a
 * component has to know how many rows there are and what sits at index *n*
 * without walking the whole structure first. A collapsed folder contributes one
 * row and nothing beneath it, so what this costs follows what is open rather
 * than how large the project is.
 */
export function flattenTree(
  nodes: TreeNode[],
  isExpanded: (node: TreeNode) => boolean,
): TreeRow[] {
  const rows: TreeRow[] = [];
  const walk = (list: TreeNode[], depth: number): void => {
    for (const node of list) {
      rows.push({ node, depth });
      if (node.isDirectory && isExpanded(node)) {
        walk(node.children, depth + 1);
      }
    }
  };
  walk(nodes, 0);
  return rows;
}

/** Every directory path in a tree, for expanding all at once. */
export function directoryPaths(nodes: TreeNode[]): string[] {
  const paths: string[] = [];
  const walk = (list: TreeNode[]): void => {
    for (const node of list) {
      if (node.isDirectory) {
        paths.push(node.path);
        walk(node.children);
      }
    }
  };
  walk(nodes);
  return paths;
}

// ---------------------------------------------------------------------------
// Presentation
// ---------------------------------------------------------------------------

/** Colour per entity family. Keeps the graph readable at a glance. */
export const ENTITY_COLORS: Record<string, string> = {
  OracleTable: '#3ba3ff',
  OracleView: '#3ba3ff',
  OracleColumn: '#63b8ff',
  OracleProcedure: '#9d7bff',
  OracleFunction: '#9d7bff',
  OraclePackage: '#8b5cf6',
  SqlQuery: '#4dd4ac',
  ApexItem: '#f59e0b',
  ApexPage: '#fbbf24',
  ApexApplication: '#fbbf24',
  JasperReport: '#ef6461',
  JasperField: '#f79c98',
  JasperParameter: '#f79c98',
  JasperVariable: '#f79c98',
  JasperSubreport: '#ef6461',
  MocaCommand: '#2dd4bf',
  MocaVariable: '#5eead4',
  JsonProperty: '#94a3b8',
  JavaScriptFunction: '#eab308',
  PythonFunction: '#38bdf8',
  File: '#64798d',
  Directory: '#64798d',
};

export function colorOf(type: string): string {
  return ENTITY_COLORS[type] ?? '#8b949e';
}

/** Short label for a relation, for edge captions. */
export function relationLabel(relation: string): string {
  return relation.toLowerCase().replace(/_/g, ' ');
}
