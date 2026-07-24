-- JARVIS Knowledge Engine — initial schema
--
-- Conventions used throughout:
--   * Primary keys are ULIDs stored as TEXT (26 chars, time-sortable).
--   * Timestamps are ISO-8601 UTC strings ending in 'Z'; they sort lexically.
--   * Booleans are INTEGER 0/1.
--   * `identity_key` columns carry the deduplication policy from
--     jarvis_engine.domain.naming; the database only enforces uniqueness.
--   * Every fact-bearing row keeps its provenance: file, lines, snippet,
--     analyzer, confidence and verification status.

-- ---------------------------------------------------------------------------
-- Projects
-- ---------------------------------------------------------------------------
CREATE TABLE projects (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    root_path        TEXT NOT NULL UNIQUE,
    project_type     TEXT NOT NULL DEFAULT 'unknown',
    status           TEXT NOT NULL DEFAULT 'created',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    last_analysis_at TEXT,
    settings_json    TEXT NOT NULL DEFAULT '{}'
);

-- ---------------------------------------------------------------------------
-- Analysis runs (declared before file_versions, which references them)
-- ---------------------------------------------------------------------------
CREATE TABLE analysis_runs (
    id                    TEXT PRIMARY KEY,
    project_id            TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status                TEXT NOT NULL DEFAULT 'running',
    trigger               TEXT NOT NULL DEFAULT 'manual',
    started_at            TEXT NOT NULL,
    finished_at           TEXT,
    files_scanned         INTEGER NOT NULL DEFAULT 0,
    files_added           INTEGER NOT NULL DEFAULT 0,
    files_modified        INTEGER NOT NULL DEFAULT 0,
    files_deleted         INTEGER NOT NULL DEFAULT 0,
    files_unchanged       INTEGER NOT NULL DEFAULT 0,
    files_analyzed        INTEGER NOT NULL DEFAULT 0,
    files_skipped         INTEGER NOT NULL DEFAULT 0,
    entities_created      INTEGER NOT NULL DEFAULT 0,
    relationships_created INTEGER NOT NULL DEFAULT 0,
    error_count           INTEGER NOT NULL DEFAULT 0,
    message               TEXT
);

CREATE INDEX ix_analysis_runs_project ON analysis_runs(project_id, started_at DESC);

-- ---------------------------------------------------------------------------
-- Files
-- ---------------------------------------------------------------------------
CREATE TABLE files (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    relative_path    TEXT NOT NULL,
    absolute_path    TEXT NOT NULL,
    extension        TEXT NOT NULL DEFAULT '',
    detected_type    TEXT NOT NULL DEFAULT 'unknown',
    size_bytes       INTEGER NOT NULL DEFAULT 0,
    -- SHA-256 of the current content; NULL when the file was skipped.
    content_hash     TEXT,
    modified_at      TEXT,
    analysis_status  TEXT NOT NULL DEFAULT 'pending',
    -- Hash at the time of the last successful analysis. Incremental analysis
    -- compares content_hash against this column, not against mtime, so touching
    -- a file without changing it costs nothing.
    analyzed_hash    TEXT,
    last_analyzed_at TEXT,
    is_deleted       INTEGER NOT NULL DEFAULT 0,
    skip_reason      TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE(project_id, relative_path)
);

CREATE INDEX ix_files_project        ON files(project_id);
CREATE INDEX ix_files_hash           ON files(content_hash);
CREATE INDEX ix_files_status         ON files(project_id, analysis_status);
CREATE INDEX ix_files_extension      ON files(project_id, extension);
CREATE INDEX ix_files_live           ON files(project_id, is_deleted);

