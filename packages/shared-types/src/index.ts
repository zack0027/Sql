/**
 * Shared vocabulary between the engine, the Tauri host and the UI.
 *
 * These values MUST match `engine/jarvis_engine/domain/types.py`. The pytest case
 * `engine/tests/test_shared_types_sync.py` parses this file and fails the build
 * if the two drift apart, so this is not a copy that can quietly rot.
 */

// ---------------------------------------------------------------------------
// Closed vocabularies
// ---------------------------------------------------------------------------

export const EntityType = {
  Project: 'Project',
  File: 'File',
  Directory: 'Directory',

  OracleTable: 'OracleTable',
  OracleView: 'OracleView',
  OracleColumn: 'OracleColumn',
  OracleSequence: 'OracleSequence',
  OracleProcedure: 'OracleProcedure',
  OracleFunction: 'OracleFunction',
  OraclePackage: 'OraclePackage',
  SqlQuery: 'SqlQuery',

  ApexApplication: 'ApexApplication',
  ApexPage: 'ApexPage',
  ApexItem: 'ApexItem',
  ApexRegion: 'ApexRegion',
  ApexProcess: 'ApexProcess',
  ApexValidation: 'ApexValidation',
  ApexButton: 'ApexButton',

  JasperReport: 'JasperReport',
  JasperField: 'JasperField',
  JasperParameter: 'JasperParameter',
  JasperVariable: 'JasperVariable',
  JasperSubreport: 'JasperSubreport',

  MocaCommand: 'MocaCommand',
  MocaVariable: 'MocaVariable',

  JsonProperty: 'JsonProperty',
  XmlElement: 'XmlElement',
  JavaScriptFunction: 'JavaScriptFunction',
  PythonFunction: 'PythonFunction',

  Error: 'Error',
  Solution: 'Solution',
  UnknownEntity: 'UnknownEntity',
} as const;
export type EntityType = (typeof EntityType)[keyof typeof EntityType];

export const RelationType = {
  FILE_CONTAINS_ENTITY: 'FILE_CONTAINS_ENTITY',
  QUERY_READS_TABLE: 'QUERY_READS_TABLE',
  QUERY_WRITES_TABLE: 'QUERY_WRITES_TABLE',
  QUERY_USES_COLUMN: 'QUERY_USES_COLUMN',
  PROCEDURE_CALLS_PROCEDURE: 'PROCEDURE_CALLS_PROCEDURE',
  APEX_PAGE_CONTAINS_ITEM: 'APEX_PAGE_CONTAINS_ITEM',
  APEX_ITEM_MAPS_TO_COLUMN: 'APEX_ITEM_MAPS_TO_COLUMN',
  APEX_PROCESS_UPDATES_TABLE: 'APEX_PROCESS_UPDATES_TABLE',
  REPORT_USES_PARAMETER: 'REPORT_USES_PARAMETER',
  REPORT_USES_FIELD: 'REPORT_USES_FIELD',
  REPORT_QUERIES_TABLE: 'REPORT_QUERIES_TABLE',
  REPORT_REFERENCES_IMAGE: 'REPORT_REFERENCES_IMAGE',
  REPORT_INCLUDES_SUBREPORT: 'REPORT_INCLUDES_SUBREPORT',
  MOCA_COMMAND_USES_VARIABLE: 'MOCA_COMMAND_USES_VARIABLE',
  ENTITY_DEFINED_IN_FILE: 'ENTITY_DEFINED_IN_FILE',
  ERROR_AFFECTS_ENTITY: 'ERROR_AFFECTS_ENTITY',
  SOLUTION_RESOLVES_ERROR: 'SOLUTION_RESOLVES_ERROR',
  ENTITY_DEPENDS_ON_ENTITY: 'ENTITY_DEPENDS_ON_ENTITY',
  ENTITY_MENTIONS_ENTITY: 'ENTITY_MENTIONS_ENTITY',
} as const;
export type RelationType = (typeof RelationType)[keyof typeof RelationType];

/** How a fact came to exist. Never silently promoted between values. */
export const VerificationStatus = {
  confirmed: 'confirmed',
  inferred: 'inferred',
  manual: 'manual',
} as const;
export type VerificationStatus =
  (typeof VerificationStatus)[keyof typeof VerificationStatus];

export const FileAnalysisStatus = {
  pending: 'pending',
  analyzing: 'analyzing',
  analyzed: 'analyzed',
  failed: 'failed',
  skipped: 'skipped',
  deleted: 'deleted',
} as const;
export type FileAnalysisStatus =
  (typeof FileAnalysisStatus)[keyof typeof FileAnalysisStatus];

export const ChangeKind = {
  added: 'added',
  modified: 'modified',
  unchanged: 'unchanged',
  deleted: 'deleted',
} as const;
export type ChangeKind = (typeof ChangeKind)[keyof typeof ChangeKind];

export const ProjectStatus = {
  created: 'created',
  scanning: 'scanning',
  analyzing: 'analyzing',
  ready: 'ready',
  error: 'error',
} as const;
export type ProjectStatus = (typeof ProjectStatus)[keyof typeof ProjectStatus];

export const AnalysisRunStatus = {
  running: 'running',
  completed: 'completed',
  failed: 'failed',
  cancelled: 'cancelled',
} as const;
export type AnalysisRunStatus =
  (typeof AnalysisRunStatus)[keyof typeof AnalysisRunStatus];

export const Severity = {
  warning: 'warning',
  error: 'error',
} as const;
export type Severity = (typeof Severity)[keyof typeof Severity];

