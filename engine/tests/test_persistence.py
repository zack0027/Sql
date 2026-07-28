"""Schema, migrations, repositories, deduplication and cascades."""

from __future__ import annotations

import sqlite3

import pytest

from hana_engine.domain.confidence import CONFIRMED, MENTION, STRONG_INFERENCE
from hana_engine.domain.models import (
    Entity,
    Evidence,
    FileRecord,
    Project,
    Relationship,
)
from hana_engine.domain.naming import entity_identity_key, relationship_identity_key
from hana_engine.domain.types import (
    AnalysisRunStatus,
    ChangeKind,
    EntityType,
    FileAnalysisStatus,
    RelationType,
    VerificationStatus,
)
from hana_engine.persistence.database import (
    applied_versions,
    has_fts5,
    migrate,
    open_knowledge_base,
)


@pytest.fixture
def project(repos) -> Project:
    item = Project(name="demo", root_path="/tmp/demo")
    repos.projects.create(item)
    return item


@pytest.fixture
def file_record(repos, project) -> FileRecord:
    record = FileRecord(
        project_id=project.id,
        relative_path="sql/guardar.sql",
        absolute_path="/tmp/demo/sql/guardar.sql",
        extension=".sql",
        detected_type="sql",
        size_bytes=100,
        content_hash="a" * 64,
    )
    repos.files.insert(record)
    return record


def _entity(project, name, entity_type=EntityType.ORACLE_TABLE, **kwargs) -> Entity:
    normalized = name.upper()
    return Entity(
        project_id=project.id,
        entity_type=entity_type,
        name=name,
        normalized_name=normalized,
        identity_key=entity_identity_key(entity_type, normalized, **kwargs),
    )


class TestMigrations:
    def test_creates_every_table(self, connection):
        names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        expected = {
            "projects",
            "files",
            "file_versions",
            "entities",
            "relationships",
            "evidence",
            "analysis_runs",
            "analysis_errors",
            "settings",
            "tags",
            "entity_tags",
        }
        assert expected <= names

    def test_creates_the_required_indexes(self, connection):
        names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        for expected in (
            "ix_files_project",
            "ix_files_hash",
            "ix_entities_type",
            "ix_entities_normalized",
            "ix_relationships_source",
            "ix_relationships_target",
        ):
            assert expected in names

    def test_is_idempotent(self, connection):
        """Re-running applies nothing and leaves the record untouched.

        Deliberately not asserting a fixed set of versions: that would fail every
        time a migration is added, which is noise rather than a finding.
        """
        before = applied_versions(connection)
        assert migrate(connection) == []
        assert applied_versions(connection) == before
        assert 1 in before  # the initial schema is always there

    def test_fts5_is_available(self, connection):
        assert has_fts5(connection)

    def test_foreign_keys_are_enforced(self, connection):
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO files (id, project_id, relative_path, absolute_path,"
                " created_at, updated_at) VALUES ('x', 'ghost', 'a', 'b', 'now', 'now')"
            )

    def test_reopening_keeps_the_data(self, db_path, connection):
        connection.execute(
            "INSERT INTO projects (id, name, root_path, created_at, updated_at)"
            " VALUES ('P1', 'demo', '/tmp/demo', 'now', 'now')"
        )
        connection.commit()
        connection.close()

        reopened = open_knowledge_base(db_path)
        row = reopened.execute("SELECT name FROM projects WHERE id = 'P1'").fetchone()
        assert row["name"] == "demo"
        reopened.close()


class TestFullTextSearch:
    def test_entities_are_indexed_and_stay_in_sync(self, repos, project, connection):
        entity = _entity(project, "UC_INSP_ENT")
        repos.entities.upsert(entity)
        connection.commit()

        rows = connection.execute(
            "SELECT rowid FROM entities_fts WHERE entities_fts MATCH 'insp'"
        ).fetchall()
        assert len(rows) == 1

        connection.execute("DELETE FROM entities WHERE id = ?", (entity.id,))
        connection.commit()
        rows = connection.execute(
            "SELECT rowid FROM entities_fts WHERE entities_fts MATCH 'insp'"
        ).fetchall()
        assert rows == []

    def test_evidence_snippets_are_searchable(self, repos, project, file_record, connection):
        entity = _entity(project, "UC_INSP_ENT")
        repos.entities.upsert(entity)
        repos.evidence.add(
            Evidence(
                project_id=project.id,
                entity_id=entity.id,
                file_id=file_record.id,
                snippet="insert into uc_insp_ent (netwgt) values (:P117_NETWGT)",
                analyzer="test",
            )
        )
        connection.commit()
        rows = connection.execute(
            "SELECT rowid FROM evidence_fts WHERE evidence_fts MATCH 'netwgt'"
        ).fetchall()
        assert len(rows) == 1


