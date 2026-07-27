/**
 * In-memory stand-in for the engine.
 *
 * Used when the UI runs in a browser tab instead of the Tauri shell — during
 * `pnpm dev` on a machine without the native toolchain, and in unit tests. It
 * imitates the engine's *shape and timing*, including progress events and a
 * second analysis reporting no changes, so the UI's states can be exercised
 * without pretending to be a real analyzer.
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

import type { EngineClient } from './client';

const DEMO_FILES: Array<[string, string, number]> = [
  ['sql/guardar_inspeccion.sql', 'sql', 1284],
  ['sql/consulta_inspecciones.sql', 'sql', 962],
  ['reports/Usr-RptInspeccion.jrxml', 'jrxml', 3410],
  ['reports/images/checkboxOn.png', 'image', 72],
  ['moca/confirmar_inspeccion.mcmd', 'moca', 604],
  ['config/apex_inspeccion.json', 'json', 918],
];

function nowIso(): string {
  return new Date().toISOString();
}

function id(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 12).toUpperCase()}`;
}

export class MockEngineClient implements EngineClient {
  readonly isNative = false;

  private projects: Project[] = [];
  private runs = new Map<string, AnalysisRun[]>();
  private analysed = new Set<string>();
  private handlers = new Set<(event: ProgressEvent) => void>();
  private cancelled = new Set<string>();

  async status(): Promise<EngineStatus> {
    return {
      version: '0.1.0',
      database_path: '(memoria — modo navegador)',
      fts5_available: true,
      analyzers: [],
      projects: this.projects.length,
      entities: this.projects.length ? DEMO_FILES.length * 3 : 0,
      relationships: this.projects.length ? DEMO_FILES.length * 4 : 0,
      model_provider: 'disabled',
      offline: true,
    };
  }

  async listProjects(limit = 20): Promise<Project[]> {
    return this.projects.slice(0, limit);
  }

  async openProject(path: string, name?: string): Promise<Project> {
    const existing = this.projects.find((project) => project.root_path === path);
    if (existing) return existing;

    const project: Project = {
      id: id('PRJ'),
      name: name ?? path.split(/[/\\]/).filter(Boolean).pop() ?? path,
      root_path: path,
      project_type: 'unknown',
      status: 'created',
      created_at: nowIso(),
      updated_at: nowIso(),
      last_analysis_at: null,
      settings: {},
    };
    this.projects = [project, ...this.projects];
    return project;
  }

  async deleteProject(projectId: string): Promise<void> {
    this.projects = this.projects.filter((project) => project.id !== projectId);
    this.runs.delete(projectId);
    this.analysed.delete(projectId);
  }

  async projectStats(projectId: string): Promise<ProjectStats> {
    const done = this.analysed.has(projectId);
    return {
      project_id: projectId,
      files: DEMO_FILES.length,
      files_by_status: done
        ? { analyzed: DEMO_FILES.length - 1, pending: 1 }
        : { pending: DEMO_FILES.length },
      files_by_extension: { '.sql': 2, '.jrxml': 1, '.mcmd': 1, '.json': 1, '.png': 1 },
      entities: done ? 18 : 0,
      entities_by_type: done ? { File: 5, OracleTable: 6, ApexItem: 4, SqlQuery: 3 } : {},
      relationships: done ? 24 : 0,
      relationships_by_type: done
        ? { FILE_CONTAINS_ENTITY: 18, QUERY_READS_TABLE: 4, QUERY_WRITES_TABLE: 2 }
        : {},
      evidence: done ? 42 : 0,
      errors: 0,
      last_analysis_at: done ? nowIso() : null,
    };
  }

  async projectFiles(projectId: string): Promise<FileTreeItem[]> {
    const done = this.analysed.has(projectId);
    return DEMO_FILES.map(([path, type, size]) => ({
      id: id('FIL'),
      relative_path: path,
      extension: `.${path.split('.').pop() ?? ''}`,
      detected_type: type,
      size_bytes: size,
      analysis_status: type === 'image' ? 'pending' : done ? 'analyzed' : 'pending',
      modified_at: nowIso(),
      is_modified: !done && type !== 'image',
      skip_reason: type === 'image' ? 'binary' : null,
    }));
  }

  async scanPolicy(): Promise<ScanPolicy> {
    return {
      ignored_directories: [
        '.git',
        'node_modules',
        'target',
        'dist',
        'build',
        '.next',
        '.venv',
        'venv',
        '__pycache__',
        '.idea',
        '.vscode',
        'coverage',
      ],
      ignored_files: ['*.pyc', '*.class', '.DS_Store'],
      max_file_size_bytes: 5 * 1024 * 1024,
      max_depth: 24,
      follow_symlinks: false,
      hash_binary_files: true,
      extra_ignored_directories: [],
    };
  }

  async analyze(projectId: string): Promise<AnalysisRun> {
    this.cancelled.delete(projectId);
    const first = !this.analysed.has(projectId);
    const runId = id('RUN');
    const startedAt = nowIso();

    const emit = (
      phase: ProgressEvent['phase'],
      current: number,
      total: number,
      message: string,
    ) => {
      for (const handler of this.handlers) {
        handler({ project_id: projectId, run_id: runId, phase, current, total, message });
      }
    };

    emit('scanning', 0, 0, 'Escaneando carpeta');
    await delay(120);
    emit('diffing', 0, 0, 'Comparando con el análisis anterior');
    await delay(80);

    for (let index = 0; index < DEMO_FILES.length; index += 1) {
      if (this.cancelled.has(projectId)) break;
      emit('analyzing', index + 1, DEMO_FILES.length, DEMO_FILES[index][0]);
      await delay(90);
    }

    const wasCancelled = this.cancelled.delete(projectId);
    emit('finalizing', 0, 0, 'Actualizando el proyecto');

    const run: AnalysisRun = {
      id: runId,
      project_id: projectId,
      status: wasCancelled ? 'cancelled' : 'completed',
      trigger: 'manual',
      started_at: startedAt,
      finished_at: nowIso(),
      files_scanned: DEMO_FILES.length,
      files_added: first ? DEMO_FILES.length : 0,
      files_modified: 0,
      files_deleted: 0,
      files_unchanged: first ? 0 : DEMO_FILES.length,
      files_analyzed: first ? DEMO_FILES.length - 1 : 0,
      files_skipped: 1,
      entities_created: first ? 18 : 0,
      relationships_created: first ? 24 : 0,
      error_count: 0,
      message: wasCancelled ? 'Cancelado por el usuario' : null,
    };

    if (!wasCancelled) {
      this.analysed.add(projectId);
      const project = this.projects.find((item) => item.id === projectId);
      if (project) {
        project.last_analysis_at = run.finished_at;
        project.status = 'ready';
        project.project_type = 'oracle-jasper';
      }
    }

    this.runs.set(projectId, [run, ...(this.runs.get(projectId) ?? [])]);
    return run;
  }

  async cancelAnalysis(projectId: string): Promise<void> {
    this.cancelled.add(projectId);
  }

  async analysisHistory(projectId: string, limit = 25): Promise<AnalysisRun[]> {
    return (this.runs.get(projectId) ?? []).slice(0, limit);
  }

  async pickFolder(): Promise<string | null> {
    // No OS dialog in a browser tab; a fixed demo path keeps the flow walkable.
    return '/demo/proyecto-inspecciones';
  }

  onProgress(handler: (event: ProgressEvent) => void): () => void {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
