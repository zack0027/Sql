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
  AnalysisIssue,
  AnalysisRun,
  ChangesResult,
  EngineStatus,
  EntityHit,
  EntityType,
  ErModel,
  FileTreeItem,
  Neighborhood,
  ReportStructure,
  ProgressEvent,
  Project,
  ProjectStats,
  ScanPolicy,
  UsageHit,
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

  // -- the answering layer -------------------------------------------------
  // Every one of these is read-only and returns evidence alongside the answer.

  search(projectId: string, text: string, limit?: number): Promise<EntityHit[]>;
  entity(entityId: string): Promise<EntityHit | null>;
  uses(entityId: string, includeStructural?: boolean): Promise<UsageHit[]>;
  dependents(entityId: string): Promise<UsageHit[]>;
  dependencies(entityId: string): Promise<UsageHit[]>;
  tablesOfFile(
    projectId: string,
    relativePath: string,
    written?: boolean | null,
  ): Promise<UsageHit[]>;
  entitiesInFile(
    projectId: string,
    relativePath: string,
    entityType?: EntityType,
  ): Promise<EntityHit[]>;
  reportsUsingTable(entityId: string): Promise<UsageHit[]>;
  imagesOfReport(entityId: string): Promise<UsageHit[]>;
  changes(projectId: string, runId?: string): Promise<ChangesResult>;
  issues(projectId: string, severity?: string): Promise<AnalysisIssue[]>;
  lowConfidence(projectId: string, threshold?: number): Promise<EntityHit[]>;
  neighborhood(entityId: string, depth?: number): Promise<Neighborhood>;
  /** Tables, columns and the joins that relate them. */
  erModel(projectId: string, tableIds?: string[]): Promise<ErModel>;
  /** A Jasper report broken down into its bands. */
  reportStructure(entityId: string): Promise<ReportStructure | null>;

  /**
   * Read one file of an open project, for the viewer.
   *
   * Goes through the host's boundary check, not straight to disk: a path the
   * webview knows is not permission to read it.
   */
  readFile(projectId: string, relativePath: string): Promise<FileContent>;

  /** Ask the OS for a folder. Resolves to null when the user cancels. */
  pickFolder(): Promise<string | null>;

  /** Subscribe to analysis progress. Returns an unsubscribe function. */
  onProgress(handler: (event: ProgressEvent) => void): () => void;
}

export interface FileContent {
  relative_path: string;
  absolute_path: string;
  size_bytes: number;
  content: string;
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

  /** Every query goes through one allowlisted host command. */
  private query<T>(method: string, params: Record<string, unknown>): Promise<T> {
    return this.call<T>('run_query', { method, params });
  }

  search(projectId: string, text: string, limit = 50): Promise<EntityHit[]> {
    return this.query('query.search', { project_id: projectId, text, limit });
  }

  entity(entityId: string): Promise<EntityHit | null> {
    return this.query('query.entity', { entity_id: entityId });
  }

  uses(entityId: string, includeStructural = false): Promise<UsageHit[]> {
    return this.query('query.uses', {
      entity_id: entityId,
      include_structural: includeStructural,
    });
  }

  dependents(entityId: string): Promise<UsageHit[]> {
    return this.query('query.dependents', { entity_id: entityId });
  }

  dependencies(entityId: string): Promise<UsageHit[]> {
    return this.query('query.dependencies', { entity_id: entityId });
  }

  tablesOfFile(
    projectId: string,
    relativePath: string,
    written: boolean | null = null,
  ): Promise<UsageHit[]> {
    return this.query('query.tables_of_file', {
      project_id: projectId,
      relative_path: relativePath,
      written,
    });
  }

  entitiesInFile(
    projectId: string,
    relativePath: string,
    entityType?: EntityType,
  ): Promise<EntityHit[]> {
    return this.query('query.entities_in_file', {
      project_id: projectId,
      relative_path: relativePath,
      entity_type: entityType ?? null,
    });
  }

  reportsUsingTable(entityId: string): Promise<UsageHit[]> {
    return this.query('query.reports_using_table', { entity_id: entityId });
  }

  imagesOfReport(entityId: string): Promise<UsageHit[]> {
    return this.query('query.images_of_report', { entity_id: entityId });
  }

  changes(projectId: string, runId?: string): Promise<ChangesResult> {
    return this.query('query.changes', {
      project_id: projectId,
      run_id: runId ?? null,
    });
  }

  issues(projectId: string, severity?: string): Promise<AnalysisIssue[]> {
    return this.query('query.errors', {
      project_id: projectId,
      severity: severity ?? null,
    });
  }

  lowConfidence(projectId: string, threshold = 0.8): Promise<EntityHit[]> {
    return this.query('query.low_confidence', {
      project_id: projectId,
      threshold,
    });
  }

  neighborhood(entityId: string, depth = 1): Promise<Neighborhood> {
    return this.query('query.neighborhood', { entity_id: entityId, depth });
  }

  erModel(projectId: string, tableIds?: string[]): Promise<ErModel> {
    return this.query('query.er_model', {
      project_id: projectId,
      table_ids: tableIds ?? null,
    });
  }

  reportStructure(entityId: string): Promise<ReportStructure | null> {
    return this.query('query.report_structure', { entity_id: entityId });
  }

  readFile(projectId: string, relativePath: string): Promise<FileContent> {
    return this.call('read_project_file', {
      projectId,
      relativePath,
    });
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
