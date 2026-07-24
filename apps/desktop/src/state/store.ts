/**
 * Global application state.
 *
 * The store holds what the UI needs to render and nothing else: no domain rules,
 * no derived knowledge. Every mutation goes through an action that talks to the
 * {@link EngineClient}, so a component never touches the engine directly.
 */

import { create } from 'zustand';

import type {
  AnalysisRun,
  EngineStatus,
  FileTreeItem,
  ProgressEvent,
  Project,
  ProjectStats,
} from '@jarvis/shared-types';

import { getClient } from '../api/client';

export interface AnalysisProgress {
  phase: ProgressEvent['phase'];
  current: number;
  total: number;
  message: string;
}

interface AppState {
  ready: boolean;
  native: boolean;
  engine: EngineStatus | null;
  projects: Project[];
  activeProjectId: string | null;
  stats: Record<string, ProjectStats>;
  files: Record<string, FileTreeItem[]>;
  history: Record<string, AnalysisRun[]>;
  progress: AnalysisProgress | null;
  analyzing: boolean;
  lastRun: AnalysisRun | null;
  error: string | null;

  initialize: () => Promise<void>;
  refreshStatus: () => Promise<void>;
  refreshProjects: () => Promise<void>;
  openFolder: () => Promise<Project | null>;
  openPath: (path: string) => Promise<Project | null>;
  selectProject: (projectId: string | null) => Promise<void>;
  analyze: (projectId: string) => Promise<void>;
  cancelAnalysis: () => Promise<void>;
  removeProject: (projectId: string) => Promise<void>;
  dismissError: () => void;
}

/** Turn anything thrown into a message the UI can show. */
function describe(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return 'Error desconocido del motor';
}

export const useAppStore = create<AppState>((set, get) => ({
  ready: false,
  native: false,
  engine: null,
  projects: [],
  activeProjectId: null,
  stats: {},
  files: {},
  history: {},
  progress: null,
  analyzing: false,
  lastRun: null,
  error: null,

  async initialize() {
    try {
      const client = await getClient();
      // Subscribing before the first analysis means no early event is missed.
      client.onProgress((event) => {
        set({
          progress: {
            phase: event.phase,
            current: event.current,
            total: event.total,
            message: event.message,
          },
        });
      });
      set({ native: client.isNative });
      await get().refreshStatus();
      await get().refreshProjects();
      set({ ready: true });
    } catch (error) {
      set({ ready: true, error: describe(error) });
    }
  },

  async refreshStatus() {
    try {
      const client = await getClient();
      set({ engine: await client.status() });
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  async refreshProjects() {
    try {
      const client = await getClient();
      set({ projects: await client.listProjects(20) });
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  async openFolder() {
    try {
      const client = await getClient();
      const path = await client.pickFolder();
      if (!path) return null;
      return await get().openPath(path);
    } catch (error) {
      set({ error: describe(error) });
      return null;
    }
  },

  async openPath(path: string) {
    try {
      const client = await getClient();
      const project = await client.openProject(path);
      await get().refreshProjects();
      await get().selectProject(project.id);
      return project;
    } catch (error) {
      set({ error: describe(error) });
      return null;
    }
  },

  async selectProject(projectId: string | null) {
    set({ activeProjectId: projectId });
    if (!projectId) return;
    try {
      const client = await getClient();
      const [stats, files, history] = await Promise.all([
        client.projectStats(projectId),
        client.projectFiles(projectId),
        client.analysisHistory(projectId, 10),
      ]);
      set((state) => ({
        stats: { ...state.stats, [projectId]: stats },
        files: { ...state.files, [projectId]: files },
        history: { ...state.history, [projectId]: history },
      }));
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  async analyze(projectId: string) {
    if (get().analyzing) return;
    set({ analyzing: true, progress: null, lastRun: null, error: null });
    try {
      const client = await getClient();
      const run = await client.analyze(projectId);
      set({ lastRun: run });
      await get().refreshStatus();
      await get().refreshProjects();
      await get().selectProject(projectId);
    } catch (error) {
      set({ error: describe(error) });
    } finally {
      set({ analyzing: false, progress: null });
    }
  },

  async cancelAnalysis() {
    const projectId = get().activeProjectId;
    if (!projectId) return;
    try {
      const client = await getClient();
      await client.cancelAnalysis(projectId);
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  async removeProject(projectId: string) {
    try {
      const client = await getClient();
      await client.deleteProject(projectId);
      if (get().activeProjectId === projectId) {
        set({ activeProjectId: null });
      }
      await get().refreshProjects();
      await get().refreshStatus();
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  dismissError() {
    set({ error: null });
  },
}));

/** The currently selected project, or null. */
export function useActiveProject(): Project | null {
  return useAppStore((state) =>
    state.projects.find((project) => project.id === state.activeProjectId) ?? null,
  );
}
