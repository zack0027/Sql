"""Join extraction, the ER model and the report's band structure.

Two views the interface offers, and the honesty constraint behind both: the ER
links come from join conditions rather than declared foreign keys, and the
report preview describes structure rather than rendering output.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hana_engine.analyzers.sql import SqlAnalyzer
from hana_engine.analyzers.sqltext import blank_noise, find_statements, join_conditions
from hana_engine.domain.analysis import AnalysisContext
from hana_engine.domain.types import EntityType, RelationType
from hana_engine.engine import KnowledgeEngine, build_default_registry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def analyze_sql(sql: str):
    return SqlAnalyzer().analyze(
        AnalysisContext(
            project_id="P",
            file_id="F",
            relative_path="sql/x.sql",
            absolute_path="/tmp/sql/x.sql",
            extension=".sql",
            detected_type="sql",
            content=sql,
        )
    )


def joins(result):
    by_ref = {draft.ref: draft for draft in result.entities}
    return {
        (
            by_ref[edge.source_ref].normalized_name,
            by_ref[edge.target_ref].normalized_name,
            edge.metadata.get("left_column"),
            edge.metadata.get("right_column"),
        )
        for edge in result.relationships
        if edge.relation_type is RelationType.TABLE_JOINS_TABLE
    }


class TestJoinConditions:
    def test_finds_an_equality_between_two_qualified_columns(self):
        statements = find_statements(blank_noise("select 1 from a x join b y on x.id = y.id"))
        found = join_conditions(statements[0])
        assert len(found) == 1
        assert found[0].left_column == "id"

    def test_a_self_comparison_links_nothing(self):
        statements = find_statements(blank_noise("select 1 from a x where x.id = x.id"))
        assert join_conditions(statements[0]) == []

    def test_a_comparison_against_a_literal_is_a_filter_not_a_link(self):
        statements = find_statements(blank_noise("select 1 from a x where x.id = 5"))
        assert join_conditions(statements[0]) == []

    def test_a_comparison_against_a_bind_variable_is_not_a_link(self):
        statements = find_statements(
            blank_noise("select 1 from a x where x.id = :P117_NUMCTL")
        )
        assert join_conditions(statements[0]) == []


class TestTableJoins:
    def test_an_explicit_join_relates_the_two_tables(self):
        result = analyze_sql(
            "select 1 from uc_insp_ent e join prtmst p on p.prtnum = e.prtnum"
        )
        assert joins(result) == {("PRTMST", "UC_INSP_ENT", "PRTNUM", "PRTNUM")}

    def test_a_join_written_in_the_where_clause_counts_too(self):
        """Plenty of production SQL joins in WHERE; that relates them just as firmly."""
        result = analyze_sql(
            "select 1 from uc_insp_ent e, prtmst p where p.prtnum = e.prtnum"
        )
        assert len(joins(result)) == 1

    def test_the_pair_is_recorded_once_regardless_of_direction(self):
        # Drawing both directions would double every line in the diagram.
        result = analyze_sql(
            "select 1 from a x join b y on x.id = y.id and y.other = x.other"
        )
        assert len(joins(result)) == 1

    def test_an_unknown_qualifier_produces_no_edge(self):
        """Guessing which table an unknown alias meant would fabricate a link."""
        result = analyze_sql("select 1 from uc_insp_ent e where zz.id = e.numctl")
        assert joins(result) == set()

    def test_the_link_records_that_it_came_from_a_query(self):
        result = analyze_sql("select 1 from a x join b y on x.id = y.id")
        edge = next(
            edge
            for edge in result.relationships
            if edge.relation_type is RelationType.TABLE_JOINS_TABLE
        )
        assert edge.metadata["source"] == "join_condition"
        assert edge.confidence == 1.0

    def test_a_join_against_a_cte_is_not_a_table_relationship(self):
        """The fixture joins PRTMST to a WITH clause, which is not an object.

        Recording it would put a table in the diagram that does not exist in the
        database.
        """
        sql = (FIXTURES / "sql" / "consulta_inspecciones.sql").read_text(encoding="utf-8")
        result = analyze_sql(sql)
        names = {name for pair in joins(result) for name in pair[:2]}
        assert "RECIENTES" not in names


# ---------------------------------------------------------------------------


@pytest.fixture
def analyzed(db_path: Path, tmp_path: Path):
    root = tmp_path / "proyecto"
    (root / "sql").mkdir(parents=True)
    (root / "reports").mkdir()
    shutil.copy(FIXTURES / "sql" / "consulta_inspecciones.sql", root / "sql")
    shutil.copy(FIXTURES / "sql" / "guardar_inspeccion.sql", root / "sql")
    shutil.copy(FIXTURES / "jrxml" / "Usr-RptInspeccion.jrxml", root / "reports")
    # A direct table-to-table join: the shipped fixtures only join against a
    # CTE, which correctly yields no relationship for the diagram.
    (root / "sql" / "union.sql").write_text(
        "select e.numctl, p.prtdsc\n"
        "  from uc_insp_ent e\n"
        "  join prtmst p on p.prtnum = e.prtnum;\n",
        encoding="utf-8",
    )

    engine = KnowledgeEngine(db_path, registry=build_default_registry())
    project = engine.open_project(root)
    engine.analyze_project(project.id)
    yield engine, project.id
    engine.close()


class TestErModel:
    def test_returns_tables_with_their_columns(self, analyzed):
        engine, project_id = analyzed
        model = engine.queries.er_model(project_id)
        names = {table["normalized_name"] for table in model["tables"]}
        assert "UC_INSP_ENT" in names

        table = next(t for t in model["tables"] if t["normalized_name"] == "UC_INSP_ENT")
        columns = {column["normalized_name"] for column in table["columns"]}
        assert "NETWGT" in columns

    def test_links_carry_the_joining_columns_and_their_evidence(self, analyzed):
        engine, project_id = analyzed
        model = engine.queries.er_model(project_id)
        assert model["links"]
        link = model["links"][0]
        assert link["left_column"]
        assert link["right_column"]
        assert link["evidence"]["file_path"]
        assert link["evidence"]["start_line"]

    def test_it_says_where_the_links_came_from(self, analyzed):
        """The caller must not be able to mistake this for the real schema."""
        engine, project_id = analyzed
        assert engine.queries.er_model(project_id)["derived_from"] == "join_conditions"

    def test_can_be_narrowed_to_specific_tables(self, analyzed):
        engine, project_id = analyzed
        every = engine.queries.er_model(project_id)
        one = engine.queries.er_model(
            project_id, table_ids=[every["tables"][0]["id"]]
        )
        assert len(one["tables"]) == 1

    def test_an_empty_project_answers_cleanly(self, analyzed):
        engine, _ = analyzed
        model = engine.queries.er_model("NO_EXISTE")
        assert model == {"tables": [], "links": [], "derived_from": "join_conditions"}


class TestReportStructure:
    def report(self, engine, project_id):
        hits = engine.queries.resolve(
            project_id, "Usr-RptInspeccion", entity_type=EntityType.JASPER_REPORT
        )
        assert hits
        return engine.queries.report_structure(hits[0].id)

    def test_bands_are_recorded_in_printing_order(self, analyzed):
        engine, project_id = analyzed
        structure = self.report(engine, project_id)
        sections = [band["section"] for band in structure["bands"]]
        assert "title" in sections
        assert "detail" in sections
        assert sections.index("title") < sections.index("detail")

    def test_each_band_lists_its_elements_with_geometry(self, analyzed):
        engine, project_id = analyzed
        structure = self.report(engine, project_id)
        detail = next(b for b in structure["bands"] if b["section"] == "detail")
        assert detail["elements"]
        element = detail["elements"][0]
        assert element["kind"]
        assert element["width"] is not None

    def test_elements_record_the_fields_they_consume(self, analyzed):
        engine, project_id = analyzed
        structure = self.report(engine, project_id)
        references = {
            reference
            for band in structure["bands"]
            for element in band["elements"]
            for reference in element["references"]
        }
        assert "$F{numctl}" in references

    def test_the_image_element_is_found_in_the_title(self, analyzed):
        engine, project_id = analyzed
        structure = self.report(engine, project_id)
        title = next(b for b in structure["bands"] if b["section"] == "title")
        assert any(element["kind"] == "image" for element in title["elements"])

    def test_the_subreport_is_part_of_the_detail_band(self, analyzed):
        engine, project_id = analyzed
        structure = self.report(engine, project_id)
        detail = next(b for b in structure["bands"] if b["section"] == "detail")
        assert any(element["kind"] == "subreport" for element in detail["elements"])

    def test_asking_a_non_report_returns_nothing(self, analyzed):
        engine, project_id = analyzed
        table = engine.queries.resolve(
            project_id, "UC_INSP_ENT", entity_type=EntityType.ORACLE_TABLE
        )[0]
        assert engine.queries.report_structure(table.id) is None

    def test_an_unknown_id_returns_nothing(self, analyzed):
        engine, _ = analyzed
        assert engine.queries.report_structure("NO_EXISTE") is None