-- ---------------------------------------------------------------------------
-- File versions — append-only history of observed content hashes
-- ---------------------------------------------------------------------------
CREATE TABLE file_versions (
    id              TEXT PRIMARY KEY,
    file_id         TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content_hash    TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    modified_at     TEXT,
    change_kind     TEXT NOT NULL,
    analysis_run_id TEXT REFERENCES analysis_runs(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX ix_file_versions_file ON file_versions(file_id, created_at DESC);
CREATE INDEX ix_file_versions_run  ON file_versions(analysis_run_id);

-- ---------------------------------------------------------------------------
-- Entities
-- ---------------------------------------------------------------------------
CREATE TABLE entities (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity_type         TEXT NOT NULL,
    -- Spelling as first seen; the per-evidence spelling lives in evidence.
    name                TEXT NOT NULL,
    normalized_name     TEXT NOT NULL,
    identity_key        TEXT NOT NULL,
    qualified_name      TEXT,
    description         TEXT,
    source_file_id      TEXT REFERENCES files(id) ON DELETE SET NULL,
    start_line          INTEGER,
    end_line            INTEGER,
    confidence          REAL NOT NULL DEFAULT 1.0,
    verification_status TEXT NOT NULL DEFAULT 'confirmed',
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE(project_id, identity_key),
    CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX ix_entities_project    ON entities(project_id);
CREATE INDEX ix_entities_type       ON entities(project_id, entity_type);
CREATE INDEX ix_entities_normalized ON entities(project_id, normalized_name);
CREATE INDEX ix_entities_type_name  ON entities(project_id, entity_type, normalized_name);
CREATE INDEX ix_entities_file       ON entities(source_file_id);
CREATE INDEX ix_entities_confidence ON entities(project_id, confidence);

-- ---------------------------------------------------------------------------
-- Relationships
-- ---------------------------------------------------------------------------
CREATE TABLE relationships (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation_type    TEXT NOT NULL,
    target_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    identity_key     TEXT NOT NULL,
    -- Relationships are owned by the file that proves them: reanalysing that
    -- file deletes and rebuilds them, which is how stale edges disappear.
    source_file_id   TEXT REFERENCES files(id) ON DELETE CASCADE,
    start_line       INTEGER,
    end_line         INTEGER,
    evidence_snippet TEXT,
    confidence       REAL NOT NULL DEFAULT 1.0,
    status           TEXT NOT NULL DEFAULT 'confirmed',
    analyzer         TEXT NOT NULL DEFAULT '',
    metadata_json    TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE(project_id, identity_key),
    CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX ix_relationships_source ON relationships(source_entity_id, relation_type);
CREATE INDEX ix_relationships_target ON relationships(target_entity_id, relation_type);
CREATE INDEX ix_relationships_file   ON relationships(source_file_id);
CREATE INDEX ix_relationships_type   ON relationships(project_id, relation_type);
CREATE INDEX ix_relationships_status ON relationships(project_id, status);

-- ---------------------------------------------------------------------------
-- Evidence — the receipt behind every entity and relationship
-- ---------------------------------------------------------------------------
CREATE TABLE evidence (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity_id       TEXT REFERENCES entities(id) ON DELETE CASCADE,
    relationship_id TEXT REFERENCES relationships(id) ON DELETE CASCADE,
    file_id         TEXT REFERENCES files(id) ON DELETE CASCADE,
    start_line      INTEGER,
    end_line        INTEGER,
    snippet         TEXT NOT NULL DEFAULT '',
    -- The identifier exactly as written in this file, before normalisation.
    original_name   TEXT,
    analyzer        TEXT NOT NULL DEFAULT '',
    confidence      REAL NOT NULL DEFAULT 1.0,
    status          TEXT NOT NULL DEFAULT 'confirmed',
    analysis_run_id TEXT REFERENCES analysis_runs(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    CHECK (entity_id IS NOT NULL OR relationship_id IS NOT NULL),
    CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX ix_evidence_entity       ON evidence(entity_id);
CREATE INDEX ix_evidence_relationship ON evidence(relationship_id);
CREATE INDEX ix_evidence_file         ON evidence(file_id);
CREATE INDEX ix_evidence_run          ON evidence(analysis_run_id);

-- ---------------------------------------------------------------------------
-- Analyzer failures — recorded, never fatal
-- ---------------------------------------------------------------------------
CREATE TABLE analysis_errors (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    analysis_run_id TEXT REFERENCES analysis_runs(id) ON DELETE CASCADE,
    file_id         TEXT REFERENCES files(id) ON DELETE CASCADE,
    analyzer        TEXT NOT NULL DEFAULT '',
    severity        TEXT NOT NULL DEFAULT 'error',
    code            TEXT NOT NULL DEFAULT '',
    message         TEXT NOT NULL DEFAULT '',
    detail_json     TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL
);

CREATE INDEX ix_analysis_errors_run  ON analysis_errors(analysis_run_id);
CREATE INDEX ix_analysis_errors_file ON analysis_errors(file_id);
CREATE INDEX ix_analysis_errors_proj ON analysis_errors(project_id, severity);

-- ---------------------------------------------------------------------------
-- Settings — project_id '' means global
-- ---------------------------------------------------------------------------
CREATE TABLE settings (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    key        TEXT NOT NULL,
    value_json TEXT NOT NULL DEFAULT 'null',
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, key)
);

-- ---------------------------------------------------------------------------
-- Tags
-- ---------------------------------------------------------------------------
CREATE TABLE tags (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    color      TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, name)
);

CREATE TABLE entity_tags (
    entity_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    tag_id     TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (entity_id, tag_id)
);

CREATE INDEX ix_entity_tags_tag ON entity_tags(tag_id);

-- ---------------------------------------------------------------------------
-- Full-text search (FTS5, external content)
--
-- The default unicode61 tokenizer treats '_' as a separator, so UC_INSP_ENT is
-- indexed as the tokens uc / insp / ent. Searching for the full identifier
-- tokenizes identically and matches as a phrase, while searching for INSP alone
-- still finds it. Prefix indexes make type-ahead queries cheap.
-- ---------------------------------------------------------------------------
CREATE VIRTUAL TABLE entities_fts USING fts5(
    name,
    normalized_name,
    qualified_name,
    description,
    content='entities',
    content_rowid='rowid',
    prefix='2 3 4'
);

CREATE TRIGGER entities_fts_ai AFTER INSERT ON entities BEGIN
    INSERT INTO entities_fts(rowid, name, normalized_name, qualified_name, description)
    VALUES (new.rowid, new.name, new.normalized_name, new.qualified_name, new.description);
END;

CREATE TRIGGER entities_fts_ad AFTER DELETE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name, normalized_name, qualified_name, description)
    VALUES ('delete', old.rowid, old.name, old.normalized_name, old.qualified_name, old.description);
END;

CREATE TRIGGER entities_fts_au AFTER UPDATE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name, normalized_name, qualified_name, description)
    VALUES ('delete', old.rowid, old.name, old.normalized_name, old.qualified_name, old.description);
    INSERT INTO entities_fts(rowid, name, normalized_name, qualified_name, description)
    VALUES (new.rowid, new.name, new.normalized_name, new.qualified_name, new.description);
END;

CREATE VIRTUAL TABLE files_fts USING fts5(
    relative_path,
    detected_type,
    content='files',
    content_rowid='rowid',
    prefix='2 3 4'
);

CREATE TRIGGER files_fts_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, relative_path, detected_type)
    VALUES (new.rowid, new.relative_path, new.detected_type);
END;

CREATE TRIGGER files_fts_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, relative_path, detected_type)
    VALUES ('delete', old.rowid, old.relative_path, old.detected_type);