class TestEntityDeduplication:
    def test_same_identity_merges_instead_of_duplicating(self, repos, project):
        first, created_first = repos.entities.upsert(_entity(project, "uc_insp_ent"))
        second, created_second = repos.entities.upsert(_entity(project, "UC_INSP_ENT"))

        assert created_first is True
        assert created_second is False
        assert first.id == second.id
        assert repos.entities.count(project.id) == 1

    def test_the_first_spelling_is_kept(self, repos, project):
        repos.entities.upsert(_entity(project, "uc_insp_ent"))
        merged, _ = repos.entities.upsert(_entity(project, "UC_INSP_ENT"))
        assert merged.name == "uc_insp_ent"

    def test_confidence_only_moves_up(self, repos, project):
        strong = _entity(project, "UC_INSP_ENT")
        strong.confidence = CONFIRMED
        repos.entities.upsert(strong)

        weak = _entity(project, "UC_INSP_ENT")
        weak.confidence = MENTION
        weak.verification_status = VerificationStatus.INFERRED
        merged, _ = repos.entities.upsert(weak)

        assert merged.confidence == CONFIRMED
        assert merged.verification_status is VerificationStatus.CONFIRMED

    def test_a_stronger_sighting_upgrades_the_entity(self, repos, project):
        weak = _entity(project, "UC_INSP_ENT")
        weak.confidence = MENTION
        weak.verification_status = VerificationStatus.INFERRED
        repos.entities.upsert(weak)

        strong = _entity(project, "UC_INSP_ENT")
        strong.confidence = CONFIRMED
        merged, _ = repos.entities.upsert(strong)

        assert merged.confidence == CONFIRMED
        assert merged.verification_status is VerificationStatus.CONFIRMED

    def test_schema_ambiguity_keeps_entities_separate(self, repos, project):
        repos.entities.upsert(_entity(project, "UC_INSP_ENT"))
        repos.entities.upsert(_entity(project, "UC_INSP_ENT", schema="WMS"))
        assert repos.entities.count(project.id) == 2

    def test_metadata_is_merged(self, repos, project):
        first = _entity(project, "UC_INSP_ENT")
        first.metadata = {"origin": "insert"}
        repos.entities.upsert(first)

        second = _entity(project, "UC_INSP_ENT")
        second.metadata = {"rows": 12}
        merged, _ = repos.entities.upsert(second)

        assert merged.metadata == {"origin": "insert", "rows": 12}


class TestRelationships:
    def _pair(self, repos, project):
        query, _ = repos.entities.upsert(
            _entity(project, "Q1", entity_type=EntityType.SQL_QUERY)
        )
        table, _ = repos.entities.upsert(_entity(project, "UC_INSP_ENT"))
        return query, table

    def _relationship(self, project, file_record, source, target, confidence=CONFIRMED):
        return Relationship(
            project_id=project.id,
            source_entity_id=source.id,
            relation_type=RelationType.QUERY_WRITES_TABLE,
            target_entity_id=target.id,
            identity_key=relationship_identity_key(
                source.id, RelationType.QUERY_WRITES_TABLE, target.id, file_record.id
            ),
            source_file_id=file_record.id,
            start_line=18,
            end_line=29,
            evidence_snippet="insert into uc_insp_ent ...",
            confidence=confidence,
            analyzer="sql",
        )

    def test_duplicates_collapse_on_identity(self, repos, project, file_record):
        source, target = self._pair(repos, project)
        first = repos.relationships.upsert(
            self._relationship(project, file_record, source, target)
        )
        second = repos.relationships.upsert(
            self._relationship(project, file_record, source, target)
        )
        assert first.id == second.id
        assert repos.relationships.count(project.id) == 1

    def test_a_weaker_duplicate_does_not_downgrade(self, repos, project, file_record):
        source, target = self._pair(repos, project)
        repos.relationships.upsert(
            self._relationship(project, file_record, source, target, CONFIRMED)
        )
        weaker = self._relationship(
            project, file_record, source, target, STRONG_INFERENCE
        )
        weaker.status = VerificationStatus.INFERRED
        stored = repos.relationships.upsert(weaker)
        assert stored.confidence == CONFIRMED

    def test_deleting_a_file_removes_the_edges_it_proved(
        self, repos, project, file_record
    ):
        source, target = self._pair(repos, project)
        repos.relationships.upsert(
            self._relationship(project, file_record, source, target)
        )
        assert repos.relationships.delete_by_file(file_record.id) == 1
        assert repos.relationships.count(project.id) == 0

    def test_incoming_and_outgoing(self, repos, project, file_record):
        source, target = self._pair(repos, project)
        repos.relationships.upsert(
            self._relationship(project, file_record, source, target)
        )
        assert len(repos.relationships.outgoing(source.id)) == 1
        assert len(repos.relationships.incoming(target.id)) == 1
        assert repos.relationships.outgoing(target.id) == []


