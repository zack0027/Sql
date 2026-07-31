/**
 * Shared vocabulary between the engine, the Tauri host and the UI.
 *
 * These values MUST match `engine/hana_engine/domain/types.py`. The pytest case
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
  /** A column belongs to a table. Without this edge, the impact of a column
   *  could not reach the reports and pipelines that read its table. */
  TABLE_HAS_COLUMN: 'TABLE_HAS_COLUMN',
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
  /** Two tables joined in a query — not a declared foreign key. */
  TABLE_JOINS_TABLE: 'TABLE_JOINS_TABLE',
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
// Query results — the answering layer
//
// Mirrors `engine/hana_engine/query/engine.py`. Every answer carries the file
// and the lines that prove it, so the UI can always open the evidence.
// ---------------------------------------------------------------------------

export interface QueryEvidence {
  file_path: string | null;
  absolute_path: string | null;
  start_line: number | null;
  end_line: number | null;
  snippet: string | null;
  analyzer: string;
  confidence: number;
  status: VerificationStatus;
}

export interface EntityHit {
  id: string;
  entity_type: EntityType;
  name: string;
  normalized_name: string;
  qualified_name: string | null;
  confidence: number;
  verification_status: VerificationStatus;
  file_path: string | null;
  start_line: number | null;
}

export interface UsageHit {
  entity: EntityHit;
  relation_type: RelationType;
  direction: 'incoming' | 'outgoing';
  evidence: QueryEvidence;
}

/**
 * A person's verdict on something an analyzer claimed.
 *
 * `resolved_id` is the id of whatever it currently points at, looked up rather
 * than stored — it changes when a file is edited and its entities are rebuilt.
 * `null` means the annotation matches nothing in the graph right now, which is
 * worth showing rather than treating as a reason to delete it.
 */
