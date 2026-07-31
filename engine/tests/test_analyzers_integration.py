"""The analyzers running through the real pipeline.

The unit tests check each analyzer in isolation. These check the thing the user
actually experiences: point HANA at a folder, and the knowledge graph that comes
out connects an APEX item to an Oracle column to a Jasper report — with evidence
that opens the right file at the right line.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hana_engine.domain.types import EntityType, RelationType, VerificationStatus
from hana_engine.engine import KnowledgeEngine, build_default_registry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "inspeccion"
    (root / "sql").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "moca").mkdir()
    (root / "config").mkdir()

    shutil.copy(FIXTURES / "sql" / "guardar_inspeccion.sql", root / "sql")
    shutil.copy(FIXTURES / "sql" / "consulta_inspecciones.sql", root / "sql")
    shutil.copy(FIXTURES / "sql" / "pkg_inspeccion.pkb", root / "sql")
    shutil.copy(FIXTURES / "jrxml" / "Usr-RptInspeccion.jrxml", root / "reports")
    shutil.copy(FIXTURES / "moca" / "confirmar_inspeccion.mcmd", root / "moca")
    shutil.copy(FIXTURES / "json" / "apex_inspeccion.json", root / "config")
    return root


@pytest.fixture
def analyzed(db_path: Path, project_dir: Path):
    engine = KnowledgeEngine(db_path, registry=build_default_registry())
    project = engine.open_project(project_dir)
    run = engine.analyze_project(project.id)
    yield engine, project, run
    engine.close()


def entity_names(engine, project_id: str, entity_type: EntityType) -> set[str]:
    return {
        entity.normalized_name
        for entity in engine.repos.entities.list_by_project(
            project_id, entity_type=entity_type, limit=1000
        )
    }


def find(engine, project_id: str, entity_type: EntityType, name: str):
    for entity in engine.repos.entities.list_by_project(
        project_id, entity_type=entity_type, limit=1000
    ):
        if entity.normalized_name == name:
            return entity
    return None


class TestTheGraphIsBuilt:
    def test_the_run_completes_without_errors(self, analyzed):
        _, _, run = analyzed
        assert run.status.value == "completed"
        assert run.files_analyzed == 6
        assert run.entities_created > 0
        assert run.relationships_created > 0

    def test_the_acceptance_scenario_entities_all_exist(self, analyzed):
        """An Oracle table, an APEX item and a Jasper report, from one folder."""
        engine, project, _ = analyzed
        assert "UC_INSP_ENT" in entity_names(
            engine, project.id, EntityType.ORACLE_TABLE
        )
        assert "P117_MUESTRA_SIZE_VER" in entity_names(
            engine, project.id, EntityType.APEX_ITEM
        )
        assert "Usr-RptInspeccion" in entity_names(
            engine, project.id, EntityType.JASPER_REPORT
        )
        assert entity_names(engine, project.id, EntityType.MOCA_VARIABLE)

    def test_analyzer_errors_are_none(self, analyzed):
        engine, project, _ = analyzed
        fatal = [
            error
            for error in engine.repos.errors.for_project(project.id)
            if error.severity.value == "error"
        ]
        assert fatal == []

    def test_the_expected_warnings_are_recorded(self, analyzed):
        """The JRXML fixture has a real undeclared field and an unused parameter."""
        engine, project, _ = analyzed
        codes = {error.code for error in engine.repos.errors.for_project(project.id)}
        assert "undeclared_field" in codes
        assert "unused_parameter" in codes


class TestRelationships:
    def test_a_process_writes_the_table(self, analyzed):
        engine, project, _ = analyzed
        table = find(engine, project.id, EntityType.ORACLE_TABLE, "UC_INSP_ENT")
        assert table is not None
        incoming = engine.repos.relationships.incoming(table.id)
        assert any(
            edge.relation_type is RelationType.QUERY_WRITES_TABLE for edge in incoming
        )

    def test_the_report_queries_the_table(self, analyzed):
        engine, project, _ = analyzed
        table = find(engine, project.id, EntityType.ORACLE_TABLE, "UC_INSP_ENT")
        incoming = engine.repos.relationships.incoming(table.id)
        assert any(
            edge.relation_type is RelationType.REPORT_QUERIES_TABLE for edge in incoming
        )

    def test_the_apex_item_maps_to_its_column(self, analyzed):
        engine, project, _ = analyzed
        item = find(
            engine, project.id, EntityType.APEX_ITEM, "P117_MUESTRA_SIZE_VER"
        )
        assert item is not None
        outgoing = engine.repos.relationships.outgoing(item.id)
        mapping = next(
            edge
            for edge in outgoing
            if edge.relation_type is RelationType.APEX_ITEM_MAPS_TO_COLUMN
        )
        column = engine.repos.entities.get(mapping.target_entity_id)
        assert column.qualified_name == "UC_INSP_ENT.MUESTRA_SIZE_VER"
        assert mapping.confidence == 1.0

    def test_the_report_references_its_image(self, analyzed):
        engine, project, _ = analyzed
        report = find(
            engine, project.id, EntityType.JASPER_REPORT, "Usr-RptInspeccion"
        )
        outgoing = engine.repos.relationships.outgoing(report.id)
        images = [
            engine.repos.entities.get(edge.target_entity_id).name
            for edge in outgoing
            if edge.relation_type is RelationType.REPORT_REFERENCES_IMAGE
        ]
        assert "images/checkboxOn.png" in images

    def test_the_call_graph_crosses_files(self, analyzed):
        """`guardar_inspeccion.sql` calls a routine the package body declares.

        Neither analyzer run saw both files — an analyzer only ever gets one.
        The two halves meet because a routine declared inside a package and a
        call that names `pkg_inspeccion.registrar_evento` produce the same
        identity key.
        """
        engine, project, _ = analyzed
        routine = find(
            engine, project.id, EntityType.ORACLE_PROCEDURE, "REGISTRAR_EVENTO"
        )
        assert routine is not None
        assert routine.qualified_name == "PKG_INSPECCION.REGISTRAR_EVENTO"

        callers = {
            engine.repos.entities.get(edge.source_entity_id).normalized_name
            for edge in engine.repos.relationships.incoming(routine.id)
            if edge.relation_type is RelationType.PROCEDURE_CALLS_PROCEDURE
        }
        assert {"CERRAR_INSPECCION", "sql/guardar_inspeccion.sql"} <= callers

    def test_the_report_includes_its_subreport(self, analyzed):
        engine, project, _ = analyzed
        report = find(
            engine, project.id, EntityType.JASPER_REPORT, "Usr-RptInspeccion"
        )
        assert any(
            edge.relation_type is RelationType.REPORT_INCLUDES_SUBREPORT
            for edge in engine.repos.relationships.outgoing(report.id)
        )


class TestProvenance:
    def test_every_relationship_cites_a_file_and_a_line(self, analyzed):
        engine, project, _ = analyzed
        rows = engine.connection.execute(
            "SELECT source_file_id, start_line, analyzer FROM relationships"
            " WHERE project_id = ?",
            (project.id,),
        ).fetchall()
        assert rows
        for row in rows:
            assert row["source_file_id"] is not None
            assert row["start_line"] is not None
            assert row["analyzer"]

    def test_evidence_opens_the_right_line(self, analyzed):
        """The promise behind every edge: click it, land on the proving line."""
        engine, project, _ = analyzed
        item = find(
            engine, project.id, EntityType.APEX_ITEM, "P117_MUESTRA_SIZE_VER"
        )
        mapping = next(
            edge
            for edge in engine.repos.relationships.outgoing(item.id)
            if edge.relation_type is RelationType.APEX_ITEM_MAPS_TO_COLUMN
        )
        evidence = engine.repos.evidence.for_relationship(mapping.id)[0]
        record = engine.repos.files.get(evidence.file_id)

        source_line = Path(record.absolute_path).read_text(encoding="utf-8").splitlines()[
            evidence.start_line - 1
        ]
        assert "MUESTRA_SIZE_VER" in source_line.upper()

    def test_inferences_are_labelled_as_inferences(self, analyzed):
        engine, project, _ = analyzed
        page = find(engine, project.id, EntityType.APEX_PAGE, "117")
        assert page is not None
        assert page.verification_status is VerificationStatus.INFERRED
        assert page.confidence == pytest.approx(0.90)

    def test_confirmed_facts_are_fully_confident(self, analyzed):
        engine, project, _ = analyzed
        rows = engine.connection.execute(
            "SELECT confidence FROM relationships"
            " WHERE project_id = ? AND status = 'confirmed'",
            (project.id,),
        ).fetchall()
        assert rows
        assert all(row["confidence"] == 1.0 for row in rows)


class TestIncrementalWithAnalyzers:
    def test_reanalysing_unchanged_files_changes_nothing(self, analyzed):
        engine, project, _ = analyzed
        before = engine.repos.entities.count(project.id)
        relationships_before = engine.repos.relationships.count(project.id)

        run = engine.analyze_project(project.id)

        assert run.files_analyzed == 0
        assert engine.repos.entities.count(project.id) == before
        assert engine.repos.relationships.count(project.id) == relationships_before

    def test_the_call_graph_survives_a_reanalysis_with_the_same_ids(self, analyzed):
        """Ids must be stable, or every saved annotation would point at a ghost."""
        engine, project, _ = analyzed

        def graph() -> set[tuple[str, str]]:
            rows = engine.connection.execute(
                "SELECT source_entity_id, target_entity_id FROM relationships"
                " WHERE project_id = ? AND relation_type = ?",
                (project.id, RelationType.PROCEDURE_CALLS_PROCEDURE.value),
            ).fetchall()
            return {(row["source_entity_id"], row["target_entity_id"]) for row in rows}

        before = graph()
        assert before

        engine.analyze_project(project.id)
        assert graph() == before

    def test_editing_a_file_updates_only_its_knowledge(self, analyzed, project_dir):
        engine, project, _ = analyzed
        table = find(engine, project.id, EntityType.ORACLE_TABLE, "UC_INSP_ENT")
        report = find(
            engine, project.id, EntityType.JASPER_REPORT, "Usr-RptInspeccion"
        )

        target = project_dir / "sql" / "guardar_inspeccion.sql"
        target.write_text(
            "insert into uc_insp_nueva (numctl) values (:P117_NUMCTL);",
            encoding="utf-8",
        )
        run = engine.analyze_project(project.id)

        assert run.files_modified == 1
        assert run.files_analyzed == 1
        assert "UC_INSP_NUEVA" in entity_names(
            engine, project.id, EntityType.ORACLE_TABLE
        )
        # The report still proves its own edges, untouched by the SQL edit.
        assert engine.repos.entities.get(report.id) is not None
        assert any(
            edge.relation_type is RelationType.REPORT_QUERIES_TABLE
            for edge in engine.repos.relationships.incoming(table.id)
        )

    def test_search_finds_a_table_by_name(self, analyzed):
        engine, project, _ = analyzed
        rows = engine.connection.execute(
            "SELECT e.normalized_name FROM entities_fts f"
            " JOIN entities e ON e.rowid = f.rowid"
            " WHERE entities_fts MATCH ? AND e.project_id = ?",
            ("insp", project.id),
        ).fetchall()
        assert any(row["normalized_name"] == "UC_INSP_ENT" for row in rows)
