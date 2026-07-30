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
  AnalysisIssue,
  AnalysisRun,
  ChangesResult,
  EngineStatus,
  EntityHit,
  EntityType,
  ErModel,
  FileTreeItem,
  Freshness,
  GraphEdgeHit,
  Neighborhood,
  ReportStructure,
  ProgressEvent,
  Project,
  ProjectStats,
  ScanPolicy,
  UsageHit,
} from '@hana/shared-types';

import type { EngineClient, FileContent } from './client';

/** Stands in for the analyzer suite fingerprint; the demo is never stale. */
const DEMO_SUITE = 'apex@1;code@1;jrxml@3;json@1;moca@1;sql@2';

const DEMO_FILES: Array<[string, string, number]> = [
  ['sql/guardar_inspeccion.sql', 'sql', 1284],
  ['sql/consulta_inspecciones.sql', 'sql', 962],
  ['reports/Usr-RptInspeccion.jrxml', 'jrxml', 3410],
  ['reports/images/checkboxOn.png', 'image', 72],
  ['moca/confirmar_inspeccion.mcmd', 'moca', 604],
  ['config/apex_inspeccion.json', 'json', 918],
];

function entity(
  entityId: string,
  type: EntityType,
  name: string,
  file: string | null,
  line: number | null,
  confidence = 1,
  qualified: string | null = null,
): EntityHit {
  return {
    id: entityId,
    entity_type: type,
    name,
    normalized_name: name.toUpperCase(),
    qualified_name: qualified,
    confidence,
    verification_status: confidence >= 1 ? 'confirmed' : 'inferred',
    file_path: file,
    start_line: line,
  };
}

/** The fixture graph in miniature: item → column, script → table → report. */
const DEMO_ENTITIES: EntityHit[] = [
  entity('E_TABLE', 'OracleTable', 'UC_INSP_ENT', 'sql/guardar_inspeccion.sql', 11),
  entity(
    'E_COLUMN',
    'OracleColumn',
    'MUESTRA_SIZE_VER',
    'sql/guardar_inspeccion.sql',
    18,
    1,
    'UC_INSP_ENT.MUESTRA_SIZE_VER',
  ),
  entity('E_ITEM', 'ApexItem', 'P117_MUESTRA_SIZE_VER', 'sql/guardar_inspeccion.sql', 21),
  // Inferred at 0.90: the page follows from a naming convention, not syntax.
  entity('E_PAGE', 'ApexPage', '117', 'sql/guardar_inspeccion.sql', 21, 0.9),
  entity('E_QUERY', 'SqlQuery', 'insert#2', 'sql/guardar_inspeccion.sql', 11),
  entity(
    'E_REPORT',
    'JasperReport',
    'Usr-RptInspeccion',
    'reports/Usr-RptInspeccion.jrxml',
    3,
  ),
  entity('E_IMAGE', 'File', 'images/checkboxOn.png', 'reports/Usr-RptInspeccion.jrxml', 41),
];

function edge(
  source: string,
  relation: GraphEdgeHit['relation_type'],
  target: string,
  file: string,
  line: number,
  snippet: string,
  confidence = 1,
): GraphEdgeHit {
  return {
    source_id: source,
    target_id: target,
    relation_type: relation,
    confidence,
    status: confidence >= 1 ? 'confirmed' : 'inferred',
    evidence: {
      file_path: file,
      absolute_path: `/demo/${file}`,
      start_line: line,
      end_line: line,
      snippet,
      analyzer: relation.startsWith('REPORT') ? 'jrxml' : 'sql',
      confidence,
      status: confidence >= 1 ? 'confirmed' : 'inferred',
    },
  };
}

