"""Incremental analysis: change detection and end-to-end pipeline behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from hana_engine.domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    Analyzer,
    AnalyzerMessage,
    AnalyzerRegistry,
    EntityDraft,
    RelationshipDraft,
    SourceSpan,
)
from hana_engine.domain.confidence import CONFIRMED, STRONG_INFERENCE
from hana_engine.domain.models import FileRecord, ScannedFile
from hana_engine.domain.types import (
    AnalysisRunStatus,
    ChangeKind,
    EntityType,
    FileAnalysisStatus,
    RelationType,
    Severity,
    SkipReason,
    VerificationStatus,
)
from hana_engine.pipeline.changes import diff
from hana_engine.pipeline.orchestrator import CancellationToken


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------
def _scanned(path: str, content_hash: str | None = "h1", **kwargs) -> ScannedFile:
    return ScannedFile(
        relative_path=path,
        absolute_path=f"/tmp/{path}",
        extension=".sql",
        size_bytes=kwargs.pop("size_bytes", 10),
        content_hash=content_hash,
        modified_at="2026-01-01T00:00:00Z",
        detected_type="sql",
        **kwargs,
    )


def _known(path: str, content_hash: str | None = "h1", **kwargs) -> FileRecord:
    return FileRecord(
        project_id="P",
        relative_path=path,
        absolute_path=f"/tmp/{path}",
        extension=".sql",
        detected_type="sql",
        size_bytes=kwargs.pop("size_bytes", 10),
        content_hash=content_hash,
        **kwargs,
    )


class TestChangeDetection:
    def test_new_file(self):
        result = diff([_scanned("a.sql")], {})
        assert len(result.added) == 1
        assert result.added[0].kind is ChangeKind.ADDED

    def test_unchanged_file(self):
        result = diff([_scanned("a.sql", "h1")], {"a.sql": _known("a.sql", "h1")})
        assert len(result.unchanged) == 1
        assert result.is_empty

    def test_modified_file(self):
        result = diff([_scanned("a.sql", "h2")], {"a.sql": _known("a.sql", "h1")})
        assert len(result.modified) == 1
        assert result.modified[0].kind is ChangeKind.MODIFIED

    def test_deleted_file(self):
        result = diff([], {"a.sql": _known("a.sql")})
        assert len(result.deleted) == 1
        assert result.deleted[0].record is not None

    def test_already_deleted_file_is_not_reported_again(self):
        result = diff([], {"a.sql": _known("a.sql", is_deleted=True)})
        assert result.deleted == []

    def test_resurrected_file_reuses_its_record(self):
        known = _known("a.sql", "h1", is_deleted=True)
        result = diff([_scanned("a.sql", "h1")], {"a.sql": known})
        assert len(result.added) == 1
        assert result.added[0].record is known  # same row, history preserved

    def test_touching_a_file_without_changing_it_is_not_a_change(self):
        """mtime moved, content did not: re-analysing would be wasted work."""
        scanned = ScannedFile(
            relative_path="a.sql",
            absolute_path="/tmp/a.sql",
            extension=".sql",
            size_bytes=10,
            content_hash="h1",
            modified_at="2030-06-06T00:00:00Z",
            detected_type="sql",
        )
        result = diff([scanned], {"a.sql": _known("a.sql", "h1")})
        assert len(result.unchanged) == 1

    def test_a_skipped_file_that_crosses_the_size_limit_counts_as_modified(self):
        known = _known("big.sql", None, skip_reason=SkipReason.TOO_LARGE, size_bytes=99)
        scanned = _scanned("big.sql", None, skip_reason=SkipReason.TOO_LARGE, size_bytes=500)
        result = diff([scanned], {"big.sql": known})
        assert len(result.modified) == 1

    def test_counts(self):
        result = diff(
            [_scanned("new.sql"), _scanned("same.sql", "h1"), _scanned("edit.sql", "h9")],
            {
                "same.sql": _known("same.sql", "h1"),
                "edit.sql": _known("edit.sql", "h1"),
                "gone.sql": _known("gone.sql", "h1"),
            },
        )
        assert result.counts == {
            "added": 1,
            "modified": 1,
            "unchanged": 1,
            "deleted": 1,
        }
        assert len(result.to_analyze()) == 2


# ---------------------------------------------------------------------------
# Analyzers used by the pipeline tests
# ---------------------------------------------------------------------------
class TableAnalyzer(Analyzer):
    """Records every ``from <table>`` it sees. Enough to prove the plumbing."""

    name = "test-table"
    supported_extensions = (".sql",)

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        result = AnalysisResult()
        query = EntityDraft(
            EntityType.SQL_QUERY,
            context.relative_path,
            span=SourceSpan(1, max(1, len(context.lines))),
            evidence_snippet=context.lines[0] if context.lines else "",
        )
        result.entities.append(query)

        for index, line in enumerate(context.lines, start=1):
            lowered = line.lower().strip()
            if not lowered.startswith("from "):
                continue
            table_name = lowered.split()[1].rstrip(";")
            table = EntityDraft(
                EntityType.ORACLE_TABLE,
                table_name,
                span=SourceSpan(index, index),
                evidence_snippet=line.strip(),
            )
            result.entities.append(table)
            result.relationships.append(
                RelationshipDraft(
                    source_ref=query.ref,
                    relation_type=RelationType.QUERY_READS_TABLE,
                    target_ref=table.ref,
                    span=SourceSpan(index, index),
                    evidence_snippet=line.strip(),
                    confidence=CONFIRMED,
                )
            )
        return result


class ExplodingAnalyzer(Analyzer):
    name = "test-exploding"
    supported_extensions = (".sql",)
    priority = 100  # runs before TableAnalyzer

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        raise RuntimeError("deliberate analyzer failure")


class WarningAnalyzer(Analyzer):
    name = "test-warning"
    supported_extensions = (".sql",)

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        return AnalysisResult(
            warnings=[
                AnalyzerMessage(
                    code="undeclared_field",
                    message="campo usado pero no declarado",
                    severity=Severity.WARNING,
                )
            ]
        )


class DanglingAnalyzer(Analyzer):
    name = "test-dangling"
    supported_extensions = (".sql",)

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        return AnalysisResult(
            relationships=[
                RelationshipDraft(
                    source_ref="does|not||EXIST",
                    relation_type=RelationType.QUERY_READS_TABLE,
                    target_ref="also|not||THERE",
                )
            ]
        )


@pytest.fixture
def sql_project(tmp_path: Path) -> Path:
    root = tmp_path / "sqlproj"
    root.mkdir()
    (root / "a.sql").write_text("select *\nfrom uc_insp_ent\n", encoding="utf-8")
    (root / "b.sql").write_text("select *\nfrom prtmst\n", encoding="utf-8")
    return root


def _engine_with(db_path: Path, *analyzers: Analyzer):
    from hana_engine.engine import KnowledgeEngine

    registry = AnalyzerRegistry()
    for analyzer in analyzers:
        registry.register(analyzer)
    return KnowledgeEngine(db_path, registry=registry)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class TestPipeline:
    def test_first_run_inventories_and_analyses_everything(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            run = engine.analyze_project(project.id)

            assert run.status is AnalysisRunStatus.COMPLETED
            assert run.files_added == 2
            assert run.files_analyzed == 2
            assert engine.repos.entities.count(project.id) > 0

            by_type = engine.repos.relationships.count_by_type(project.id)
            assert by_type[RelationType.QUERY_READS_TABLE.value] == 2
            # Each file also owns a FILE_CONTAINS_ENTITY edge per entity it
            # produced (one query + one table per file).
            assert by_type[RelationType.FILE_CONTAINS_ENTITY.value] == 4

    def test_second_run_without_changes_does_no_work(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            entities_before = engine.repos.entities.count(project.id)

            second = engine.analyze_project(project.id)

            assert second.files_added == 0
            assert second.files_modified == 0
            assert second.files_unchanged == 2
            assert second.files_analyzed == 0
            assert engine.repos.entities.count(project.id) == entities_before

    def test_modifying_one_file_reanalyses_only_that_file(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)

            (sql_project / "a.sql").write_text(
                "select *\nfrom uc_insp_det\n", encoding="utf-8"
            )
            run = engine.analyze_project(project.id)

            assert run.files_modified == 1
            assert run.files_unchanged == 1
            assert run.files_analyzed == 1

    def test_stale_relationships_disappear_when_their_evidence_does(
        self, db_path, sql_project
    ):
        """The property that makes incremental analysis trustworthy."""
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)

            targets = {
                engine.repos.entities.get(rel.target_entity_id).normalized_name
                for rel in _all_relationships(engine, project.id)
            }
            assert "UC_INSP_ENT" in targets

            (sql_project / "a.sql").write_text(
                "select *\nfrom uc_insp_det\n", encoding="utf-8"
            )
            engine.analyze_project(project.id)

            targets = {
                engine.repos.entities.get(rel.target_entity_id).normalized_name
                for rel in _all_relationships(engine, project.id)
            }
            assert "UC_INSP_ENT" not in targets
            assert "UC_INSP_DET" in targets

    def test_entity_ids_survive_a_reanalysis(self, db_path, sql_project):
        """Identity keys are stable, so entity ids must be too.

        Regression: purging orphans before persisting deleted every entity the
        file still defined and re-inserted it under a fresh ULID, breaking any
        stored reference to it (a bookmark, a graph selection, a saved query).
        """
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            before = {
                entity.identity_key: entity.id
                for entity in engine.repos.entities.list_by_project(project.id)
            }

            # Change the file without changing which table it reads.
            (sql_project / "a.sql").write_text(
                "-- comentario nuevo\nselect *\nfrom uc_insp_ent\n", encoding="utf-8"
            )
            run = engine.analyze_project(project.id)

            after = {
                entity.identity_key: entity.id
                for entity in engine.repos.entities.list_by_project(project.id)
            }
            assert after == before
            assert run.files_modified == 1
            assert run.entities_created == 0  # nothing new was learned

    def test_a_file_entity_carries_its_own_evidence(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)

            file_entity = engine.repos.entities.get_by_identity(
                project.id,
                EntityDraft(EntityType.FILE, "a.sql").ref,
            )
            assert file_entity is not None
            evidence = engine.repos.evidence.for_entity(file_entity.id)
            assert evidence
            assert evidence[0].original_name == "a.sql"

    def test_deleting_a_file_removes_its_knowledge_but_keeps_its_history(
        self, db_path, sql_project
    ):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            record = engine.repos.files.get_by_path(project.id, "a.sql")
            assert record is not None

            (sql_project / "a.sql").unlink()
            run = engine.analyze_project(project.id)

            assert run.files_deleted == 1
            by_type = engine.repos.relationships.count_by_type(project.id)
            assert by_type[RelationType.QUERY_READS_TABLE.value] == 1  # only b.sql left
            refreshed = engine.repos.files.get(record.id)
            assert refreshed is not None
            assert refreshed.is_deleted is True
            assert refreshed.analysis_status is FileAnalysisStatus.DELETED
            # Both the add and the delete are in the history.
            assert len(engine.repos.file_versions.history(record.id)) == 2

    def test_a_restored_file_reuses_its_row(self, db_path, sql_project):
        original = (sql_project / "a.sql").read_text(encoding="utf-8")
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            first_id = engine.repos.files.get_by_path(project.id, "a.sql").id

            (sql_project / "a.sql").unlink()
            engine.analyze_project(project.id)

            (sql_project / "a.sql").write_text(original, encoding="utf-8")
            engine.analyze_project(project.id)

            restored = engine.repos.files.get_by_path(project.id, "a.sql")
            assert restored.id == first_id
            assert restored.is_deleted is False
            assert restored.analysis_status is FileAnalysisStatus.ANALYZED

    def test_one_failing_analyzer_does_not_stop_the_others(self, db_path, sql_project):
        with _engine_with(db_path, ExplodingAnalyzer(), TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            run = engine.analyze_project(project.id)

            assert run.status is AnalysisRunStatus.COMPLETED
            assert run.files_analyzed == 2
            by_type = engine.repos.relationships.count_by_type(project.id)
            assert by_type[RelationType.QUERY_READS_TABLE.value] == 2  # the good one ran

            errors = engine.repos.errors.for_project(project.id)
            assert any(error.code == "analyzer_exception" for error in errors)
            assert any(error.analyzer == "test-exploding" for error in errors)

    def test_analyzer_warnings_are_recorded(self, db_path, sql_project):
        with _engine_with(db_path, WarningAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            errors = engine.repos.errors.for_project(project.id)
            assert any(
                error.code == "undeclared_field"
                and error.severity is Severity.WARNING
                for error in errors
            )

    def test_relationships_pointing_at_nothing_are_reported_not_silently_dropped(
        self, db_path, sql_project
    ):
        with _engine_with(db_path, DanglingAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            errors = engine.repos.errors.for_project(project.id)
            assert any(error.code == "unresolved_entity_ref" for error in errors)

    def test_cancellation_stops_the_run_and_records_it(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            token = CancellationToken()
            token.cancel()

            run = engine.analyze_project(project.id, cancellation=token)

            assert run.status is AnalysisRunStatus.CANCELLED
            assert engine.repos.entities.count(project.id) == 0

    def test_progress_is_reported_for_each_phase(self, db_path, sql_project):
        phases: list[str] = []
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(
                project.id, on_progress=lambda event: phases.append(event.phase)
            )
        assert {"scanning", "diffing", "inventory", "analyzing", "finalizing"} <= set(
            phases
        )

    def test_knowledge_survives_closing_and_reopening(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            project_id = project.id
            entities = engine.repos.entities.count(project_id)
            relationships = engine.repos.relationships.count(project_id)

        with _engine_with(db_path, TableAnalyzer()) as reopened:
            assert reopened.repos.entities.count(project_id) == entities
            assert reopened.repos.relationships.count(project_id) == relationships
            assert reopened.get_project(project_id) is not None

    def test_evidence_keeps_file_lines_and_snippet(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)

            relationship = _all_relationships(engine, project.id)[0]
            assert relationship.source_file_id is not None
            assert relationship.start_line == 2
            assert "from" in (relationship.evidence_snippet or "")

            evidence = engine.repos.evidence.for_relationship(relationship.id)
            assert evidence
            assert evidence[0].file_id == relationship.source_file_id
            assert evidence[0].start_line == 2

    def test_a_file_entity_is_created_for_every_analysed_file(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            by_type = engine.repos.entities.count_by_type(project.id)
            assert by_type.get(EntityType.FILE.value) == 2
            assert by_type.get(EntityType.ORACLE_TABLE.value) == 2

    def test_binary_and_ignored_files_are_inventoried_but_never_analysed(
        self, db_path, sample_project
    ):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sample_project)
            engine.analyze_project(project.id)

            image = engine.repos.files.get_by_path(
                project.id, "reports/images/checkboxOn.png"
            )
            assert image is not None
            assert image.skip_reason is SkipReason.BINARY
            assert image.analysis_status is FileAnalysisStatus.PENDING

    def test_project_type_is_detected(self, db_path, sample_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sample_project)
            engine.analyze_project(project.id)
            refreshed = engine.get_project(project.id)
            assert refreshed.project_type != "unknown"

    def test_run_history_accumulates(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            engine.analyze_project(project.id)
            history = engine.analysis_history(project.id)
            assert len(history) == 2
            assert history[0].started_at >= history[1].started_at

    def test_an_externally_supplied_inventory_is_accepted(self, db_path, sql_project):
        """The path the Rust scanner uses: the engine never walks the disk itself."""
        from hana_engine.indexing.scanner import scan_project

        inventory = scan_project(sql_project).files
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            run = engine.analyze_project(project.id, scanned_files=inventory)
            assert run.files_scanned == len(inventory)
            assert run.files_analyzed == 2


class TestEngineFacade:
    def test_opening_the_same_folder_twice_returns_one_project(self, db_path, sql_project):
        with _engine_with(db_path) as engine:
            first = engine.open_project(sql_project)
            second = engine.open_project(str(sql_project) + "/.")
            assert first.id == second.id

    def test_opening_a_missing_folder_is_a_clean_error(self, db_path, tmp_path):
        from hana_engine.engine import ProjectPathError

        with _engine_with(db_path) as engine:
            with pytest.raises(ProjectPathError):
                engine.open_project(tmp_path / "does-not-exist")

    def test_status_reports_real_counts(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            status = engine.status()
            assert status.projects == 1
            assert status.entities > 0
            assert status.relationships > 0
            assert status.fts5_available is True
            assert status.offline is True
            assert status.analyzers == ["test-table"]

    def test_project_stats(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            stats = engine.project_stats(project.id)
            assert stats.files == 2
            assert stats.entities > 0
            assert stats.evidence > 0
            assert stats.last_analysis_at is not None

    def test_file_tree_flags_files_needing_analysis(self, db_path, sql_project):
        with _engine_with(db_path, TableAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            assert all(not item["is_modified"] for item in engine.file_tree(project.id))

            (sql_project / "a.sql").write_text("select 1 from dual;\n", encoding="utf-8")
            engine.analyze_project(project.id)
            tree = {item["relative_path"]: item for item in engine.file_tree(project.id)}
            assert tree["a.sql"]["analysis_status"] == FileAnalysisStatus.ANALYZED.value

    def test_scan_policy_is_persisted_per_project(self, db_path, sql_project):
        from hana_engine.indexing.policy import ScanPolicy

        with _engine_with(db_path) as engine:
            project = engine.open_project(sql_project)
            engine.update_scan_policy(project.id, ScanPolicy(max_depth=3))
            reloaded = engine.scan_policy_for(engine.get_project(project.id))
            assert reloaded.max_depth == 3


def _all_relationships(engine, project_id):
    rows = engine.connection.execute(
        "SELECT * FROM relationships WHERE project_id = ? AND relation_type = ?",
        (project_id, RelationType.QUERY_READS_TABLE.value),
    ).fetchall()
    from hana_engine.domain.models import Relationship

    return [Relationship.from_row(row) for row in rows]


class TestConfidencePropagation:
    class InferringAnalyzer(Analyzer):
        name = "test-inferring"
        supported_extensions = (".sql",)

        def analyze(self, context: AnalysisContext) -> AnalysisResult:
            page = EntityDraft(
                EntityType.APEX_PAGE,
                "117",
                span=SourceSpan(1, 1),
                confidence=STRONG_INFERENCE,
                evidence_snippet=":P117_NUMCTL",
            )
            item = EntityDraft(
                EntityType.APEX_ITEM,
                "P117_NUMCTL",
                span=SourceSpan(1, 1),
                evidence_snippet=":P117_NUMCTL",
            )
            return AnalysisResult(
                entities=[page, item],
                relationships=[
                    RelationshipDraft(
                        source_ref=page.ref,
                        relation_type=RelationType.APEX_PAGE_CONTAINS_ITEM,
                        target_ref=item.ref,
                        span=SourceSpan(1, 1),
                        evidence_snippet=":P117_NUMCTL",
                        confidence=STRONG_INFERENCE,
                    )
                ],
            )

    def test_inferred_knowledge_is_stored_as_inferred(self, db_path, sql_project):
        with _engine_with(db_path, self.InferringAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)

            page = engine.repos.entities.get_by_identity(
                project.id,
                EntityDraft(EntityType.APEX_PAGE, "117").ref,
            )
            assert page is not None
            assert page.verification_status is VerificationStatus.INFERRED
            assert page.confidence == pytest.approx(STRONG_INFERENCE)

            item = engine.repos.entities.get_by_identity(
                project.id, EntityDraft(EntityType.APEX_ITEM, "P117_NUMCTL").ref
            )
            assert item.verification_status is VerificationStatus.CONFIRMED

    def test_low_confidence_entities_can_be_listed(self, db_path, sql_project):
        with _engine_with(db_path, self.InferringAnalyzer()) as engine:
            project = engine.open_project(sql_project)
            engine.analyze_project(project.id)
            assert engine.repos.entities.low_confidence(project.id, threshold=0.95)