export const SkipReason = {
  ignored_directory: 'ignored_directory',
  too_large: 'too_large',
  too_deep: 'too_deep',
  binary: 'binary',
  symlink_escape: 'symlink_escape',
  unreadable: 'unreadable',
} as const;
export type SkipReason = (typeof SkipReason)[keyof typeof SkipReason];

// ---------------------------------------------------------------------------
// Records
// ---------------------------------------------------------------------------

export interface Project {
  id: string;
  name: string;
  root_path: string;
  project_type: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  last_analysis_at: string | null;
  settings: Record<string, unknown>;
}

export interface FileRecord {
  id: string;
  project_id: string;
  relative_path: string;
  absolute_path: string;
  extension: string;
  detected_type: string;
  size_bytes: number;
  content_hash: string | null;
  modified_at: string | null;
  analysis_status: FileAnalysisStatus;
  analyzed_hash: string | null;
  last_analyzed_at: string | null;
  is_deleted: boolean;
  skip_reason: SkipReason | null;
  created_at: string;
  updated_at: string;
}

/** The shape `project.files` returns; lighter than a full FileRecord. */
export interface FileTreeItem {
  id: string;
  relative_path: string;
  extension: string;
  detected_type: string;
  size_bytes: number;
  analysis_status: FileAnalysisStatus;
  modified_at: string | null;
  is_modified: boolean;
  skip_reason: SkipReason | null;
}

export interface Entity {
  id: string;
  project_id: string;
  entity_type: EntityType;
  name: string;
  normalized_name: string;
  identity_key: string;
  qualified_name: string | null;
  description: string | null;
  source_file_id: string | null;
  start_line: number | null;
  end_line: number | null;
  confidence: number;
  verification_status: VerificationStatus;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Relationship {
  id: string;
  project_id: string;
  source_entity_id: string;
  relation_type: RelationType;
  target_entity_id: string;
  identity_key: string;
  source_file_id: string | null;
  start_line: number | null;
  end_line: number | null;
  evidence_snippet: string | null;
  confidence: number;
  status: VerificationStatus;
  analyzer: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Evidence {
  id: string;
  project_id: string;
  entity_id: string | null;
  relationship_id: string | null;
  file_id: string | null;
  start_line: number | null;
  end_line: number | null;
  snippet: string;
  original_name: string | null;
  analyzer: string;
  confidence: number;
  status: VerificationStatus;
  analysis_run_id: string | null;
  created_at: string;
}

export interface AnalysisRun {
  id: string;
  project_id: string;
  status: AnalysisRunStatus;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  files_scanned: number;
  files_added: number;
  files_modified: number;
  files_deleted: number;
  files_unchanged: number;
  files_analyzed: number;
  files_skipped: number;
  entities_created: number;
  relationships_created: number;
  error_count: number;
  message: string | null;
}

export interface EngineStatus {
  version: string;
  database_path: string;
  fts5_available: boolean;
  analyzers: string[];
  projects: number;
  entities: number;
  relationships: number;
  model_provider: string;
  offline: boolean;
}

export interface ProjectStats {
  project_id: string;
  files: number;
  files_by_status: Record<string, number>;
  files_by_extension: Record<string, number>;
  entities: number;
  entities_by_type: Record<string, number>;
  relationships: number;
  relationships_by_type: Record<string, number>;
  evidence: number;
  errors: number;
  last_analysis_at: string | null;
}

export interface ScanPolicy {
  ignored_directories: string[];
  ignored_files: string[];
  max_file_size_bytes: number;
  max_depth: number;
  follow_symlinks: boolean;
  hash_binary_files: boolean;
  extra_ignored_directories: string[];
}

export type AnalysisPhase =
  | 'scanning'
  | 'diffing'
  | 'inventory'
  | 'analyzing'
  | 'finalizing';

export interface ProgressEvent {
  project_id: string;
  run_id: string | null;
  phase: AnalysisPhase;
  current: number;
  total: number;
  message: string;
}

// ---------------------------------------------------------------------------
// Confidence
// ---------------------------------------------------------------------------

/** Mirrors `engine/jarvis_engine/domain/confidence.py`. */
export const Confidence = {
  CONFIRMED: 1.0,
  STRONG_INFERENCE: 0.9,
  PROBABLE_INFERENCE: 0.65,
  MENTION: 0.3,
} as const;

export type ConfidenceBandName = 'confirmed' | 'strong' | 'probable' | 'low';

export function confidenceBand(value: number): ConfidenceBandName {
  if (value >= 1) return 'confirmed';
  if (value >= 0.8) return 'strong';
  if (value >= 0.5) return 'probable';
  return 'low';
}

// ---------------------------------------------------------------------------
// Local model seam
// ---------------------------------------------------------------------------

export interface ModelInfo {
  id: string;
  name: string;
  context_window: number;
  parameters: string;
  quantization: string;
  local_path: string | null;
}

export interface ModelRequest {
  prompt: string;
  system?: string;
  model_id?: string;
  max_tokens?: number;
  temperature?: number;
  stop?: string[];
}

export interface ModelResponse {
  text: string;
  model_id: string;
  finish_reason: string;
  tokens_generated: number;
  available: boolean;
  error: string | null;
}

/**
 * The seam a future llama.cpp / Ollama / bundled-GGUF backend plugs into.
 *
 * Nothing in the application's critical path may depend on an implementation
 * being present: the knowledge graph is built by analyzers, not by a model.
 */
export interface LocalModelProvider {
  isAvailable(): Promise<boolean>;
  listModels(): Promise<ModelInfo[]>;
  generate(request: ModelRequest): Promise<ModelResponse>;
}
