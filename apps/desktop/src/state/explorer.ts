/**
 * Explorer state: what is selected, what the graph shows, what search found.
 *
 * Kept separate from the home-screen store because the lifetimes differ. The
 * home store holds one engine and a project list for the whole session; this
 * one is scoped to exploring a single project and is reset when the project
 * changes.
 *
 * The graph grows by *expansion*, never by loading everything: opening an entity
 * fetches its immediate neighbours, and expanding a node merges one more ring
 * into what is already on screen. A project with hundreds of thousands of
 * relationships must never arrive in one payload.
 */

import { create } from 'zustand';

import type {
  AnalysisIssue,
  ChangesResult,
  EntityHit,
  FileTreeItem,
  Neighborhood,
  UsageHit,
} from '@hana/shared-types';

import { getClient } from '../api/client';

export type CenterTab = 'graph' | 'code' | 'file' | 'issues' | 'changes';

interface ExplorerState {
  projectId: string | null;
  files: FileTreeItem[];

  searchText: string;
  searchResults: EntityHit[];
  searching: boolean;

  selected: EntityHit | null;
  incoming: UsageHit[];
  outgoing: UsageHit[];
  loadingDetails: boolean;

  graph: Neighborhood | null;
  expanded: Set<string>;
  loadingGraph: boolean;

  selectedFile: FileTreeItem | null;
  fileEntities: EntityHit[];
  fileTables: UsageHit[];

  /** Loaded source for the viewer, plus the range to reveal. */
  source: { path: string; content: string } | null;
  loadingSource: boolean;
  highlight: { start: number; end: number } | null;

  issues: AnalysisIssue[];
  changes: ChangesResult | null;
  tab: CenterTab;
  error: string | null;

  open: (projectId: string) => Promise<void>;
  reset: () => void;
  setTab: (tab: CenterTab) => void;
  search: (text: string) => Promise<void>;
  selectEntity: (entity: EntityHit) => Promise<void>;
  expandNode: (entityId: string) => Promise<void>;
  selectFile: (file: FileTreeItem) => Promise<void>;
  /** Open a file at a line — the click target behind every piece of evidence. */
  openEvidence: (
    relativePath: string,
    startLine?: number | null,
    endLine?: number | null,
  ) => Promise<void>;
  dismissError: () => void;
}

function describe(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return 'Error desconocido del motor';
}

/** Merge a freshly fetched ring into the graph already on screen. */
export function mergeNeighborhood(
  current: Neighborhood | null,
  incoming: Neighborhood,
): Neighborhood {
  if (!current) return incoming;

  const nodes = new Map(current.nodes.map((node) => [node.entity.id, node]));
  for (const node of incoming.nodes) {
    const existing = nodes.get(node.entity.id);
    // Keep the shallowest depth seen: a node reached again from further away is
    // still as close as it ever was, and its ring must not drift outward.
    if (!existing || node.depth < existing.depth) {
      nodes.set(node.entity.id, existing ? { ...node, depth: Math.min(existing.depth, node.depth) } : node);
    }
  }

  const edges = new Map(
    current.edges.map((edge) => [
      `${edge.source_id}|${edge.relation_type}|${edge.target_id}`,
      edge,
    ]),
  );
  for (const edge of incoming.edges) {
    edges.set(`${edge.source_id}|${edge.relation_type}|${edge.target_id}`, edge);
  }

  const known = new Set(nodes.keys());
  return {
    nodes: [...nodes.values()],
    // An edge whose far end never arrived would draw a line to nowhere.
    edges: [...edges.values()].filter(
      (edge) => known.has(edge.source_id) && known.has(edge.target_id),
    ),
    truncated: current.truncated || incoming.truncated,
  };
}

