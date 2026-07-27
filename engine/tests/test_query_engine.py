"""The deterministic query layer.

These are the ten questions HANA promises to answer without a language model,
checked against a real analysed project rather than fixtures of rows.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hana_engine.domain.types import EntityType, RelationType
from hana_engine.engine import KnowledgeEngine, build_default_registry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "inspeccion"
    (root / "sql").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "moca").mkdir()
    shutil.copy(FIXTURES / "sql" / "guardar_inspeccion.sql", root / "sql")
    shutil.copy(FIXTURES / "sql" / "consulta_inspecciones.sql", root / "sql")
    shutil.copy(FIXTURES / "jrxml" / "Usr-RptInspeccion.jrxml", root / "reports")
    shutil.copy(FIXTURES / "moca" / "confirmar_inspeccion.mcmd", root / "moca")
    return root


@pytest.fixture
def engine(db_path: Path, project_dir: Path):
    instance = KnowledgeEngine(db_path, registry=build_default_registry())
    project = instance.open_project(project_dir)
    instance.analyze_project(project.id)
    instance.project_id = project.id  # convenience for the tests
    yield instance
    instance.close()


def table_id(engine, name: str = "UC_INSP_ENT") -> str:
    hits = engine.queries.resolve(
        engine.project_id, name, entity_type=EntityType.ORACLE_TABLE
    )
    assert hits, f"no se encontró la tabla {name}"
    return hits[0].id


class TestSearch:
    def test_finds_a_table_by_full_name(self, engine):
        names = {hit.normalized_name for hit in engine.queries.search(engine.project_id, "UC_INSP_ENT")}
        assert "UC_INSP_ENT" in names

    def test_finds_by_a_fragment(self, engine):
        names = {hit.normalized_name for hit in engine.queries.search(engine.project_id, "insp")}
        assert any("INSP" in name for name in names)

    def test_finds_an_apex_item(self, engine):
        names = {hit.normalized_name for hit in engine.queries.search(engine.project_id, "P117")}
        assert any(name.startswith("P117_") for name in names)

    def test_punctuation_does_not_break_the_query(self, engine):
        """`UC_INSP_ENT.NUMCTL` contains characters FTS5 reads as operators."""
        engine.queries.search(engine.project_id, "UC_INSP_ENT.NUMCTL")
        engine.queries.search(engine.project_id, 'a"b*c(d)')
        engine.queries.search(engine.project_id, "   ")

    def test_empty_text_returns_nothing(self, engine):
        assert engine.queries.search(engine.project_id, "") == []

    def test_resolve_is_case_and_quote_insensitive(self, engine):
        assert engine.queries.resolve(engine.project_id, "uc_insp_ent")
        assert engine.queries.resolve(engine.project_id, '"UC_INSP_ENT"')

    def test_resolve_can_narrow_by_type(self, engine):
        hits = engine.queries.resolve(
            engine.project_id, "UC_INSP_ENT", entity_type=EntityType.ORACLE_TABLE
        )
        assert all(hit.entity_type == EntityType.ORACLE_TABLE.value for hit in hits)


class TestWhereUsed:
    def test_a_table_reports_its_uses(self, engine):
        hits = engine.queries.where_used(table_id(engine))
        assert hits
        relations = {hit.relation_type for hit in hits}
        assert RelationType.QUERY_WRITES_TABLE.value in relations

    def test_structural_edges_are_excluded_by_default(self, engine):
        """A file *containing* an entity is true, but it is not a use of it."""
        hits = engine.queries.where_used(table_id(engine))
        assert RelationType.FILE_CONTAINS_ENTITY.value not in {
            hit.relation_type for hit in hits
        }

    def test_structural_edges_can_be_requested(self, engine):
        hits = engine.queries.where_used(table_id(engine), include_structural=True)
        assert len(hits) >= len(engine.queries.where_used(table_id(engine)))

    def test_every_use_carries_a_file_and_a_line(self, engine):
        for hit in engine.queries.where_used(table_id(engine)):
            assert hit.evidence.file_path
            assert hit.evidence.start_line

    def test_the_cited_line_really_mentions_the_entity(self, engine):
        """The promise: open the evidence and the proof is there."""
        checked = 0
        for hit in engine.queries.where_used(table_id(engine)):
            if not hit.evidence.absolute_path or not hit.evidence.start_line:
                continue
            lines = Path(hit.evidence.absolute_path).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            window = " ".join(
                lines[max(0, hit.evidence.start_line - 1) : hit.evidence.end_line or hit.evidence.start_line]
            ).upper()
            assert "UC_INSP_ENT" in window or "INSP" in window
            checked += 1
        assert checked > 0

    def test_an_unknown_entity_yields_nothing(self, engine):
        assert engine.queries.where_used("NO_EXISTE") == []


class TestDependencies:
    def test_dependents_and_dependencies_are_opposite_directions(self, engine):
        entity = table_id(engine)
        incoming = engine.queries.dependents(entity)
        outgoing = engine.queries.dependencies(entity)
        assert all(hit.direction == "incoming" for hit in incoming)
        assert all(hit.direction == "outgoing" for hit in outgoing)


class TestTables:
    def test_a_script_reports_the_table_it_writes(self, engine):
        hits = engine.queries.tables_of_file(
            engine.project_id, "sql/guardar_inspeccion.sql", written=True
        )
        assert "UC_INSP_ENT" in {hit.entity.normalized_name for hit in hits}

    def test_a_read_only_script_writes_nothing(self, engine):
        hits = engine.queries.tables_of_file(
            engine.project_id, "sql/consulta_inspecciones.sql", written=True
        )
        assert hits == []

    def test_a_read_only_script_reports_its_reads(self, engine):
        hits = engine.queries.tables_of_file(
            engine.project_id, "sql/consulta_inspecciones.sql", written=False
        )
        names = {hit.entity.normalized_name for hit in hits}
        assert {"UC_INSP_ENT", "PRTMST"} <= names

    def test_without_a_filter_both_directions_come_back(self, engine):
        hits = engine.queries.tables_of_file(
            engine.project_id, "sql/guardar_inspeccion.sql"
        )
        assert hits

    def test_an_unknown_file_yields_nothing(self, engine):
        assert engine.queries.tables_of_file(engine.project_id, "no/existe.sql") == []


class TestApexItems:
    def test_items_of_a_file(self, engine):
        names = {
            hit.normalized_name
            for hit in engine.queries.apex_items_in_file(
                engine.project_id, "sql/guardar_inspeccion.sql"
            )
        }
        assert {"P117_PRTNUM", "P117_MUESTRA_SIZE_VER"} <= names

    def test_a_file_without_items_yields_nothing(self, engine):
        assert (
            engine.queries.apex_items_in_file(
                engine.project_id, "moca/confirmar_inspeccion.mcmd"
            )
            == []
        )


class TestReportsAndImages:
    def test_reports_using_a_table(self, engine):
        hits = engine.queries.reports_using_table(table_id(engine))
        assert "Usr-RptInspeccion" in {hit.entity.name for hit in hits}

    def test_images_of_a_report(self, engine):
        report = engine.queries.resolve(
            engine.project_id, "Usr-RptInspeccion", entity_type=EntityType.JASPER_REPORT
        )[0]
        images = {hit.entity.name for hit in engine.queries.images_of_report(report.id)}
        assert "images/checkboxOn.png" in images


class TestChangesErrorsAndReview:
    def test_the_first_run_reports_every_file_as_added(self, engine):
        result = engine.queries.changes_since(engine.project_id)
        kinds = {change["change_kind"] for change in result["changes"]}
        assert kinds == {"added"}

    def test_editing_a_file_shows_up_as_modified(self, engine, project_dir):
        (project_dir / "sql" / "guardar_inspeccion.sql").write_text(
            "select 1 from dual;", encoding="utf-8"
        )
        engine.analyze_project(engine.project_id)

        result = engine.queries.changes_since(engine.project_id)
        modified = [
            change
            for change in result["changes"]
            if change["change_kind"] == "modified"
        ]
        assert [change["relative_path"] for change in modified] == [
            "sql/guardar_inspeccion.sql"
        ]

    def test_a_project_without_runs_answers_cleanly(self, engine, tmp_path):
        empty = tmp_path / "vacio"
        empty.mkdir()
        project = engine.open_project(empty)
        assert engine.queries.changes_since(project.id) == {
            "run_id": None,
            "changes": [],
        }

    def test_analysis_warnings_are_listed_with_their_file(self, engine):
        rows = engine.queries.files_with_errors(engine.project_id)
        assert rows
        assert any(row["code"] == "undeclared_field" for row in rows)
        assert all(row["severity"] in ("warning", "error") for row in rows)

    def test_errors_can_be_filtered_by_severity(self, engine):
        assert engine.queries.files_with_errors(engine.project_id, severity="error") == []

    def test_low_confidence_finds_the_inferred_apex_page(self, engine):
        hits = engine.queries.low_confidence(engine.project_id, threshold=1.0)
        assert any(hit.entity_type == EntityType.APEX_PAGE.value for hit in hits)

    def test_low_confidence_is_ordered_weakest_first(self, engine):
        hits = engine.queries.low_confidence(engine.project_id, threshold=1.0)
        confidences = [hit.confidence for hit in hits]
        assert confidences == sorted(confidences)


class TestGraphNavigation:
    def test_depth_one_returns_the_immediate_neighbours(self, engine):
        result = engine.queries.neighborhood(table_id(engine), depth=1)
        assert result.nodes[0].entity.normalized_name == "UC_INSP_ENT"
        assert len(result.nodes) > 1
        assert all(node.depth <= 1 for node in result.nodes)

    def test_depth_two_reaches_further(self, engine):
        near = engine.queries.neighborhood(table_id(engine), depth=1)
        far = engine.queries.neighborhood(table_id(engine), depth=2)
        assert len(far.nodes) >= len(near.nodes)

    def test_no_edge_dangles_outside_the_returned_nodes(self, engine):
        """A hairball is useless, but a broken graph is worse."""
        result = engine.queries.neighborhood(table_id(engine), depth=2)
        known = {node.entity.id for node in result.nodes}
        for edge in result.edges:
            assert edge.source_id in known
            assert edge.target_id in known

    def test_the_node_budget_is_honoured_and_reported(self, engine):
        result = engine.queries.neighborhood(table_id(engine), depth=3, max_nodes=3)
        assert len(result.nodes) <= 3
        assert result.truncated is True

    def test_an_unknown_entity_yields_an_empty_graph(self, engine):
        result = engine.queries.neighborhood("NO_EXISTE")
        assert result.nodes == []
        assert result.edges == []

    def test_every_edge_carries_evidence(self, engine):
        result = engine.queries.neighborhood(table_id(engine), depth=1)
        for edge in result.edges:
            assert edge.evidence.analyzer
            assert edge.confidence > 0


class TestSerialisation:
    def test_results_survive_a_json_round_trip(self, engine):
        import json

        payload = {
            "search": [hit.to_dict() for hit in engine.queries.search(engine.project_id, "insp")],
            "uses": [hit.to_dict() for hit in engine.queries.where_used(table_id(engine))],
            "graph": engine.queries.neighborhood(table_id(engine)).to_dict(),
            "changes": engine.queries.changes_since(engine.project_id),
        }
        assert json.loads(json.dumps(payload)) == payload