export interface Annotation {
  id: string;
  project_id: string;
  target_kind: 'entity' | 'relationship';
  target_key: string;
  verdict: 'confirmed' | 'rejected';
  note: string | null;
  author: string | null;
  resolved_id: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Entities nothing in the project refers to.
 *
 * Candidates to review, never "safe to delete" — `caveat` carries the wording
 * so every surface says the same thing.
 */
export interface OrphanReport {
  total: number;
  by_type: Record<string, EntityHit[]>;
  truncated: boolean;
  caveat: string;
}

/** A runtime failure read from a log, with how often it happened. */
export interface Incident extends EntityHit {
  identity_key: string;
  message: string | null;
  times_seen: number;
  first_seen: string | null;
  last_seen: string | null;
  affects: AffectedEntity[];
  solutions: Solution[];
}

export interface AffectedEntity extends EntityHit {
  /**
   * Entities identical but for the schema.
   *
   * Logs name objects with their schema and source code usually does not, so
   * the two never become one entity — unknown must not match known. This is the
   * correspondence recorded as an inference instead, and must be shown as one.
   */
  probably_same_as: Array<EntityHit & { reason: string }>;
}

/** What a person did that made an error stop. */
export interface Solution {
  id: string;
  project_id: string;
  error_key: string;
  description: string;
  author: string | null;
  /** False is kept on purpose: a dead end nobody has to walk twice. */
  worked: boolean;
  created_at: string;
  updated_at: string;
}

export interface ComparisonSide {
  project_id: string;
  name: string;
  root_path: string;
  entities: number;
  relationships: number;
}

/** One claim, named by its two ends rather than by ids. */
export interface ComparedClaim {
  key: string;
  relation_type: RelationType;
  source_name: string;
  source_type: EntityType;
  target_name: string;
  target_type: EntityType;
  confidence: number;
  status: VerificationStatus;
  file_path: string | null;
  start_line: number | null;
}

/**
 * Two analysed projects, compared by their graphs.
 *
 * `comparable` is false when the two file trees barely overlap — probably not
 * two versions of the same code. The differences below would then say almost
 * everything changed, which is a badly posed comparison rather than a finding,
 * so `warning` must be shown before any of them.
 */
export interface ComparisonReport {
  left: ComparisonSide;
  right: ComparisonSide;
  entities_only_left: Record<string, EntityHit[]>;
  entities_only_right: Record<string, EntityHit[]>;
  relations_only_left: Record<string, ComparedClaim[]>;
  relations_only_right: Record<string, ComparedClaim[]>;
  shared_entities: number;
  shared_relations: number;
  path_overlap: number;
  comparable: boolean;
  warning: string | null;
  truncated: boolean;
}

/** One thing a change to the root could reach, and how the change gets there. */
export interface ImpactNode {
  entity: EntityHit;
  depth: number;
  /** Entity ids from the root to here, inclusive. */
  path: string[];
  /** Confidence of the weakest link in that path, not of the last edge. */
  min_confidence: number;
  inferred_in_path: boolean;
  relation_type: RelationType;
  evidence: QueryEvidence;
}

/**
 * Transitive impact. Deliberately an over-approximation: missing something that
 * really does break is far worse than listing something that does not, so every
 * node carries its path and the reader judges each one.
 */
export interface ImpactReport {
  root: EntityHit;
  nodes: ImpactNode[];
  /** True when the node budget ran out. An incomplete answer must say so. */
  truncated: boolean;
  max_depth_reached: number;
  by_type: Record<string, number>;
  direction: 'incoming' | 'outgoing';
  include_containment: boolean;
}

export interface GraphNodeHit {
  entity: EntityHit;
  depth: number;
}

export interface GraphEdgeHit {
  source_id: string;
  target_id: string;
  relation_type: RelationType;
  confidence: number;
  status: VerificationStatus;
  evidence: QueryEvidence;
}

/** A bounded slice of the graph, for progressive display. */
export interface Neighborhood {
  nodes: GraphNodeHit[];
  edges: GraphEdgeHit[];
  truncated: boolean;
}

export interface FileChangeEntry {
  change_kind: ChangeKind;
  relative_path: string;
  absolute_path: string;
  detected_type: string;
  content_hash: string | null;
  observed_at: string;
}

export interface ChangesResult {
  run_id: string | null;
  changes: FileChangeEntry[];
}

// -- entity-relationship model ----------------------------------------------

export interface ErColumn {
  id: string;
  name: string;
  normalized_name: string;
  confidence: number;
}

export interface ErTable extends EntityHit {
  columns: ErColumn[];
}

export interface ErLink {
  source_id: string;
  target_id: string;
  left_column: string | null;
  right_column: string | null;
  confidence: number;
  status: VerificationStatus;
  evidence: QueryEvidence;
}

/**
 * The schema as the code uses it, not as the database declares it.
 * `derived_from` says so explicitly — these links come from join conditions,
 * never from foreign keys, because HANA does not connect to Oracle.
 */
export interface ErModel {
  tables: ErTable[];
  links: ErLink[];
  derived_from: string;
}

// -- report structure -------------------------------------------------------

export interface ReportElement {
  kind: string;
  x: number | null;
  y: number | null;
  width: number | null;
  height: number | null;
  text: string;
  references: string[];
}

export interface ReportBand {
  section: string;
  group: string | null;
  height: number | null;
  elements: ReportElement[];
}

export interface ReportStructure {
  id: string;
  name: string;
  file_path: string | null;
  absolute_path: string | null;
  bands: ReportBand[];
  /** Analyzer suite that produced this reading; null if from before it was recorded. */
  analyzed_by: string | null;
  /** True when a newer analyzer would read more out of the same file. */
  stale: boolean;
}

/** How much of a project's knowledge predates the installed analyzers. */
export interface Freshness {
  suite: string | null;
  analyzed: number;
  stale: number;
  by_suite: Record<string, number>;
}

export interface AnalysisIssue {
  relative_path: string | null;
  absolute_path: string | null;
  severity: Severity;
  code: string;
  message: string;
  analyzer: string;
  observed_at: string;
}

// ---------------------------------------------------------------------------
// Confidence
// ---------------------------------------------------------------------------

/** Mirrors `engine/hana_engine/domain/confidence.py`. */
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
