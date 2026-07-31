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
  Annotation,
  ChangesResult,
  EntityHit,
  ErModel,
  ComparisonReport,
  FileTreeItem,
  Freshness,
  ImpactReport,
  Neighborhood,
  OrphanReport,
  ReportStructure,
  UsageHit,
} from '@hana/shared-types';

import { getClient } from '../api/client';

export type CenterTab =
  | 'graph'
  | 'impact'
  | 'orphans'
  | 'compare'
  | 'er'
  | 'report'
  | 'code'
  | 'file'
  | 'issues'
  | 'changes';

/** Whether the centre panel describes the selection or the whole project. */
export type Scope = 'selection' | 'project';

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

  orphans: OrphanReport | null;
  loadingOrphans: boolean;

  /** The other project being diffed against, and the result. */
  compareAgainst: string | null;
  comparison: ComparisonReport | null;
  loadingComparison: boolean;

  /** Verdicts a person recorded, keyed by the id they currently point at. */
  annotations: Map<string, Annotation>;

  /** Transitive impact of the selection, and which entity it was computed for. */
  impact: ImpactReport | null;
  impactOf: string | null;
  impactDepth: number;
  impactReverse: boolean;
  loadingImpact: boolean;

  er: ErModel | null;
  /** Table the diagram is centred on; null when it shows the whole project. */
  erFocus: string | null;
  loadingEr: boolean;
  report: ReportStructure | null;
  loadingReport: boolean;

  /** Whether this project's knowledge predates the installed analyzers. */
  freshness: Freshness | null;

  /**
   * What the centre panel is describing.
   *
   * `'selection'` — everything follows what you clicked. `'project'` — the whole
   * project, which is what the tabs used to always show.
   */
  scope: Scope;

  tab: CenterTab;
  error: string | null;

  open: (projectId: string) => Promise<void>;
  reset: () => void;
  setTab: (tab: CenterTab) => void;
  setScope: (scope: Scope) => void;
  loadOrphans: () => Promise<void>;
  compareWith: (projectId: string) => Promise<void>;
  loadAnnotations: () => Promise<void>;
  annotate: (
    targetKind: 'entity' | 'relationship',
    targetId: string,
    verdict: 'confirmed' | 'rejected',
    note?: string,
  ) => Promise<void>;
  withdrawAnnotation: (
    targetKind: 'entity' | 'relationship',
    targetKey: string,
  ) => Promise<void>;
  loadImpact: () => Promise<void>;
  setImpactDepth: (depth: number) => void;
  toggleImpactDirection: () => void;
  loadEr: () => Promise<void>;
  loadReport: (entityId: string) => Promise<void>;
  search: (text: string) => Promise<void>;
  selectEntity: (entity: EntityHit) => Promise<void>;
  expandNode: (entityId: string) => Promise<void>;
  selectFile: (file: FileTreeItem) => Promise<void>;
  /** Open a file at a line — the click target behind every piece of evidence. */
  openEvidence: (
    relativePath: string,
    startLine?: number | null,
    endLine?: number | null,
    options?: { keepTab?: boolean },
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

/**
 * Which table the ER diagram should be centred on, if any.
 *
 * One function so that the entity selection and the file selection cannot
 * disagree about it — they each used to work it out, and whichever ran last won.
 *
 * Only a table can focus the diagram. Asking for the neighbours of an APEX item
 * would narrow it to nothing, and an empty diagram reads as a bug rather than as
 * "that is not a table".
 */
export function erFocusOf(state: {
  scope: Scope;
  selected: EntityHit | null;
  fileTables: UsageHit[];
}): string | null {
  if (state.scope !== 'selection') return null;
  if (state.selected?.entity_type === 'OracleTable') return state.selected.id;

  const fromFile = state.fileTables.find(
    (hit) => hit.entity.entity_type === 'OracleTable',
  );
  return fromFile ? fromFile.entity.id : null;
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
  orphans: null,
  loadingOrphans: false,
  compareAgainst: null,
  comparison: null,
  loadingComparison: false,
  annotations: new Map<string, Annotation>(),
  impact: null,
  impactOf: null,
  impactDepth: 4,
  impactReverse: false,
  loadingImpact: false,
  er: null,
  erFocus: null,
  loadingEr: false,
  report: null,
  loadingReport: false,
  freshness: null,
  scope: 'selection' as Scope,
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
      const [files, issues, changes, freshness] = await Promise.all([
        client.projectFiles(projectId),
        client.issues(projectId),
        client.changes(projectId),
        client.freshness(projectId),
      ]);
      set({ files, issues, changes, freshness });
      await get().loadAnnotations();
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  reset() {
    set({ projectId: null, ...EMPTY, expanded: new Set<string>() });
  },

  setTab(tab: CenterTab) {
    set({ tab });
    // Fetched only when opened: expensive enough to be worth the delay, and
    // cheap enough to keep afterwards.
    if (tab === 'er' && !get().er && !get().loadingEr) void get().loadEr();
    if (tab === 'impact' && get().impactOf !== get().selected?.id) {
      void get().loadImpact();
    }
    if (tab === 'orphans' && !get().orphans && !get().loadingOrphans) {
      void get().loadOrphans();
    }
  },

  async compareWith(projectId: string) {
    const mine = get().projectId;
    if (!mine) return;
    if (!projectId) {
      set({ compareAgainst: null, comparison: null });
      return;
    }
    set({ compareAgainst: projectId, loadingComparison: true });
    try {
      const client = await getClient();
      const report = await client.compare(mine, projectId);
      // A slower earlier request must not overwrite a newer choice's answer.
      if (get().compareAgainst === projectId) set({ comparison: report });
    } catch (error) {
      set({ error: describe(error), comparison: null });
    } finally {
      set({ loadingComparison: false });
    }
  },

  async loadOrphans() {
    const projectId = get().projectId;
    if (!projectId) return;
    set({ loadingOrphans: true });
    try {
      const client = await getClient();
      set({ orphans: await client.orphans(projectId) });
    } catch (error) {
      set({ error: describe(error) });
    } finally {
      set({ loadingOrphans: false });
    }
  },

  async loadAnnotations() {
    const projectId = get().projectId;
    if (!projectId) return;
    try {
      const client = await getClient();
      const stored = await client.annotations(projectId);
      const byId = new Map<string, Annotation>();
      for (const item of stored) {
        // Keyed by what it currently points at. One that matches nothing has
        // nothing on screen to attach to, and is not dropped from the engine.
        if (item.resolved_id) byId.set(item.resolved_id, item);
      }
      set({ annotations: byId });
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  async annotate(targetKind, targetId, verdict, note) {
    const projectId = get().projectId;
    if (!projectId) return;
    try {
      const client = await getClient();
      await client.setAnnotation(projectId, targetKind, targetId, verdict, note);
      await get().loadAnnotations();
      // The verdict changes `verification_status` on the row, so whatever is
      // on screen is now describing the old value.
      const selected = get().selected;
      if (selected) {
        const refreshed = await client.entity(selected.id);
        if (refreshed) set({ selected: refreshed });
      }
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  async withdrawAnnotation(targetKind, targetKey) {
    const projectId = get().projectId;
    if (!projectId) return;
    try {
      const client = await getClient();
      await client.clearAnnotation(projectId, targetKind, targetKey);
      await get().loadAnnotations();
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  async loadImpact() {
    const entity = get().selected;
    if (!entity) {
      set({ impact: null, impactOf: null });
      return;
    }
    const target = entity.id;
    set({ loadingImpact: true, impactOf: target });
    try {
      const client = await getClient();
      const report = await client.impact(target, {
        depth: get().impactDepth,
        direction: get().impactReverse ? 'outgoing' : 'incoming',
      });
      // A slower earlier request must not overwrite a newer selection's answer.
      if (get().impactOf === target) set({ impact: report });
    } catch (error) {
      set({ error: describe(error), impact: null });
    } finally {
      set({ loadingImpact: false });
    }
  },

  setImpactDepth(depth: number) {
    if (get().impactDepth === depth) return;
    set({ impactDepth: depth });
    if (get().tab === 'impact') void get().loadImpact();
  },

  toggleImpactDirection() {
    set({ impactReverse: !get().impactReverse });
    if (get().tab === 'impact') void get().loadImpact();
  },

  setScope(scope: Scope) {
    if (get().scope === scope) return;
    // The ER model is the one view whose *contents* come from the engine rather
    // than being filtered here, so widening or narrowing means asking again.
    set({ scope, er: null });
    if (get().tab === 'er') void get().loadEr();
  },

  async loadEr() {
    const projectId = get().projectId;
    if (!projectId) return;

    const focus = erFocusOf(get());
    set({ loadingEr: true, erFocus: focus });
    try {
      const client = await getClient();
      const model = await client.erModel(projectId, undefined, focus);
      // A slower earlier request must not overwrite a newer selection's answer.
      if (get().erFocus === focus) set({ er: model });
    } catch (error) {
      set({ error: describe(error) });
    } finally {
      set({ loadingEr: false });
    }
  },

  async loadReport(entityId: string) {
    set({ loadingReport: true, tab: 'report' });
    try {
      const client = await getClient();
      set({ report: await client.reportStructure(entityId) });
    } catch (error) {
      set({ error: describe(error), report: null });
    } finally {
      set({ loadingReport: false });
    }
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

      // Selecting a report loads its bands too, so the preview is ready the
      // moment the tab is opened rather than after a second wait.
      if (entity.entity_type === 'JasperReport') {
        const structure = await client.reportStructure(entity.id);
        set({ report: structure });
      }

      // Every other tab follows the selection as well. The diagram is refetched
      // because only the engine can say which tables this one joins; the file
      // is opened at the line where the entity is defined, so the code tab is
      // showing the same thing the graph is.
      if (get().scope === 'selection') {
        set({ er: null, impact: null, impactOf: null });
        if (get().tab === 'er') void get().loadEr();
        if (get().tab === 'impact') void get().loadImpact();
        if (entity.file_path) {
          void get().openEvidence(entity.file_path, entity.start_line, null, {
            keepTab: true,
          });
        }
      }
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
    set({ selectedFile: file, tab: 'file', highlight: null });
    const projectId = get().projectId;
    if (!projectId) return;
    try {
      const client = await getClient();
      const [entities, tables] = await Promise.all([
        client.entitiesInFile(projectId, file.relative_path),
        client.tablesOfFile(projectId, file.relative_path),
      ]);
      set({ fileEntities: entities, fileTables: tables });

      if (get().scope !== 'selection') return;

      // Load the source now, so the code tab is showing this file the moment
      // it is opened. Skipped for anything the viewer cannot render as text —
      // a compiled .jasper or a PNG would arrive as a screen of mojibake.
      if (!file.skip_reason) {
        void get().openEvidence(file.relative_path, null, null, { keepTab: true });
      } else {
        set({ source: null });
      }

      // The diagram follows too, centred on whichever table this file uses.
      set({ er: null });
      if (get().tab === 'er') void get().loadEr();
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  async openEvidence(relativePath, startLine, endLine, options) {
    const projectId = get().projectId;
    if (!projectId || !relativePath) return;

    const start = startLine && startLine >= 1 ? startLine : null;
    set({
      // Clicking a piece of evidence *means* "show me the code"; loading it
      // behind a selection does not, and stealing the tab would yank the user
      // away from the graph they were reading.
      ...(options?.keepTab ? {} : { tab: 'code' as CenterTab }),
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
