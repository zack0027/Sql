"""Transitive impact analysis.

Two halves. The walk itself is checked against small hand-built graphs, where a
cycle or a weak link can be placed exactly where it needs to be. The result is
then checked against a really analysed project, because a traversal that is
correct on a toy graph and finds nothing on real code is still useless.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from hana_engine.domain.types import EntityType, RelationType
from hana_engine.engine import KnowledgeEngine, build_default_registry
from hana_engine.query.impact import analyze_impact

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


# --- a graph small enough to reason about -----------------------------------


@dataclass
class FakeEntity:
    id: str
    entity_type: str = "OracleTable"
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "name": self.name or self.id,
            "normalized_name": (self.name or self.id).upper(),
            "qualified_name": None,
            "confidence": 1.0,
            "verification_status": "confirmed",
            "file_path": "x.sql",
            "start_line": 1,
        }


class Graph:
    """A hand-built graph: `add("a", "b")` means a → b."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE files (
                id TEXT PRIMARY KEY, relative_path TEXT, absolute_path TEXT
            );
            CREATE TABLE relationships (
                source_entity_id TEXT, target_entity_id TEXT, relation_type TEXT,
                confidence REAL, status TEXT, analyzer TEXT,
                start_line INTEGER, end_line INTEGER, evidence_snippet TEXT,
                source_file_id TEXT
            );
            INSERT INTO files VALUES ('f1', 'sql/prueba.sql', '/tmp/sql/prueba.sql');
            """
        )
        self.types: dict[str, str] = {}

    def add(
        self,
        source: str,
        target: str,
        *,
        confidence: float = 1.0,
        status: str = "confirmed",
        relation: RelationType = RelationType.QUERY_READS_TABLE,
    ) -> Graph:
        self.connection.execute(
            "INSERT INTO relationships VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                source,
                target,
                relation.value,
                confidence,
                status,
                "prueba",
                7,
                7,
                "select 1",
                "f1",
            ),
        )
        return self

    def typed(self, entity_id: str, entity_type: str) -> Graph:
        self.types[entity_id] = entity_type
        return self

    def entity_of(self, entity_id: str) -> FakeEntity | None:
        return FakeEntity(entity_id, self.types.get(entity_id, "OracleTable"))

    def impact(self, entity_id: str, **kwargs: Any):
        return analyze_impact(
            self.connection, entity_id, entity_of=self.entity_of, **kwargs
        )


def reached(report) -> set[str]:
    return {node.entity["id"] for node in report.nodes}


def node_for(report, entity_id: str):
    return next(node for node in report.nodes if node.entity["id"] == entity_id)


class TestTheWalk:
    def test_a_chain_of_three_hops(self):
        """column ← query ← report, the shape the product turns on."""
        graph = Graph().add("query", "column").add("report", "query")
        report = graph.impact("column")
        assert reached(report) == {"query", "report"}
        assert node_for(report, "report").depth == 2
        assert node_for(report, "report").path == ["column", "query", "report"]

    def test_a_cycle_terminates_and_repeats_nothing(self):
        """PL/SQL has mutual recursion; without a visited set this never returns."""
        graph = Graph().add("a", "b").add("b", "a")
        report = graph.impact("a", depth=10)
        assert reached(report) == {"b"}
        assert len(report.nodes) == 1

    def test_a_longer_cycle_terminates(self):
        graph = Graph().add("a", "b").add("b", "c").add("c", "a")
        report = graph.impact("a", depth=50)
        assert reached(report) == {"b", "c"}

    def test_depth_cuts_where_it_should(self):
        graph = Graph().add("b", "a").add("c", "b").add("d", "c")
        assert reached(graph.impact("a", depth=1)) == {"b"}
        assert reached(graph.impact("a", depth=2)) == {"b", "c"}
        assert reached(graph.impact("a", depth=3)) == {"b", "c", "d"}
        assert graph.impact("a", depth=2).max_depth_reached == 2

    def test_direction_can_be_reversed(self):
        graph = Graph().add("a", "b")
        assert reached(graph.impact("a")) == set()
        assert reached(graph.impact("a", direction="outgoing")) == {"b"}

    def test_an_inferred_link_marks_the_whole_path(self):
        graph = (
            Graph()
            .add("b", "a", confidence=0.9, status="inferred")
            .add("c", "b")
        )
        report = graph.impact("a")
        assert node_for(report, "b").inferred_in_path is True
        # The inference is upstream of c, so c cannot be presented as certain.
        assert node_for(report, "c").inferred_in_path is True

    def test_a_confirmed_path_is_not_marked(self):
        graph = Graph().add("b", "a").add("c", "b")
        report = graph.impact("a")
        assert all(node.inferred_in_path is False for node in report.nodes)

    def test_min_confidence_is_the_weakest_link_not_the_last(self):
        """The whole point: a chain is only as good as its worst step."""
        graph = (
            Graph()
            .add("b", "a", confidence=0.5, status="inferred")
            .add("c", "b", confidence=1.0)
        )
        report = graph.impact("a")
        assert node_for(report, "b").min_confidence == pytest.approx(0.5)
        assert node_for(report, "c").min_confidence == pytest.approx(0.5)

    def test_the_best_path_wins_when_two_reach_the_same_node(self):
        graph = (
            Graph()
            .add("hub", "a", confidence=0.4, status="inferred")
            .add("hub", "a", confidence=1.0)
        )
        assert node_for(graph.impact("a"), "hub").min_confidence == pytest.approx(1.0)

    def test_containment_is_excluded_by_default(self):
        """A file contains everything; follow it and impact means the project."""
        graph = Graph().add(
            "file", "a", relation=RelationType.FILE_CONTAINS_ENTITY
        )
        assert reached(graph.impact("a")) == set()
        assert reached(graph.impact("a", include_containment=True)) == {"file"}

    def test_truncation_is_reported(self):
        graph = Graph()
        for index in range(10):
            graph.add(f"n{index}", "a")
        report = graph.impact("a", max_nodes=4)
        assert report.truncated is True
        assert len(report.nodes) == 4

    def test_an_untruncated_report_says_so(self):
        graph = Graph().add("b", "a")
        assert graph.impact("a", max_nodes=100).truncated is False

    def test_the_root_never_appears_among_the_affected(self):
        graph = Graph().add("a", "b").add("b", "a")
        assert "a" not in reached(graph.impact("a", direction="outgoing"))

    def test_an_unknown_entity_yields_nothing_rather_than_an_invention(self):
        graph = Graph()
        graph.entity_of = lambda entity_id: None  # type: ignore[assignment]
        assert graph.impact("fantasma") is None

    def test_results_are_grouped_by_type(self):
        graph = (
            Graph()
            .typed("q", "SqlQuery")
            .typed("r", "JasperReport")
            .add("q", "a")
            .add("r", "a")
        )
        assert graph.impact("a").by_type == {"SqlQuery": 1, "JasperReport": 1}

    def test_every_node_carries_the_edge_that_brought_it(self):
        graph = Graph().add("b", "a")
        node = node_for(graph.impact("a"), "b")
        assert node.relation_type == RelationType.QUERY_READS_TABLE.value
        assert node.evidence["file_path"] == "sql/prueba.sql"
        assert node.evidence["start_line"] == 7


# --- the same thing over a really analysed project --------------------------


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "inspeccion"
    (root / "sql").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "moca").mkdir()
    shutil.copy(FIXTURES / "sql" / "guardar_inspeccion.sql", root / "sql")
    shutil.copy(FIXTURES / "sql" / "consulta_inspecciones.sql", root / "sql")
    shutil.copy(FIXTURES / "sql" / "pkg_inspeccion.pkb", root / "sql")
    shutil.copy(FIXTURES / "jrxml" / "Usr-RptInspeccion.jrxml", root / "reports")
    shutil.copy(FIXTURES / "moca" / "confirmar_inspeccion.mcmd", root / "moca")
    return root


@pytest.fixture
def engine(db_path: Path, project_dir: Path):
    instance = KnowledgeEngine(db_path, registry=build_default_registry())
    project = instance.open_project(project_dir)
    instance.analyze_project(project.id)
    instance.project_id = project.id
    yield instance
    instance.close()


def resolve(engine, name: str, entity_type: EntityType) -> str:
    hits = engine.queries.resolve(engine.project_id, name, entity_type=entity_type)
    assert hits, f"no se encontró {name}"
    return hits[0].id


class TestImpactOnRealCode:
    @pytest.fixture
    def report(self, engine):
        column = resolve(engine, "UC_INSP_ENT.NETWGT", EntityType.ORACLE_COLUMN)
        return engine.queries.impact(column)

    def test_it_reaches_the_apex_item_the_page_and_the_report(self, report):
        """The acceptance scenario, end to end, from one column."""
        by_name = {node.entity["normalized_name"]: node for node in report.nodes}
        assert "P117_NETWGT" in by_name
        assert "117" in by_name
        assert "Usr-RptInspeccion" in by_name

    def test_the_page_is_marked_as_reached_through_an_inference(self, report):
        """`P117_NETWGT` belongs to page 117 by convention, not by syntax."""
        page = next(
            node for node in report.nodes if node.entity["normalized_name"] == "117"
        )
        assert page.inferred_in_path is True
        assert page.min_confidence < 1.0

    def test_the_report_is_reached_without_an_inference(self, report):
        jasper = next(
            node
            for node in report.nodes
            if node.entity["normalized_name"] == "Usr-RptInspeccion"
        )
        assert jasper.inferred_in_path is False
        assert jasper.min_confidence == pytest.approx(1.0)

    def test_every_node_opens_a_real_file_at_a_real_line(self, report):
        """Impact is only actionable if each result can be gone and looked at."""
        assert report.nodes
        for node in report.nodes:
            evidence = node.evidence
            assert evidence["file_path"], node.entity["name"]
            assert evidence["start_line"], node.entity["name"]
            source = Path(evidence["absolute_path"]).read_text(encoding="utf-8")
            assert evidence["start_line"] <= len(source.splitlines())

    def test_a_tables_impact_does_not_drag_in_the_whole_project(self, engine):
        table = resolve(engine, "UC_INSP_ENT", EntityType.ORACLE_TABLE)
        total = engine.repos.entities.count(engine.project_id)
        reached_count = len(engine.queries.impact(table, depth=6).nodes)
        assert reached_count < total

    def test_containment_makes_it_drag_in_much_more(self, engine):
        table = resolve(engine, "UC_INSP_ENT", EntityType.ORACLE_TABLE)
        without = len(engine.queries.impact(table, depth=6).nodes)
        with_containment = len(
            engine.queries.impact(table, depth=6, include_containment=True).nodes
        )
        assert with_containment > without

    def test_the_call_graph_is_walked(self, engine):
        """A change to a called routine reaches the routine that calls it."""
        routine = resolve(engine, "TOTAL_NETO", EntityType.ORACLE_FUNCTION)
        names = {
            node.entity["normalized_name"]
            for node in engine.queries.impact(routine).nodes
        }
        assert "CERRAR_INSPECCION" in names

    def test_reversing_it_asks_the_other_question(self, engine):
        report_id = resolve(
            engine, "Usr-RptInspeccion", EntityType.JASPER_REPORT
        )
        depends_on = {
            node.entity["normalized_name"]
            for node in engine.queries.impact(report_id, direction="outgoing").nodes
        }
        assert "UC_INSP_ENT" in depends_on
