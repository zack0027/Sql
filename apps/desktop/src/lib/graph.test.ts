import { describe, expect, it } from 'vitest';

import type { FileTreeItem, Neighborhood } from '@hana/shared-types';

import {
  boundsOf,
  buildFileTree,
  colorOf,
  directoryPaths,
  flattenTree,
  layoutNeighborhood,
  type TreeRow,
} from './graph';

function node(id: string, name: string, depth: number, confidence = 1) {
  return {
    entity: {
      id,
      entity_type: 'OracleTable' as const,
      name,
      normalized_name: name.toUpperCase(),
      qualified_name: null,
      confidence,
      verification_status: (confidence >= 1 ? 'confirmed' : 'inferred') as
        | 'confirmed'
        | 'inferred',
      file_path: 'sql/a.sql',
      start_line: 1,
    },
    depth,
  };
}

function edge(source: string, target: string, confidence = 1) {
  return {
    source_id: source,
    target_id: target,
    relation_type: 'QUERY_READS_TABLE' as const,
    confidence,
    status: (confidence >= 1 ? 'confirmed' : 'inferred') as 'confirmed' | 'inferred',
    evidence: {
      file_path: 'sql/a.sql',
      absolute_path: '/p/sql/a.sql',
      start_line: 3,
      end_line: 3,
      snippet: 'from t',
      analyzer: 'sql',
      confidence,
      status: (confidence >= 1 ? 'confirmed' : 'inferred') as 'confirmed' | 'inferred',
    },
  };
}

const GRAPH: Neighborhood = {
  nodes: [node('A', 'root', 0), node('B', 'beta', 1), node('C', 'alpha', 1)],
  edges: [edge('A', 'B'), edge('A', 'C', 0.9)],
  truncated: false,
};

describe('layoutNeighborhood', () => {
  it('puts the root at the centre', () => {
    const layout = layoutNeighborhood(GRAPH);
    const root = layout.nodes.find((item) => item.id === 'A')!;
    expect(root.x).toBe(0);
    expect(root.y).toBe(0);
  });

  it('places deeper nodes further out', () => {
    const layout = layoutNeighborhood(GRAPH);
    const root = layout.nodes.find((item) => item.id === 'A')!;
    const near = layout.nodes.find((item) => item.id === 'B')!;
    expect(Math.hypot(near.x, near.y)).toBeGreaterThan(Math.hypot(root.x, root.y));
  });

  it('is deterministic: the same graph lays out identically', () => {
    // A picture that shifts between renders cannot be reasoned about.
    const first = layoutNeighborhood(GRAPH);
    const second = layoutNeighborhood(GRAPH);
    expect(first.nodes).toEqual(second.nodes);
  });

  it('does not depend on the order the engine returned nodes in', () => {
    const shuffled: Neighborhood = { ...GRAPH, nodes: [...GRAPH.nodes].reverse() };
    const a = layoutNeighborhood(GRAPH);
    const b = layoutNeighborhood(shuffled);
    const positionOf = (layout: typeof a, id: string) =>
      layout.nodes.find((item) => item.id === id)!;
    expect(positionOf(a, 'B')).toEqual(positionOf(b, 'B'));
  });

  it('marks inferred nodes and edges', () => {
    const inferred: Neighborhood = {
      nodes: [node('A', 'root', 0), node('P', 'page', 1, 0.9)],
      edges: [edge('A', 'P', 0.9)],
      truncated: false,
    };
    const layout = layoutNeighborhood(inferred);
    expect(layout.nodes.find((item) => item.id === 'P')!.inferred).toBe(true);
    expect(layout.edges[0].inferred).toBe(true);
  });

  it('drops an edge whose far end is not in the node set', () => {
    // Otherwise it renders as a line to nowhere.
    const dangling: Neighborhood = {
      nodes: [node('A', 'root', 0)],
      edges: [edge('A', 'MISSING')],
      truncated: false,
    };
    expect(layoutNeighborhood(dangling).edges).toHaveLength(0);
  });

  it('carries the truncation flag through', () => {
    expect(layoutNeighborhood({ ...GRAPH, truncated: true }).truncated).toBe(true);
  });

  it('survives an empty graph', () => {
    const layout = layoutNeighborhood({ nodes: [], edges: [], truncated: false });
    expect(layout.nodes).toHaveLength(0);
    expect(boundsOf(layout).width).toBeGreaterThan(0);
  });
});