const DEMO_EDGES: GraphEdgeHit[] = [
  edge('E_QUERY', 'QUERY_WRITES_TABLE', 'E_TABLE', 'sql/guardar_inspeccion.sql', 11,
    'insert into uc_insp_ent ('),
  edge('E_QUERY', 'QUERY_USES_COLUMN', 'E_COLUMN', 'sql/guardar_inspeccion.sql', 18,
    'muestra_size_ver'),
  edge('E_ITEM', 'APEX_ITEM_MAPS_TO_COLUMN', 'E_COLUMN', 'sql/guardar_inspeccion.sql', 18,
    'insert into uc_insp_ent (... muestra_size_ver) values (... :P117_MUESTRA_SIZE_VER)'),
  edge('E_PAGE', 'APEX_PAGE_CONTAINS_ITEM', 'E_ITEM', 'sql/guardar_inspeccion.sql', 21,
    ':P117_MUESTRA_SIZE_VER', 0.9),
  edge('E_REPORT', 'REPORT_QUERIES_TABLE', 'E_TABLE', 'reports/Usr-RptInspeccion.jrxml', 22,
    'from uc_insp_ent e'),
  edge('E_REPORT', 'REPORT_REFERENCES_IMAGE', 'E_IMAGE', 'reports/Usr-RptInspeccion.jrxml', 41,
    'images/checkboxOn.png'),
];

