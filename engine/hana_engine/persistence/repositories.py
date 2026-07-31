"""Repositories — the only code that writes SQL against the knowledge base.

Each repository owns one table (plus its history). Nothing above this layer
builds SQL strings, and nothing in this layer makes domain decisions:
deduplication keys arrive already computed by ``domain.naming``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

from ..domain.ids import new_ulid
from ..domain.models import (
    AnalysisError,
    AnalysisRun,
    Annotation,
    Entity,
    Evidence,
    FileRecord,
    FileVersion,
    Project,
    Relationship,
    ScannedFile,
    Solution,
    utc_now,
)
from ..domain.types import (
    AnalysisRunStatus,
    ChangeKind,
    EntityType,
    FileAnalysisStatus,
    ProjectStatus,
)


class _Repository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, params)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
class ProjectRepository(_Repository):
    def create(self, project: Project) -> Project:
        self._execute(
            """
            INSERT INTO projects
                (id, name, root_path, project_type, status,
                 created_at, updated_at, last_analysis_at, settings_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project.id,
                project.name,
                project.root_path,
                project.project_type,
                project.status.value,
                project.created_at,
                project.updated_at,
                project.last_analysis_at,
                json.dumps(project.settings),
            ),
        )
        return project

    def get(self, project_id: str) -> Project | None:
        row = self._execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return Project.from_row(row) if row else None

    def get_by_root_path(self, root_path: str) -> Project | None:
        row = self._execute(
            "SELECT * FROM projects WHERE root_path = ?", (root_path,)
        ).fetchone()
        return Project.from_row(row) if row else None

    def list_recent(self, limit: int = 20) -> list[Project]:
        rows = self._execute(
            """
            SELECT * FROM projects
            ORDER BY COALESCE(last_analysis_at, updated_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [Project.from_row(row) for row in rows]

    def set_status(self, project_id: str, status: ProjectStatus) -> None:
        self._execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, utc_now(), project_id),
        )

    def mark_analyzed(self, project_id: str, *, when: str | None = None) -> None:
        timestamp = when or utc_now()
        self._execute(
            """
            UPDATE projects
            SET last_analysis_at = ?, updated_at = ?, status = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, ProjectStatus.READY.value, project_id),
        )

    def set_project_type(self, project_id: str, project_type: str) -> None:
        self._execute(
            "UPDATE projects SET project_type = ?, updated_at = ? WHERE id = ?",
            (project_type, utc_now(), project_id),
        )

    def update_settings(self, project_id: str, settings: dict[str, Any]) -> None:
        self._execute(
            "UPDATE projects SET settings_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(settings), utc_now(), project_id),
        )

    def delete(self, project_id: str) -> None:
        self._execute("DELETE FROM projects WHERE id = ?", (project_id,))


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
class FileRepository(_Repository):
    def get(self, file_id: str) -> FileRecord | None:
        row = self._execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return FileRecord.from_row(row) if row else None

    def get_by_path(self, project_id: str, relative_path: str) -> FileRecord | None:
        row = self._execute(
            "SELECT * FROM files WHERE project_id = ? AND relative_path = ?",
            (project_id, relative_path),
        ).fetchone()
        return FileRecord.from_row(row) if row else None

    def list_by_project(
        self, project_id: str, *, include_deleted: bool = False
    ) -> list[FileRecord]:
        sql = "SELECT * FROM files WHERE project_id = ?"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        sql += " ORDER BY relative_path"
        rows = self._execute(sql, (project_id,)).fetchall()
        return [FileRecord.from_row(row) for row in rows]

    def path_index(self, project_id: str) -> dict[str, FileRecord]:
        """Every known file of a project keyed by relative path, deleted included.

        Change detection needs deleted files too: a file that comes back must
        reuse its original row so its history survives.
        """
        return {
            record.relative_path: record
            for record in self.list_by_project(project_id, include_deleted=True)
        }

    def insert(self, record: FileRecord) -> FileRecord:
        self._execute(
            """
            INSERT INTO files
                (id, project_id, relative_path, absolute_path, extension,
                 detected_type, size_bytes, content_hash, modified_at,
                 analysis_status, analyzed_hash, last_analyzed_at, is_deleted,
                 skip_reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.project_id,
                record.relative_path,
                record.absolute_path,
                record.extension,
                record.detected_type,
                record.size_bytes,
                record.content_hash,
                record.modified_at,
                record.analysis_status.value,
                record.analyzed_hash,
                record.last_analyzed_at,
                int(record.is_deleted),
                record.skip_reason.value if record.skip_reason else None,
                record.created_at,
                record.updated_at,
            ),
        )
        return record

    def update_from_scan(self, record: FileRecord, scanned: ScannedFile) -> FileRecord:
        """Refresh a known file with what the scanner just observed."""
        record.absolute_path = scanned.absolute_path
        record.extension = scanned.extension
        record.detected_type = scanned.detected_type
        record.size_bytes = scanned.size_bytes
        record.content_hash = scanned.content_hash
        record.modified_at = scanned.modified_at
        record.skip_reason = scanned.skip_reason
        record.is_deleted = False
        record.updated_at = utc_now()
        self._execute(
            """
            UPDATE files
            SET absolute_path = ?, extension = ?, detected_type = ?, size_bytes = ?,
                content_hash = ?, modified_at = ?, skip_reason = ?, is_deleted = 0,
                analysis_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                record.absolute_path,
                record.extension,
                record.detected_type,
                record.size_bytes,
                record.content_hash,
                record.modified_at,
                record.skip_reason.value if record.skip_reason else None,
                record.analysis_status.value,
                record.updated_at,
                record.id,
            ),
        )
        return record

    def set_analysis_status(
        self,
        file_id: str,
        status: FileAnalysisStatus,
        *,
        analyzed_hash: str | None = None,
        analyzed_by: str | None = None,
    ) -> None:
        now = utc_now()
        if analyzed_hash is None:
            self._execute(
                "UPDATE files SET analysis_status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, file_id),
            )
        else:
            self._execute(
                """
                UPDATE files
                SET analysis_status = ?, analyzed_hash = ?, analyzed_by = ?,
                    last_analyzed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, analyzed_hash, analyzed_by, now, now, file_id),
            )

    def stale_for_analyzer(self, project_id: str, suite: str) -> list[FileRecord]:
        """Analysable files whose knowledge came from a different analyzer suite.

        Content-hash comparison cannot see this: the bytes have not moved, but
        what HANA is able to learn from them has. Without this, adding a new
        capability would leave every already-analysed file behind it, and the
        user would see a gap with no explanation.
        """
        rows = self._execute(
            """
            SELECT * FROM files
            WHERE project_id = ? AND is_deleted = 0 AND skip_reason IS NULL
              AND content_hash IS NOT NULL
              AND analyzed_hash = content_hash
              AND (analyzed_by IS NULL OR analyzed_by <> ?)
            ORDER BY relative_path
            """,
            (project_id, suite),
        ).fetchall()
        return [FileRecord.from_row(row) for row in rows]

    def mark_deleted(self, file_id: str) -> None:
        """Soft-delete: the row and its history stay, the content is gone."""
        now = utc_now()
        self._execute(
            """
            UPDATE files
            SET is_deleted = 1, analysis_status = ?, content_hash = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (FileAnalysisStatus.DELETED.value, now, file_id),
        )

    def count(self, project_id: str, *, include_deleted: bool = False) -> int:
        sql = "SELECT COUNT(*) AS n FROM files WHERE project_id = ?"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        return int(self._execute(sql, (project_id,)).fetchone()["n"])

    def count_by_status(self, project_id: str) -> dict[str, int]:
        rows = self._execute(
            """
            SELECT analysis_status, COUNT(*) AS n
            FROM files WHERE project_id = ? AND is_deleted = 0
            GROUP BY analysis_status
            """,
            (project_id,),
        ).fetchall()
        return {row["analysis_status"]: int(row["n"]) for row in rows}

    def count_by_extension(self, project_id: str) -> dict[str, int]:
        rows = self._execute(
            """
            SELECT extension, COUNT(*) AS n
            FROM files WHERE project_id = ? AND is_deleted = 0
            GROUP BY extension ORDER BY n DESC
            """,
            (project_id,),
        ).fetchall()
        return {row["extension"]: int(row["n"]) for row in rows}

    def pending_analysis(self, project_id: str, limit: int = 500) -> list[FileRecord]:
        """Files whose current hash differs from the one last analysed."""
        rows = self._execute(
            """
            SELECT * FROM files
            WHERE project_id = ? AND is_deleted = 0 AND skip_reason IS NULL
              AND content_hash IS NOT NULL
              AND (analyzed_hash IS NULL OR analyzed_hash <> content_hash)
            ORDER BY relative_path
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return [FileRecord.from_row(row) for row in rows]


class FileVersionRepository(_Repository):
    def add(self, version: FileVersion) -> FileVersion:
        self._execute(
            """
            INSERT INTO file_versions
                (id, file_id, project_id, content_hash, size_bytes, modified_at,
                 change_kind, analysis_run_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version.id,
                version.file_id,
                version.project_id,
                version.content_hash,
                version.size_bytes,
                version.modified_at,
                version.change_kind.value,
                version.analysis_run_id,
                version.created_at,
            ),
        )
        return version

    def record(
        self,
        *,
        file_id: str,
        project_id: str,
        content_hash: str,
        size_bytes: int,
        modified_at: str | None,
        change_kind: ChangeKind,
        analysis_run_id: str | None = None,
    ) -> FileVersion:
        return self.add(
            FileVersion(
                file_id=file_id,
                project_id=project_id,
                content_hash=content_hash,
                size_bytes=size_bytes,
                modified_at=modified_at,
                change_kind=change_kind,
                analysis_run_id=analysis_run_id,
            )
        )

    def history(self, file_id: str, limit: int = 50) -> list[FileVersion]:
        rows = self._execute(
            """
            SELECT * FROM file_versions WHERE file_id = ?
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (file_id, limit),
        ).fetchall()
        return [FileVersion.from_row(row) for row in rows]

    def for_run(self, analysis_run_id: str) -> list[FileVersion]:
        rows = self._execute(
            "SELECT * FROM file_versions WHERE analysis_run_id = ? ORDER BY created_at",
            (analysis_run_id,),
        ).fetchall()
        return [FileVersion.from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class EntityRepository(_Repository):
    def get(self, entity_id: str) -> Entity | None:
        row = self._execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        return Entity.from_row(row) if row else None

    def get_by_identity(self, project_id: str, identity_key: str) -> Entity | None:
        row = self._execute(
            "SELECT * FROM entities WHERE project_id = ? AND identity_key = ?",
            (project_id, identity_key),
        ).fetchone()
        return Entity.from_row(row) if row else None

    def upsert(self, entity: Entity) -> tuple[Entity, bool]:
        """Insert, or merge into the entity that already owns this identity key.

        Returns ``(entity, created)`` so callers can count genuinely new
        knowledge without issuing a second query.

        Merging is deliberately conservative: the first spelling seen wins, and
        confidence only ever moves up. A second, weaker sighting of the same
        table must not downgrade a fact proved by an ``INSERT INTO``.
        """
        existing = self.get_by_identity(entity.project_id, entity.identity_key)
        if existing is None:
            self._execute(
                """
                INSERT INTO entities
                    (id, project_id, entity_type, name, normalized_name, identity_key,
                     qualified_name, description, source_file_id, start_line, end_line,
                     confidence, verification_status, metadata_json,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity.id,
                    entity.project_id,
                    entity.entity_type.value,
                    entity.name,
                    entity.normalized_name,
                    entity.identity_key,
                    entity.qualified_name,
                    entity.description,
                    entity.source_file_id,
                    entity.start_line,
                    entity.end_line,
                    entity.confidence,
                    entity.verification_status.value,
                    json.dumps(entity.metadata),
                    entity.created_at,
                    entity.updated_at,
                ),
            )
            return entity, True

        merged_confidence = max(existing.confidence, entity.confidence)
        status = (
            entity.verification_status
            if entity.confidence > existing.confidence
            else existing.verification_status
        )
        metadata = {**existing.metadata, **entity.metadata}
        description = existing.description or entity.description
        qualified = existing.qualified_name or entity.qualified_name
        # A definition site (one that came with line numbers) outranks a mention.
        source_file_id = existing.source_file_id or entity.source_file_id
        start_line = existing.start_line if existing.start_line else entity.start_line
        end_line = existing.end_line if existing.end_line else entity.end_line
        now = utc_now()

        self._execute(
            """
            UPDATE entities
            SET confidence = ?, verification_status = ?, metadata_json = ?,
                description = ?, qualified_name = ?, source_file_id = ?,
                start_line = ?, end_line = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                merged_confidence,
                status.value,
                json.dumps(metadata),
                description,
                qualified,
                source_file_id,
                start_line,
                end_line,
                now,
                existing.id,
            ),
        )
        existing.confidence = merged_confidence
        existing.verification_status = status
        existing.metadata = metadata
        existing.description = description
        existing.qualified_name = qualified
        existing.source_file_id = source_file_id
        existing.start_line = start_line
        existing.end_line = end_line
        existing.updated_at = now
        return existing, False

    def list_by_project(
        self,
        project_id: str,
        *,
        entity_type: EntityType | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Entity]:
        params: list[Any] = [project_id]
        sql = "SELECT * FROM entities WHERE project_id = ?"
        if entity_type is not None:
            sql += " AND entity_type = ?"
            params.append(entity_type.value)
        sql += " ORDER BY normalized_name LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._execute(sql, params).fetchall()
        return [Entity.from_row(row) for row in rows]

    def count(self, project_id: str | None = None) -> int:
        if project_id is None:
            row = self._execute("SELECT COUNT(*) AS n FROM entities").fetchone()
        else:
            row = self._execute(
                "SELECT COUNT(*) AS n FROM entities WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return int(row["n"])

    def count_by_type(self, project_id: str) -> dict[str, int]:
        rows = self._execute(
            """
            SELECT entity_type, COUNT(*) AS n FROM entities
            WHERE project_id = ? GROUP BY entity_type ORDER BY n DESC
            """,
            (project_id,),
        ).fetchall()
        return {row["entity_type"]: int(row["n"]) for row in rows}

    def low_confidence(self, project_id: str, threshold: float = 0.5) -> list[Entity]:
        rows = self._execute(
            """
            SELECT * FROM entities WHERE project_id = ? AND confidence < ?
            ORDER BY confidence ASC, normalized_name
            """,
            (project_id, threshold),
        ).fetchall()
        return [Entity.from_row(row) for row in rows]

    def delete_orphans_of_file(self, file_id: str) -> int:
        """Remove entities defined in a file that no longer have any evidence.

        Called after a file is reanalysed or deleted. Entities still referenced
        from other files keep their row; only the ones this file alone justified
        disappear.
        """
        cursor = self._execute(
            """
            DELETE FROM entities
            WHERE source_file_id = ?
              AND NOT EXISTS (SELECT 1 FROM evidence e WHERE e.entity_id = entities.id)
              AND NOT EXISTS (
                    SELECT 1 FROM relationships r
                    WHERE r.source_entity_id = entities.id
                       OR r.target_entity_id = entities.id
              )
            """,
            (file_id,),
        )
        return cursor.rowcount


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------
class RelationshipRepository(_Repository):
    def get(self, relationship_id: str) -> Relationship | None:
        row = self._execute(
            "SELECT * FROM relationships WHERE id = ?", (relationship_id,)
        ).fetchone()
        return Relationship.from_row(row) if row else None

    def upsert(self, relationship: Relationship) -> Relationship:
        row = self._execute(
            "SELECT * FROM relationships WHERE project_id = ? AND identity_key = ?",
            (relationship.project_id, relationship.identity_key),
        ).fetchone()
        if row is None:
            self._execute(
                """
                INSERT INTO relationships
                    (id, project_id, source_entity_id, relation_type, target_entity_id,
                     identity_key, source_file_id, start_line, end_line,
                     evidence_snippet, confidence, status, analyzer, metadata_json,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relationship.id,
                    relationship.project_id,
                    relationship.source_entity_id,
                    relationship.relation_type.value,
                    relationship.target_entity_id,
                    relationship.identity_key,
                    relationship.source_file_id,
                    relationship.start_line,
                    relationship.end_line,
                    relationship.evidence_snippet,
                    relationship.confidence,
                    relationship.status.value,
                    relationship.analyzer,
                    json.dumps(relationship.metadata),
                    relationship.created_at,
                    relationship.updated_at,
                ),
            )
            return relationship

        existing = Relationship.from_row(row)
        if relationship.confidence <= existing.confidence:
            return existing

        now = utc_now()
        self._execute(
            """
            UPDATE relationships
            SET confidence = ?, status = ?, start_line = ?, end_line = ?,
                evidence_snippet = ?, analyzer = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                relationship.confidence,
                relationship.status.value,
                relationship.start_line,
                relationship.end_line,
                relationship.evidence_snippet,
                relationship.analyzer,
                now,
                existing.id,
            ),
        )
        existing.confidence = relationship.confidence
        existing.status = relationship.status
        existing.start_line = relationship.start_line
        existing.end_line = relationship.end_line
        existing.evidence_snippet = relationship.evidence_snippet
        existing.analyzer = relationship.analyzer
        existing.updated_at = now
        return existing

    def outgoing(self, entity_id: str, limit: int = 200) -> list[Relationship]:
        rows = self._execute(
            "SELECT * FROM relationships WHERE source_entity_id = ? LIMIT ?",
            (entity_id, limit),
        ).fetchall()
        return [Relationship.from_row(row) for row in rows]

    def incoming(self, entity_id: str, limit: int = 200) -> list[Relationship]:
        rows = self._execute(
            "SELECT * FROM relationships WHERE target_entity_id = ? LIMIT ?",
            (entity_id, limit),
        ).fetchall()
        return [Relationship.from_row(row) for row in rows]

    def delete_by_file(self, file_id: str) -> int:
        """Drop every relationship a file proved.

        This is the heart of correct incremental analysis: a modified file must
        not leave behind edges that its new content no longer supports.
        """
        cursor = self._execute(
            "DELETE FROM relationships WHERE source_file_id = ?", (file_id,)
        )
        return cursor.rowcount

    def count(self, project_id: str | None = None) -> int:
        if project_id is None:
            row = self._execute("SELECT COUNT(*) AS n FROM relationships").fetchone()
        else:
            row = self._execute(
                "SELECT COUNT(*) AS n FROM relationships WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return int(row["n"])

    def count_by_type(self, project_id: str) -> dict[str, int]:
        rows = self._execute(
            """
            SELECT relation_type, COUNT(*) AS n FROM relationships
            WHERE project_id = ? GROUP BY relation_type ORDER BY n DESC
            """,
            (project_id,),
        ).fetchall()
        return {row["relation_type"]: int(row["n"]) for row in rows}


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------
class EvidenceRepository(_Repository):
    def add(self, evidence: Evidence) -> Evidence:
        self._execute(
            """
            INSERT INTO evidence
                (id, project_id, entity_id, relationship_id, file_id, start_line,
                 end_line, snippet, original_name, analyzer, confidence, status,
                 analysis_run_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.id,
                evidence.project_id,
                evidence.entity_id,
                evidence.relationship_id,
                evidence.file_id,
                evidence.start_line,
                evidence.end_line,
                evidence.snippet,
                evidence.original_name,
                evidence.analyzer,
                evidence.confidence,
                evidence.status.value,
                evidence.analysis_run_id,
                evidence.created_at,
            ),
        )
        return evidence

    def add_many(self, items: Iterable[Evidence]) -> int:
        count = 0
        for item in items:
            self.add(item)
            count += 1
        return count

    def for_entity(self, entity_id: str, limit: int = 100) -> list[Evidence]:
        rows = self._execute(
            """
            SELECT * FROM evidence WHERE entity_id = ?
            ORDER BY confidence DESC, start_line LIMIT ?
            """,
            (entity_id, limit),
        ).fetchall()
        return [Evidence.from_row(row) for row in rows]

    def for_relationship(self, relationship_id: str, limit: int = 100) -> list[Evidence]:
        rows = self._execute(
            """
            SELECT * FROM evidence WHERE relationship_id = ?
            ORDER BY confidence DESC, start_line LIMIT ?
            """,
            (relationship_id, limit),
        ).fetchall()
        return [Evidence.from_row(row) for row in rows]

    def delete_by_file(self, file_id: str) -> int:
        cursor = self._execute("DELETE FROM evidence WHERE file_id = ?", (file_id,))
        return cursor.rowcount

    def count(self, project_id: str) -> int:
        row = self._execute(
            "SELECT COUNT(*) AS n FROM evidence WHERE project_id = ?", (project_id,)
        ).fetchone()
        return int(row["n"])