const EMPTY = {
  files: [] as FileTreeItem[],
  searchText: '',
  searchResults: [] as EntityHit[],
  searching: false,
  selected: null,
  incoming: [] as UsageHit[],
  outgoing: [] as UsageHit[],
  loadingDetails: false,
  graph: null,
  expanded: new Set<string>(),
  loadingGraph: false,
  selectedFile: null,
  fileEntities: [] as EntityHit[],
  fileTables: [] as UsageHit[],
  source: null,
  loadingSource: false,
  highlight: null,
  issues: [] as AnalysisIssue[],
  changes: null,
  tab: 'graph' as CenterTab,
  error: null,
};

export const useExplorerStore = create<ExplorerState>((set, get) => ({
  projectId: null,
  ...EMPTY,

  async open(projectId: string) {
    set({ projectId, ...EMPTY, expanded: new Set<string>() });
    try {
      const client = await getClient();
      const [files, issues, changes] = await Promise.all([
        client.projectFiles(projectId),
        client.issues(projectId),
        client.changes(projectId),
      ]);
      set({ files, issues, changes });
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  reset() {
    set({ projectId: null, ...EMPTY, expanded: new Set<string>() });
  },

  setTab(tab: CenterTab) {
    set({ tab });
  },

  async search(text: string) {
    set({ searchText: text });
    const projectId = get().projectId;
    if (!projectId || !text.trim()) {
      set({ searchResults: [], searching: false });
      return;
    }
    set({ searching: true });
    try {
      const client = await getClient();
      const results = await client.search(projectId, text, 60);
      // A slower earlier search must not overwrite a newer one's results.
      if (get().searchText === text) set({ searchResults: results });
    } catch (error) {
      set({ error: describe(error) });
    } finally {
      set({ searching: false });
    }
  },

  async selectEntity(entity: EntityHit) {
    set({
      selected: entity,
      loadingDetails: true,
      loadingGraph: true,
      tab: 'graph',
      // A new focus starts a new picture; keeping the old one would mix two
      // unrelated neighbourhoods into one misleading graph.
      graph: null,
      expanded: new Set<string>([entity.id]),
    });
    try {
      const client = await getClient();
      const [incoming, outgoing, graph] = await Promise.all([
        client.dependents(entity.id),
        client.dependencies(entity.id),
        client.neighborhood(entity.id, 1),
      ]);
      set({ incoming, outgoing, graph });
    } catch (error) {
      set({ error: describe(error) });
    } finally {
      set({ loadingDetails: false, loadingGraph: false });
    }
  },

  async expandNode(entityId: string) {
    if (get().expanded.has(entityId)) return;
    set({ loadingGraph: true });
    try {
      const client = await getClient();
      const extra = await client.neighborhood(entityId, 1);
      set((state) => ({
        graph: mergeNeighborhood(state.graph, extra),
        expanded: new Set(state.expanded).add(entityId),
      }));
    } catch (error) {
      set({ error: describe(error) });
    } finally {
      set({ loadingGraph: false });
    }
  },

  async selectFile(file: FileTreeItem) {
    set({ selectedFile: file, tab: 'file' });
    const projectId = get().projectId;
    if (!projectId) return;
    try {
      const client = await getClient();
      const [entities, tables] = await Promise.all([
        client.entitiesInFile(projectId, file.relative_path),
        client.tablesOfFile(projectId, file.relative_path),
      ]);
      set({ fileEntities: entities, fileTables: tables });
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  async openEvidence(relativePath, startLine, endLine) {
    const projectId = get().projectId;
    if (!projectId || !relativePath) return;

    const start = startLine && startLine >= 1 ? startLine : null;
    set({
      tab: 'code',
      highlight: start ? { start, end: Math.max(start, endLine ?? start) } : null,
    });

    // Already loaded: only the highlight moves. Re-reading the file to jump
    // three lines would be wasteful and would flicker the viewer.
    if (get().source?.path === relativePath) return;

    set({ loadingSource: true });
    try {
      const client = await getClient();
      const file = await client.readFile(projectId, relativePath);
      set({ source: { path: relativePath, content: file.content } });
    } catch (error) {
      set({ error: describe(error), source: null });
    } finally {
      set({ loadingSource: false });
    }
  },

  dismissError() {
    set({ error: null });
  },
}));
