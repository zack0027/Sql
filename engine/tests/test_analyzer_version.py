"""Knowledge must not go stale when the analyzers learn something new.

Incremental analysis decides what to re-read by content hash. That is right for
files that change and wrong for analyzers that change: adding band extraction to
the JRXML analyzer left eighty-six already-analysed reports without bands,
because not one of their bytes had moved. These tests pin the fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hana_engine.domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    Analyzer,
    AnalyzerRegistry,
    EntityDraft,
)
from hana_engine.domain.types import EntityType
from hana_engine.engine import KnowledgeEngine


class BasicAnalyzer(Analyzer):
    name = "demo"
    supported_extensions = (".sql",)
    version = 1

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        return AnalysisResult(
            entities=[EntityDraft(EntityType.ORACLE_TABLE, "TABLA_BASE")]
        )


class ImprovedAnalyzer(Analyzer):
    """Same analyzer, taught to find one more thing."""

    name = "demo"
    supported_extensions = (".sql",)
    version = 2

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        return AnalysisResult(
            entities=[
                EntityDraft(EntityType.ORACLE_TABLE, "TABLA_BASE"),
                EntityDraft(EntityType.ORACLE_TABLE, "TABLA_NUEVA"),
            ]
        )


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "proyecto"
    root.mkdir()
    (root / "a.sql") .write_text("select 1 from dual;", encoding="utf-8")
    return root


def engine_with(db_path: Path, analyzer: Analyzer) -> KnowledgeEngine:
    registry = AnalyzerRegistry()
    registry.register(analyzer)
    return KnowledgeEngine(db_path, registry=registry)


class TestFingerprint:
    def test_includes_each_analyzer_version(self):
        registry = AnalyzerRegistry()
        registry.register(BasicAnalyzer())
        assert registry.fingerprint() == "demo@1"

    def test_changes_when_an_analyzer_is_upgraded(self):
        old, new = AnalyzerRegistry(), AnalyzerRegistry()
        old.register(BasicAnalyzer())
        new.register(ImprovedAnalyzer())
        assert old.fingerprint() != new.fingerprint()

    def test_is_stable_regardless_of_registration_order(self):
        first, second = AnalyzerRegistry(), AnalyzerRegistry()
        first.register(BasicAnalyzer())
        first.register(_Other())
        second.register(_Other())
        second.register(BasicAnalyzer())
        assert first.fingerprint() == second.fingerprint()

    def test_an_empty_registry_still_has_one(self):
        assert AnalyzerRegistry().fingerprint() == "empty"


class _Other(Analyzer):
    name = "otro"
    supported_extensions = (".txt",)

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        return AnalysisResult()


class TestReanalysisOnUpgrade:
    def test_an_unchanged_file_is_re_read_by_a_newer_analyzer(
        self, db_path: Path, project_dir: Path
    ):
        with engine_with(db_path, BasicAnalyzer()) as engine:
            project = engine.open_project(project_dir)
            engine.analyze_project(project.id)
            names = {
                entity.normalized_name
                for entity in engine.repos.entities.list_by_project(
                    project.id, entity_type=EntityType.ORACLE_TABLE
                )
            }
            assert names == {"TABLA_BASE"}
            project_id = project.id

        # Same bytes on disk, better analyzer.
        with engine_with(db_path, ImprovedAnalyzer()) as engine:
            run = engine.analyze_project(project_id)
            assert run.files_modified == 0
            assert run.files_reanalyzed == 1
            assert run.files_analyzed == 1

            names = {
                entity.normalized_name
                for entity in engine.repos.entities.list_by_project(
                    project_id, entity_type=EntityType.ORACLE_TABLE
                )
            }
            assert names == {"TABLA_BASE", "TABLA_NUEVA"}

    def test_running_the_same_suite_twice_does_no_work(
        self, db_path: Path, project_dir: Path
    ):
        with engine_with(db_path, ImprovedAnalyzer()) as engine:
            project = engine.open_project(project_dir)
            engine.analyze_project(project.id)
            run = engine.analyze_project(project.id)
            assert run.files_reanalyzed == 0
            assert run.files_analyzed == 0

    def test_the_suite_version_is_recorded_against_the_file(
        self, db_path: Path, project_dir: Path
    ):
        with engine_with(db_path, BasicAnalyzer()) as engine:
            project = engine.open_project(project_dir)
            engine.analyze_project(project.id)
            record = engine.repos.files.get_by_path(project.id, "a.sql")
            assert record.analyzed_by == "demo@1"

    def test_files_analysed_before_the_column_existed_count_as_stale(
        self, db_path: Path, project_dir: Path
    ):
        """A NULL means "analysed by an unknown suite", which cannot be trusted."""
        with engine_with(db_path, ImprovedAnalyzer()) as engine:
            project = engine.open_project(project_dir)
            engine.analyze_project(project.id)
            engine.connection.execute("UPDATE files SET analyzed_by = NULL")
            engine.connection.commit()

            stale = engine.repos.files.stale_for_analyzer(
                project.id, engine.registry.fingerprint()
            )
            assert len(stale) == 1