# ---------------------------------------------------------------------------
# Analysis runs and errors
# ---------------------------------------------------------------------------
class AnalysisRunRepository(_Repository):
    def start(self, project_id: str, trigger: str = "manual") -> AnalysisRun:
        run = AnalysisRun(project_id=project_id, trigger=trigger)
        self._execute(
            """
            INSERT INTO analysis_runs
                (id, project_id, status, trigger, started_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run.id, run.project_id, run.status.value, run.trigger, run.started_at),
        )
        return run

    def finish(
        self,
        run: AnalysisRun,
        status: AnalysisRunStatus,
        *,
        message: str | None = None,
    ) -> AnalysisRun:
        run.status = status
        run.finished_at = utc_now()
        run.message = message
        self._execute(
            """
            UPDATE analysis_runs
            SET status = ?, finished_at = ?, files_scanned = ?, files_added = ?,
                files_modified = ?, files_deleted = ?, files_unchanged = ?,
                files_analyzed = ?, files_reanalyzed = ?, files_skipped = ?,
                entities_created = ?,
                relationships_created = ?, error_count = ?, message = ?
            WHERE id = ?
            """,
            (
                run.status.value,
                run.finished_at,
                run.files_scanned,
                run.files_added,
                run.files_modified,
                run.files_deleted,
                run.files_unchanged,
                run.files_analyzed,
                run.files_reanalyzed,
                run.files_skipped,
                run.entities_created,
                run.relationships_created,
                run.error_count,
                run.message,
                run.id,
            ),
        )
        return run

    def get(self, run_id: str) -> AnalysisRun | None:
        row = self._execute(
            "SELECT * FROM analysis_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return AnalysisRun.from_row(row) if row else None

    def latest(self, project_id: str) -> AnalysisRun | None:
        row = self._execute(
            """
            SELECT * FROM analysis_runs WHERE project_id = ?
            ORDER BY started_at DESC, id DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        return AnalysisRun.from_row(row) if row else None

    def history(self, project_id: str, limit: int = 25) -> list[AnalysisRun]:
        rows = self._execute(
            """
            SELECT * FROM analysis_runs WHERE project_id = ?
            ORDER BY started_at DESC, id DESC LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return [AnalysisRun.from_row(row) for row in rows]


class AnalysisErrorRepository(_Repository):
    def add(self, error: AnalysisError) -> AnalysisError:
        self._execute(
            """
            INSERT INTO analysis_errors
                (id, project_id, analysis_run_id, file_id, analyzer, severity,
                 code, message, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                error.id,
                error.project_id,
                error.analysis_run_id,
                error.file_id,
                error.analyzer,
                error.severity.value,
                error.code,
                error.message,
                json.dumps(error.detail),
                error.created_at,
            ),
        )
        return error

    def for_run(self, run_id: str) -> list[AnalysisError]:
        rows = self._execute(
            "SELECT * FROM analysis_errors WHERE analysis_run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [AnalysisError.from_row(row) for row in rows]

    def for_project(self, project_id: str, limit: int = 200) -> list[AnalysisError]:
        rows = self._execute(
            """
            SELECT * FROM analysis_errors WHERE project_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return [AnalysisError.from_row(row) for row in rows]

    def delete_by_file(self, file_id: str) -> int:
        cursor = self._execute(
            "DELETE FROM analysis_errors WHERE file_id = ?", (file_id,)
        )
        return cursor.rowcount

    def count(self, project_id: str) -> int:
        row = self._execute(
            "SELECT COUNT(*) AS n FROM analysis_errors WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return int(row["n"])


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SettingsRepository(_Repository):
    GLOBAL = ""

    def get(self, key: str, default: Any = None, *, project_id: str = GLOBAL) -> Any:
        row = self._execute(
            "SELECT value_json FROM settings WHERE project_id = ? AND key = ?",
            (project_id, key),
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return default

    def set(self, key: str, value: Any, *, project_id: str = GLOBAL) -> None:
        self._execute(
            """
            INSERT INTO settings (id, project_id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id, key)
            DO UPDATE SET value_json = excluded.value_json,
                          updated_at = excluded.updated_at
            """,
            (new_ulid(), project_id, key, json.dumps(value), utc_now()),
        )

    def all(self, *, project_id: str = GLOBAL) -> dict[str, Any]:
        rows = self._execute(
            "SELECT key, value_json FROM settings WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value_json"])
            except json.JSONDecodeError:
                result[row["key"]] = None
        return result

    def delete(self, key: str, *, project_id: str = GLOBAL) -> None:
        self._execute(
            "DELETE FROM settings WHERE project_id = ? AND key = ?",
            (project_id, key),
        )


# ---------------------------------------------------------------------------
# Annotations — the only place a human writes into the graph
# ---------------------------------------------------------------------------
class AnnotationRepository(_Repository):
    """Verdicts a person recorded, and the reapplying that keeps them alive.

    See ``migrations/004_annotations.sql``. The short version: reanalysing a
    file deletes its relationships and rebuilds them, so a verdict stored on
    the row itself would vanish. These are stored apart and stamped back on
    after every run.
    """

    def set(
        self,
        project_id: str,
        target_kind: str,
        target_key: str,
        verdict: str,
        *,
        note: str | None = None,
        author: str | None = None,
    ) -> Annotation:
        if target_kind not in ("entity", "relationship"):
            raise ValueError(f"target_kind desconocido: {target_kind!r}")
        if verdict not in ("confirmed", "rejected"):
            raise ValueError(f"verdict desconocido: {verdict!r}")

        now = utc_now()
        self._execute(
            """
            INSERT INTO annotations
                (id, project_id, target_kind, target_key, verdict, note, author,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, target_kind, target_key)
            DO UPDATE SET verdict = excluded.verdict,
                          note = excluded.note,
                          author = excluded.author,
                          updated_at = excluded.updated_at
            """,
            (
                new_ulid(),
                project_id,
                target_kind,
                target_key,
                verdict,
                note,
                author,
                now,
                now,
            ),
        )
        stored = self.get(project_id, target_kind, target_key)
        assert stored is not None
        return stored

    def get(
        self, project_id: str, target_kind: str, target_key: str
    ) -> Annotation | None:
        row = self._execute(
            """
            SELECT * FROM annotations
            WHERE project_id = ? AND target_kind = ? AND target_key = ?
            """,
            (project_id, target_kind, target_key),
        ).fetchone()
        return Annotation.from_row(row) if row else None

    def clear(self, project_id: str, target_kind: str, target_key: str) -> bool:
        cursor = self._execute(
            """
            DELETE FROM annotations
            WHERE project_id = ? AND target_kind = ? AND target_key = ?
            """,
            (project_id, target_kind, target_key),
        )
        return cursor.rowcount > 0

    def for_project(self, project_id: str) -> list[Annotation]:
        rows = self._execute(
            "SELECT * FROM annotations WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        ).fetchall()
        return [Annotation.from_row(row) for row in rows]

    def count(self, project_id: str) -> int:
        row = self._execute(
            "SELECT COUNT(*) AS n FROM annotations WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return int(row["n"])

    def apply_to_project(self, project_id: str) -> int:
        """Stamp `verification_status = 'manual'` on everything a person judged.

        Run after each analysis. Rows the annotation no longer matches are left
        alone: an entity that disappeared from the code has nothing to mark, and
        the annotation waits in case it comes back.

        Only the status is written. Confidence stays as the analyzer left it,
        because confidence answers "how sure is HANA", and a human verdict is a
        different fact — it is recorded as one, alongside, rather than dressed up
        as the machine having become more certain.
        """
        marked = self._execute(
            """
            UPDATE entities SET verification_status = 'manual', updated_at = ?
            WHERE project_id = ?
              AND identity_key IN (
                    SELECT target_key FROM annotations
                    WHERE project_id = ? AND target_kind = 'entity'
              )
              AND verification_status != 'manual'
            """,
            (utc_now(), project_id, project_id),
        ).rowcount

        marked += self._execute(
            """
            UPDATE relationships SET status = 'manual', updated_at = ?
            WHERE project_id = ?
              AND id IN (
                    SELECT r.id
                    FROM relationships r
                    JOIN entities s ON s.id = r.source_entity_id
                    JOIN entities t ON t.id = r.target_entity_id
                    JOIN annotations a
                      ON a.project_id = r.project_id
                     AND a.target_kind = 'relationship'
                     AND a.target_key =
                         s.identity_key || '|' || r.relation_type || '|' || t.identity_key
                    WHERE r.project_id = ?
              )
              AND status != 'manual'
            """,
            (utc_now(), project_id, project_id),
        ).rowcount
        return marked

    def resolved(self, project_id: str) -> list[dict[str, Any]]:
        """Annotations with the id of whatever they currently point at.

        The id is what the interface keys on, and it is looked up rather than
        stored: it changes when a file is edited and its entities are rebuilt.
        ``None`` means the annotation currently matches nothing in the graph —
        worth showing as such, not worth deleting.
        """
        entities = self._execute(
            """
            SELECT a.*, e.id AS resolved_id
            FROM annotations a
            LEFT JOIN entities e
              ON e.project_id = a.project_id AND e.identity_key = a.target_key
            WHERE a.project_id = ? AND a.target_kind = 'entity'
            """,
            (project_id,),
        ).fetchall()

        relationships = self._execute(
            """
            SELECT a.*, r.id AS resolved_id
            FROM annotations a
            LEFT JOIN relationships r
              ON r.project_id = a.project_id
             AND EXISTS (
                    SELECT 1 FROM entities s, entities t
                    WHERE s.id = r.source_entity_id AND t.id = r.target_entity_id
                      AND s.identity_key || '|' || r.relation_type || '|' || t.identity_key
                          = a.target_key
             )
            WHERE a.project_id = ? AND a.target_kind = 'relationship'
            """,
            (project_id,),
        ).fetchall()

        out: list[dict[str, Any]] = []
        for row in [*entities, *relationships]:
            payload = Annotation.from_row(row).to_dict()
            payload["resolved_id"] = row["resolved_id"]
            out.append(payload)
        out.sort(key=lambda item: item["updated_at"], reverse=True)
        return out


# ---------------------------------------------------------------------------
# Solutions — the half of the knowledge no analyzer can find
# ---------------------------------------------------------------------------
class SolutionRepository(_Repository):
    """What people did that made errors stop. See ``migrations/005_solutions.sql``."""

    def add(
        self,
        project_id: str,
        error_key: str,
        description: str,
        *,
        worked: bool = True,
        author: str | None = None,
    ) -> Solution:
        text = description.strip()
        if not text:
            raise ValueError("una solución sin texto no dice nada")

        now = utc_now()
        self._execute(
            """
            INSERT INTO solutions
                (id, project_id, error_key, description, author, worked,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, error_key, description)
            DO UPDATE SET worked = excluded.worked,
                          author = excluded.author,
                          updated_at = excluded.updated_at
            """,
            (new_ulid(), project_id, error_key, text, author, int(worked), now, now),
        )
        stored = self.for_error(project_id, error_key)
        return next(item for item in stored if item.description == text)

    def for_error(self, project_id: str, error_key: str) -> list[Solution]:
        rows = self._execute(
            """
            SELECT * FROM solutions
            WHERE project_id = ? AND error_key = ?
            ORDER BY worked DESC, updated_at DESC
            """,
            (project_id, error_key),
        ).fetchall()
        return [Solution.from_row(row) for row in rows]

    def for_project(self, project_id: str) -> dict[str, list[Solution]]:
        rows = self._execute(
            "SELECT * FROM solutions WHERE project_id = ? ORDER BY worked DESC, updated_at DESC",
            (project_id,),
        ).fetchall()
        grouped: dict[str, list[Solution]] = {}
        for row in rows:
            solution = Solution.from_row(row)
            grouped.setdefault(solution.error_key, []).append(solution)
        return grouped

    def delete(self, solution_id: str) -> bool:
        cursor = self._execute("DELETE FROM solutions WHERE id = ?", (solution_id,))
        return cursor.rowcount > 0

    def count(self, project_id: str) -> int:
        row = self._execute(
            "SELECT COUNT(*) AS n FROM solutions WHERE project_id = ?", (project_id,)
        ).fetchone()
        return int(row["n"])


class Repositories:
    """One handle carrying every repository for a connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.projects = ProjectRepository(connection)
        self.files = FileRepository(connection)
        self.file_versions = FileVersionRepository(connection)
        self.entities = EntityRepository(connection)
        self.relationships = RelationshipRepository(connection)
        self.evidence = EvidenceRepository(connection)
        self.runs = AnalysisRunRepository(connection)
        self.errors = AnalysisErrorRepository(connection)
        self.settings = SettingsRepository(connection)
        self.annotations = AnnotationRepository(connection)
        self.solutions = SolutionRepository(connection)