END;

CREATE TRIGGER files_fts_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, relative_path, detected_type)
    VALUES ('delete', old.rowid, old.relative_path, old.detected_type);
    INSERT INTO files_fts(rowid, relative_path, detected_type)
    VALUES (new.rowid, new.relative_path, new.detected_type);
END;

CREATE VIRTUAL TABLE evidence_fts USING fts5(
    snippet,
    original_name,
    content='evidence',
    content_rowid='rowid',
    prefix='2 3 4'
);

CREATE TRIGGER evidence_fts_ai AFTER INSERT ON evidence BEGIN
    INSERT INTO evidence_fts(rowid, snippet, original_name)
    VALUES (new.rowid, new.snippet, new.original_name);
END;

CREATE TRIGGER evidence_fts_ad AFTER DELETE ON evidence BEGIN
    INSERT INTO evidence_fts(evidence_fts, rowid, snippet, original_name)
    VALUES ('delete', old.rowid, old.snippet, old.original_name);
END;

CREATE TRIGGER evidence_fts_au AFTER UPDATE ON evidence BEGIN
    INSERT INTO evidence_fts(evidence_fts, rowid, snippet, original_name)
    VALUES ('delete', old.rowid, old.snippet, old.original_name);
    INSERT INTO evidence_fts(rowid, snippet, original_name)
    VALUES (new.rowid, new.snippet, new.original_name);
END;