/** Enough real source for the viewer to have something to highlight. */
const DEMO_SOURCES: Record<string, string> = {
  'sql/guardar_inspeccion.sql': [
    'declare',
    '    l_numctl  uc_insp_ent.numctl%type;',
    "    l_usuario varchar2(30) := :APP_USER;",
    'begin',
    '    select seq_uc_insp_ent.nextval',
    '      into l_numctl',
    '      from dual;',
    '',
    '',
    '',
    '    insert into uc_insp_ent (',
    '        numctl,',
    '        prtnum,',
    '        muestra_size_ver,',
    '        netwgt,',
    '        usuario,',
    '        fecha_registro',
    '    ) values (',
    '        l_numctl,',
    '        :P117_PRTNUM,',
    '        :P117_MUESTRA_SIZE_VER,',
    '        :P117_NETWGT,',
    '        l_usuario,',
    '        sysdate',
    '    );',
    'end;',
    '/',
  ].join('\n'),
  'reports/Usr-RptInspeccion.jrxml': [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<jasperReport name="Usr-RptInspeccion">',
    '    <parameter name="P_NUMCTL" class="java.lang.String"/>',
    '    <queryString>',
    '        <![CDATA[',
    '            select e.numctl,',
    '                   e.netwgt',
    '              from uc_insp_ent e',
    '        ]]>',
    '    </queryString>',
    '    <field name="numctl" class="java.lang.String"/>',
    '</jasperReport>',
  ].join('\n'),
};

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
  /** Set by the settings screen; null means "still the defaults". */
  private policy: ScanPolicy | null = null;

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

  async setScanPolicy(_projectId: string, policy: ScanPolicy): Promise<ScanPolicy> {
    this.policy = policy;
    return policy;
  }

  async scanPolicy(): Promise<ScanPolicy> {
    return this.policy ?? {
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

  // -- the answering layer -------------------------------------------------
  //
  // A small graph modelled on the fixtures: an APEX item feeding an Oracle
  // column, a table written by a script and read by a report. Small on purpose,
  // but shaped like the real thing so the views can be built and tested against
  // it — including the inferred APEX page, which must render differently from a
  // confirmed fact.

  async search(_projectId: string, text: string, limit = 50): Promise<EntityHit[]> {
    const needle = text.trim().toUpperCase();
    if (!needle) return [];
    return DEMO_ENTITIES.filter(
      (entity) =>
        entity.normalized_name.toUpperCase().includes(needle) ||
        (entity.qualified_name ?? '').toUpperCase().includes(needle),
    ).slice(0, limit);
  }

  async entity(entityId: string): Promise<EntityHit | null> {
    return DEMO_ENTITIES.find((item) => item.id === entityId) ?? null;
  }

  async uses(entityId: string, includeStructural = false): Promise<UsageHit[]> {
    return DEMO_EDGES.filter(
      (edge) => edge.source_id === entityId || edge.target_id === entityId,
    )
      .filter(
        (edge) =>
          includeStructural || edge.relation_type !== 'FILE_CONTAINS_ENTITY',
      )
      .map((edge) => this.usageOf(edge, entityId));
  }

  async dependents(entityId: string): Promise<UsageHit[]> {
    return DEMO_EDGES.filter((edge) => edge.target_id === entityId).map((edge) =>
      this.usageOf(edge, entityId),
    );
  }

  async dependencies(entityId: string): Promise<UsageHit[]> {
    return DEMO_EDGES.filter((edge) => edge.source_id === entityId).map((edge) =>
      this.usageOf(edge, entityId),
    );
  }

  async tablesOfFile(
    _projectId: string,
    relativePath: string,
    written: boolean | null = null,
  ): Promise<UsageHit[]> {
    return DEMO_EDGES.filter((edge) => {
      if (edge.evidence.file_path !== relativePath) return false;
      const isWrite = edge.relation_type === 'QUERY_WRITES_TABLE';
      const isRead =
        edge.relation_type === 'QUERY_READS_TABLE' ||
        edge.relation_type === 'REPORT_QUERIES_TABLE';
      if (written === true) return isWrite;
      if (written === false) return isRead;
      return isWrite || isRead;
    }).map((edge) => this.usageOf(edge, edge.source_id));
  }

  async entitiesInFile(
    _projectId: string,
    relativePath: string,
    entityType?: EntityType,
  ): Promise<EntityHit[]> {
    return DEMO_ENTITIES.filter(
      (entity) =>
        entity.file_path === relativePath &&
        (!entityType || entity.entity_type === entityType),
    );
  }

  async reportsUsingTable(entityId: string): Promise<UsageHit[]> {
    return DEMO_EDGES.filter(
      (edge) =>
        edge.target_id === entityId &&
        edge.relation_type === 'REPORT_QUERIES_TABLE',
    ).map((edge) => this.usageOf(edge, entityId));
  }

  async imagesOfReport(entityId: string): Promise<UsageHit[]> {
    return DEMO_EDGES.filter(
      (edge) =>
        edge.source_id === entityId &&
        edge.relation_type === 'REPORT_REFERENCES_IMAGE',
    ).map((edge) => this.usageOf(edge, entityId));
  }

  async changes(projectId: string): Promise<ChangesResult> {
    const analysed = this.analysed.has(projectId);
    return {
      run_id: analysed ? 'RUN_DEMO' : null,
      changes: analysed
        ? DEMO_FILES.map(([path, type]) => ({
            change_kind: 'added' as const,
            relative_path: path,
            absolute_path: `/demo/${path}`,
            detected_type: type,
            content_hash: 'a'.repeat(64),
            observed_at: nowIso(),
          }))
        : [],
    };
  }

  async issues(projectId: string): Promise<AnalysisIssue[]> {
    if (!this.analysed.has(projectId)) return [];
    return [
      {
        relative_path: 'reports/Usr-RptInspeccion.jrxml',
        absolute_path: '/demo/reports/Usr-RptInspeccion.jrxml',
        severity: 'warning',
        code: 'undeclared_field',
        message: 'el campo $F{campo_no_declarado} se usa pero no está declarado',
        analyzer: 'jrxml',
        observed_at: nowIso(),
      },
    ];
  }

  async lowConfidence(projectId: string, threshold = 0.8): Promise<EntityHit[]> {
    if (!this.analysed.has(projectId)) return [];
    return DEMO_ENTITIES.filter((entity) => entity.confidence < threshold);
  }

  async neighborhood(entityId: string, depth = 1): Promise<Neighborhood> {
    const seen = new Map<string, number>([[entityId, 0]]);
    let frontier = [entityId];

    for (let level = 1; level <= Math.max(1, depth); level += 1) {
      const next: string[] = [];
      for (const edge of DEMO_EDGES) {
        for (const [near, far] of [
          [edge.source_id, edge.target_id],
          [edge.target_id, edge.source_id],
        ]) {
          if (frontier.includes(near) && !seen.has(far)) {
            seen.set(far, level);
            next.push(far);
          }
        }
      }
      frontier = next;
    }

    const nodes = [...seen.entries()]
      .map(([id, nodeDepth]) => {
        const entity = DEMO_ENTITIES.find((item) => item.id === id);
        return entity ? { entity, depth: nodeDepth } : null;
      })
      .filter((node): node is { entity: EntityHit; depth: number } => node !== null);

    const known = new Set(nodes.map((node) => node.entity.id));
    return {
      nodes,
      edges: DEMO_EDGES.filter(
        (edge) => known.has(edge.source_id) && known.has(edge.target_id),
      ),
      truncated: false,
    };
  }

  async erModel(_projectId?: string, _tableIds?: string[], _focusId?: string | null): Promise<ErModel> {
    const table = (id: string, name: string, columns: string[]) => ({
      ...(DEMO_ENTITIES.find((item) => item.id === id) ??
        entity(id, 'OracleTable', name, null, null)),
      columns: columns.map((column, index) => ({
        id: `${id}_C${index}`,
        name: column,
        normalized_name: column.toUpperCase(),
        confidence: 1,
      })),
    });

    return {
      tables: [
        table('E_TABLE', 'UC_INSP_ENT', ['NUMCTL', 'PRTNUM', 'MUESTRA_SIZE_VER', 'NETWGT']),
        table('E_PRTMST', 'PRTMST', ['PRTNUM', 'PRTDSC']),
      ],
      links: [
        {
          source_id: 'E_TABLE',
          target_id: 'E_PRTMST',
          left_column: 'PRTNUM',
          right_column: 'PRTNUM',
          confidence: 1,
          status: 'confirmed',
          evidence: {
            file_path: 'sql/consulta_inspecciones.sql',
            absolute_path: '/demo/sql/consulta_inspecciones.sql',
            start_line: 17,
            end_line: 17,
            snippet: 'join prtmst p on p.prtnum = r.prtnum',
            analyzer: 'sql',
            confidence: 1,
            status: 'confirmed',
          },
        },
      ],
      derived_from: 'join_conditions',
    };
  }

  async reportStructure(entityId: string): Promise<ReportStructure | null> {
    if (entityId !== 'E_REPORT') return null;
    return {
      id: 'E_REPORT',
      name: 'Usr-RptInspeccion',
      file_path: 'reports/Usr-RptInspeccion.jrxml',
      absolute_path: '/demo/reports/Usr-RptInspeccion.jrxml',
      bands: [
        {
          section: 'title',
          group: null,
          height: 60,
          elements: [
            { kind: 'image', x: 0, y: 0, width: 24, height: 24,
              text: '"images/checkboxOn.png"', references: [] },
            { kind: 'textField', x: 30, y: 0, width: 300, height: 20,
              text: '$P{P_PRTNUM}', references: ['$P{P_PRTNUM}'] },
          ],
        },
        {
          section: 'detail',
          group: null,
          height: 40,
          elements: [
            { kind: 'textField', x: 0, y: 0, width: 120, height: 20,
              text: '$F{numctl}', references: ['$F{numctl}'] },
            { kind: 'textField', x: 130, y: 0, width: 120, height: 20,
              text: '$F{muestra_size_ver}', references: ['$F{muestra_size_ver}'] },
            { kind: 'subreport', x: 0, y: 22, width: 555, height: 18,
              text: '"Usr-RptInspeccionDetalle.jasper"', references: [] },
          ],
        },
        {
          section: 'summary',
          group: null,
          height: 30,
          elements: [
            { kind: 'textField', x: 0, y: 0, width: 200, height: 20,
              text: '$V{V_TOTAL_NETWGT}', references: ['$V{V_TOTAL_NETWGT}'] },
          ],
        },
      ],
      analyzed_by: DEMO_SUITE,
      stale: false,
    };
  }

  async freshness(): Promise<Freshness> {
    return {
      suite: DEMO_SUITE,
      analyzed: 4,
      stale: 0,
      by_suite: { [DEMO_SUITE]: 4 },
    };
  }

  private usageOf(edge: GraphEdgeHit, from: string): UsageHit {
    const otherId = edge.source_id === from ? edge.target_id : edge.source_id;
    const entity =
      DEMO_ENTITIES.find((item) => item.id === otherId) ?? DEMO_ENTITIES[0];
    return {
      entity,
      relation_type: edge.relation_type,
      direction: edge.source_id === from ? 'outgoing' : 'incoming',
      evidence: edge.evidence,
    };
  }

  async readFile(_projectId: string, relativePath: string): Promise<FileContent> {
    const content = DEMO_SOURCES[relativePath] ?? `-- ${relativePath}\n-- (sin contenido de ejemplo)\n`;
    return {
      relative_path: relativePath,
      absolute_path: `/demo/${relativePath}`,
      size_bytes: content.length,
      content,
    };
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
