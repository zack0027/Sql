/**
 * The single door between the UI and the engine.
 *
 * The React tree never calls `invoke` directly. It depends on {@link EngineClient},
 * which has two implementations: the Tauri one that talks to the native host, and
 * a mock used when the app runs in a plain browser (`pnpm dev` without Tauri,
 * and the unit tests). Keeping this seam means the UI can be developed and tested
 * on a machine where the native shell does not build.
 */

import type {
  AnalysisRun,
  EngineStatus,
  FileTreeItem,
  ProgressEvent,
  Project,
  ProjectStats,
  ScanPolicy,
} from '@hana/shared-types';

export interface EngineClient {
  /** True when a real engine is behind this client. */
  readonly isNative: boolean;

  status(): Promise<EngineStatus>;
  listProjects(limit?: number): Promise<Project[]>;
  openProject(path: string, name?: string): Promise<Project>;
  deleteProject(projectId: string): Promise<void>;

  projectStats(projectId: string): Promise<ProjectStats>;
  projectFiles(projectId: string): Promise<FileTreeItem[]>;
  scanPolicy(projectId: string): Promise<ScanPolicy>;

  analyze(projectId: string): Promise<AnalysisRun>;
  cancelAnalysis(projectId: string): Promise<void>;
  analysisHistory(projectId: string, limit?: number): Promise<AnalysisRun[]>;

  /** Ask the OS for a folder. Resolves to null when the user cancels. */
  pickFolder(): Promise<string | null>;

  /** Subscribe to analysis progress. Returns an unsubscribe function. */
  onProgress(handler: (event: ProgressEvent) => void): () => void;
}

/** True when running inside the Tauri shell rather than a browser tab. */
export function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

class TauriEngineClient implements EngineClient {
  readonly isNative = true;

  private async call<T>(command: string, args?: Record<string, unknown>): Promise<T> {
    const { invoke } = await import('@tauri-apps/api/core');
    return invoke<T>(command, args);
  }

  status(): Promise<EngineStatus> {
    return this.call('engine_status');
  }

  listProjects(limit = 20): Promise<Project[]> {
    return this.call('list_projects', { limit });
  }

  openProject(path: string, name?: string): Promise<Project> {
    return this.call('open_project', { path, name: name ?? null });
  }

  deleteProject(projectId: string): Promise<void> {
    return this.call('delete_project', { projectId });
  }

  projectStats(projectId: string): Promise<ProjectStats> {
    return this.call('project_stats', { projectId });
  }

  projectFiles(projectId: string): Promise<FileTreeItem[]> {
    return this.call('project_files', { projectId });
  }

  scanPolicy(projectId: string): Promise<ScanPolicy> {
    return this.call('scan_policy', { projectId });
  }

  analyze(projectId: string): Promise<AnalysisRun> {
    return this.call('analyze_project', { projectId });
  }

  cancelAnalysis(projectId: string): Promise<void> {
    return this.call('cancel_analysis', { projectId });
  }

  analysisHistory(projectId: string, limit = 25): Promise<AnalysisRun[]> {
    return this.call('analysis_history', { projectId, limit });
  }

  async pickFolder(): Promise<string | null> {
    // The dialog plugin is the only component allowed to widen the sandbox: the
    // folder the user picks becomes an allowed root for this project.
    const { open } = await import('@tauri-apps/plugin-dialog');
    const selected = await open({ directory: true, multiple: false });
    return typeof selected === 'string' ? selected : null;
  }

  onProgress(handler: (event: ProgressEvent) => void): () => void {
    let dispose: (() => void) | undefined;
    let cancelled = false;

    void (async () => {
      const { listen } = await import('@tauri-apps/api/event');
      const unlisten = await listen<ProgressEvent>('hana://progress', (event) =>
        handler(event.payload),
      );
      if (cancelled) unlisten();
      else dispose = unlisten;
    })();

    return () => {
      cancelled = true;
      dispose?.();
    };
  }
}

let cached: EngineClient | undefined;

/** Return the client for the current environment, creating it once. */
export async function getClient(): Promise<EngineClient> {
  if (cached) return cached;
  if (isTauri()) {
    cached = new TauriEngineClient();
  } else {
    const { MockEngineClient } = await import('./mock');
    cached = new MockEngineClient();
  }
  return cached;
}

/** Test seam: force a specific client. */
export function setClient(client: EngineClient | undefined): void {
  cached = client;
}