class TestEvidence:
    def test_evidence_cascades_when_its_relationship_disappears(
        self, repos, project, file_record, connection
    ):
        source, _ = repos.entities.upsert(
            _entity(project, "Q1", entity_type=EntityType.SQL_QUERY)
        )
        target, _ = repos.entities.upsert(_entity(project, "UC_INSP_ENT"))
        relationship = repos.relationships.upsert(
            Relationship(
                project_id=project.id,
                source_entity_id=source.id,
                relation_type=RelationType.QUERY_READS_TABLE,
                target_entity_id=target.id,
                identity_key="k1",
                source_file_id=file_record.id,
                analyzer="sql",
            )
        )
        repos.evidence.add(
            Evidence(
                project_id=project.id,
                relationship_id=relationship.id,
                file_id=file_record.id,
                snippet="select ... from uc_insp_ent",
                analyzer="sql",
            )
        )
        connection.commit()
        assert repos.evidence.count(project.id) == 1

        repos.relationships.delete_by_file(file_record.id)
        connection.commit()
        assert repos.evidence.count(project.id) == 0

    def test_original_spelling_survives_deduplication(self, repos, project, file_record):
        entity, _ = repos.entities.upsert(_entity(project, "UC_INSP_ENT"))
        repos.evidence.add(
            Evidence(
                project_id=project.id,
                entity_id=entity.id,
                file_id=file_record.id,
                snippet="insert into uc_insp_ent",
                original_name="uc_insp_ent",
                analyzer="sql",
            )
        )
        stored = repos.evidence.for_entity(entity.id)
        assert stored[0].original_name == "uc_insp_ent"


class TestFiles:
    def test_soft_delete_keeps_the_row_and_its_history(self, repos, project, file_record):
        repos.file_versions.record(
            file_id=file_record.id,
            project_id=project.id,
            content_hash="a" * 64,
            size_bytes=100,
            modified_at=None,
            change_kind=ChangeKind.ADDED,
        )
        repos.files.mark_deleted(file_record.id)

        assert repos.files.count(project.id) == 0
        assert repos.files.count(project.id, include_deleted=True) == 1
        assert len(repos.file_versions.history(file_record.id)) == 1

    def test_pending_analysis_lists_only_files_whose_hash_moved(
        self, repos, project, file_record
    ):
        assert [f.id for f in repos.files.pending_analysis(project.id)] == [file_record.id]

        repos.files.set_analysis_status(
            file_record.id, FileAnalysisStatus.ANALYZED, analyzed_hash="a" * 64
        )
        assert repos.files.pending_analysis(project.id) == []

    def test_path_index_includes_deleted_files(self, repos, project, file_record):
        repos.files.mark_deleted(file_record.id)
        index = repos.files.path_index(project.id)
        assert "sql/guardar.sql" in index
        assert index["sql/guardar.sql"].is_deleted is True


class TestRunsAndSettings:
    def test_run_lifecycle(self, repos, project):
        run = repos.runs.start(project.id, trigger="test")
        run.files_scanned = 7
        run.files_added = 7
        repos.runs.finish(run, AnalysisRunStatus.COMPLETED)

        stored = repos.runs.latest(project.id)
        assert stored is not None
        assert stored.status is AnalysisRunStatus.COMPLETED
        assert stored.files_scanned == 7
        assert stored.finished_at is not None

    def test_settings_round_trip_json_values(self, repos):
        repos.settings.set("theme", {"mode": "dark", "accent": "#3ba3ff"})
        assert repos.settings.get("theme")["mode"] == "dark"
        repos.settings.set("theme", {"mode": "light"})
        assert repos.settings.get("theme") == {"mode": "light"}
        assert repos.settings.get("missing", "fallback") == "fallback"

    def test_project_settings_are_scoped(self, repos, project):
        repos.settings.set("max_depth", 10)
        repos.settings.set("max_depth", 3, project_id=project.id)
        assert repos.settings.get("max_depth") == 10
        assert repos.settings.get("max_depth", project_id=project.id) == 3

    def test_deleting_a_project_removes_its_knowledge(
        self, repos, project, file_record, connection
    ):
        entity, _ = repos.entities.upsert(_entity(project, "UC_INSP_ENT"))
        repos.evidence.add(
            Evidence(project_id=project.id, entity_id=entity.id, file_id=file_record.id)
        )
        connection.commit()

        repos.projects.delete(project.id)
        connection.commit()

        assert repos.entities.count(project.id) == 0
        assert repos.files.count(project.id, include_deleted=True) == 0
        assert repos.evidence.count(project.id) == 0