describe('boundsOf', () => {
  it('covers every node with padding', () => {
    const layout = layoutNeighborhood(GRAPH);
    const bounds = boundsOf(layout, 50);
    for (const item of layout.nodes) {
      expect(item.x).toBeGreaterThanOrEqual(bounds.minX);
      expect(item.y).toBeGreaterThanOrEqual(bounds.minY);
      expect(item.x).toBeLessThanOrEqual(bounds.minX + bounds.width);
      expect(item.y).toBeLessThanOrEqual(bounds.minY + bounds.height);
    }
  });
});

// ---------------------------------------------------------------------------

function file(path: string): FileTreeItem {
  return {
    id: path,
    relative_path: path,
    extension: `.${path.split('.').pop() ?? ''}`,
    detected_type: 'sql',
    size_bytes: 10,
    analysis_status: 'analyzed',
    modified_at: null,
    is_modified: false,
    skip_reason: null,
  };
}

describe('buildFileTree', () => {
  it('nests by path segment', () => {
    const tree = buildFileTree([file('sql/a.sql'), file('sql/b.sql')]);
    expect(tree).toHaveLength(1);
    expect(tree[0].name).toBe('sql');
    expect(tree[0].isDirectory).toBe(true);
    expect(tree[0].children.map((node) => node.name)).toEqual(['a.sql', 'b.sql']);
  });

  it('handles files at the root', () => {
    const tree = buildFileTree([file('leeme.md')]);
    expect(tree[0].isDirectory).toBe(false);
    expect(tree[0].file).toBeDefined();
  });

  it('puts directories before files', () => {
    const tree = buildFileTree([file('zeta.sql'), file('alfa/x.sql')]);
    expect(tree.map((node) => node.name)).toEqual(['alfa', 'zeta.sql']);
  });

  it('nests several levels deep', () => {
    const tree = buildFileTree([file('a/b/c/d.sql')]);
    expect(tree[0].children[0].children[0].children[0].name).toBe('d.sql');
  });

  it('does not duplicate a shared directory', () => {
    const tree = buildFileTree([file('sql/a.sql'), file('sql/sub/b.sql')]);
    expect(tree).toHaveLength(1);
    expect(tree[0].children).toHaveLength(2);
  });

  it('survives an empty list', () => {
    expect(buildFileTree([])).toEqual([]);
  });

  it('lists every directory path', () => {
    const tree = buildFileTree([file('a/b/c.sql'), file('d/e.sql')]);
    expect(directoryPaths(tree).sort()).toEqual(['a', 'a/b', 'd']);
  });
});

describe('flattenTree', () => {
  const tree = buildFileTree([
    file('sql/a.sql'),
    file('sql/sub/b.sql'),
    file('raiz.sql'),
  ]);
  const paths = (rows: TreeRow[]) => rows.map((row) => row.node.path);

  it('shows a closed folder without its contents', () => {
    expect(paths(flattenTree(tree, () => false))).toEqual(['sql', 'raiz.sql']);
  });

  it('shows the children of an open folder', () => {
    expect(paths(flattenTree(tree, (node) => node.path === 'sql'))).toEqual([
      'sql',
      'sql/sub',
      'sql/a.sql',
      'raiz.sql',
    ]);
  });

  it('descends only where every level is open', () => {
    expect(paths(flattenTree(tree, () => true))).toEqual([
      'sql',
      'sql/sub',
      'sql/sub/b.sql',
      'sql/a.sql',
      'raiz.sql',
    ]);
  });

  it('records how deep each row sits, for the indent', () => {
    const rows = flattenTree(tree, () => true);
    expect(rows.find((row) => row.node.path === 'sql/sub/b.sql')?.depth).toBe(2);
  });

  it('an empty tree yields no rows', () => {
    expect(flattenTree([], () => true)).toEqual([]);
  });
});

describe('colorOf', () => {
  it('gives known types their own colour', () => {
    expect(colorOf('OracleTable')).not.toBe(colorOf('JasperReport'));
  });

  it('falls back for an unknown type', () => {
    expect(colorOf('AlgoNuevo')).toBeTruthy();
  });
});
