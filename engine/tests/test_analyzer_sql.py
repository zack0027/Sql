"""SQL and PL/SQL analyzer."""

from __future__ import annotations

from pathlib import Path

import pytest

from hana_engine.analyzers.sql import SqlAnalyzer
from hana_engine.analyzers.sqltext import blank_noise, cte_names, find_statements
from hana_engine.domain.analysis import AnalysisContext
from hana_engine.domain.types import EntityType, RelationType

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "sql"


def analyze(sql: str, path: str = "sql/prueba.sql"):
    context = AnalysisContext(
        project_id="P",
        file_id="F",
        relative_path=path,
        absolute_path=f"/tmp/{path}",
        extension=".sql",
        detected_type="sql",
        content=sql,
    )
    return SqlAnalyzer().analyze(context)


def names(result, entity_type: EntityType) -> set[str]:
    return {
        draft.normalized_name
        for draft in result.entities
        if draft.entity_type is entity_type
    }


def targets(result, relation: RelationType) -> set[str]:
    """Normalised names on the receiving end of a relation."""
    by_ref = {draft.ref: draft for draft in result.entities}
    return {
        by_ref[edge.target_ref].normalized_name
        for edge in result.relationships
        if edge.relation_type is relation and edge.target_ref in by_ref
    }


class TestTextPreparation:
    def test_line_comments_are_blanked_but_offsets_survive(self):
        sql = "select 1 -- from secretos\nfrom t"
        cleaned = blank_noise(sql)
        assert len(cleaned) == len(sql)
        assert "secretos" not in cleaned
        assert cleaned.endswith("from t")

    def test_block_comments_are_blanked(self):
        cleaned = blank_noise("select /* from oculta */ 1 from t")
        assert "oculta" not in cleaned
        assert "from t" in cleaned

    def test_string_literals_are_blanked(self):
        cleaned = blank_noise("update t set x = 'from otra_tabla' where y = 1")
        assert "otra_tabla" not in cleaned

    def test_escaped_quotes_do_not_swallow_the_rest(self):
        cleaned = blank_noise("select 'a''b' from uc_insp_ent")
        assert "uc_insp_ent" in cleaned

    def test_newlines_are_preserved_so_line_numbers_hold(self):
        sql = "-- uno\n-- dos\nselect * from t"
        assert blank_noise(sql).count("\n") == sql.count("\n")

    def test_cte_names_are_detected(self):
        sql = "with recientes as (select 1 from t), otra as (select 2 from u) select * from recientes"
        assert cte_names(blank_noise(sql)) == {"RECIENTES", "OTRA"}

    def test_subqueries_do_not_become_separate_statements(self):
        sql = "select * from a where id in (select id from b)"
        assert len(find_statements(blank_noise(sql))) == 1


class TestReadsAndWrites:
    def test_select_reads_its_table(self):
        result = analyze("select numctl from uc_insp_ent")
        assert "UC_INSP_ENT" in targets(result, RelationType.QUERY_READS_TABLE)
        assert not targets(result, RelationType.QUERY_WRITES_TABLE)

    def test_insert_writes_its_table(self):
        result = analyze("insert into uc_insp_ent (numctl) values (1)")
        assert "UC_INSP_ENT" in targets(result, RelationType.QUERY_WRITES_TABLE)

    def test_update_writes_its_table(self):
        result = analyze("update uc_insp_ent set estado = 'X' where numctl = 1")
        assert "UC_INSP_ENT" in targets(result, RelationType.QUERY_WRITES_TABLE)

    def test_delete_writes_its_table(self):
        result = analyze("delete from uc_insp_ent where numctl = 1")
        assert "UC_INSP_ENT" in targets(result, RelationType.QUERY_WRITES_TABLE)

    def test_merge_writes_its_target_and_reads_its_source(self):
        result = analyze(
            "merge into uc_insp_ent d using uc_insp_stg s on (d.numctl = s.numctl)"
            " when matched then update set d.estado = s.estado"
        )
        assert "UC_INSP_ENT" in targets(result, RelationType.QUERY_WRITES_TABLE)
        assert "UC_INSP_STG" in targets(result, RelationType.QUERY_READS_TABLE)

    def test_join_reads_every_table(self):
        result = analyze(
            "select e.numctl, p.prtdsc from uc_insp_ent e"
            " join prtmst p on p.prtnum = e.prtnum"
        )
        read = targets(result, RelationType.QUERY_READS_TABLE)
        assert {"UC_INSP_ENT", "PRTMST"} <= read

    def test_left_join_is_read_too(self):
        result = analyze(
            "select 1 from uc_insp_ent e left join uc_insp_det d on d.numctl = e.numctl"
        )
        assert "UC_INSP_DET" in targets(result, RelationType.QUERY_READS_TABLE)

    def test_subquery_tables_belong_to_the_enclosing_query(self):
        result = analyze(
            "select 1 from uc_insp_ent e"
            " where exists (select 1 from uc_insp_est s where s.numctl = e.numctl)"
        )
        assert "UC_INSP_EST" in targets(result, RelationType.QUERY_READS_TABLE)

    def test_a_cte_is_not_reported_as_a_table(self):
        """`WITH recientes AS (...)` looks like a table but is not an object."""
        result = analyze(
            "with recientes as (select numctl from uc_insp_ent)"
            " select * from recientes"
        )
        tables = names(result, EntityType.ORACLE_TABLE)
        assert "UC_INSP_ENT" in tables
        assert "RECIENTES" not in tables

    def test_a_table_named_only_in_a_comment_is_not_a_reference(self):
        result = analyze("-- toca uc_insp_ent\nselect 1 from prtmst")
        assert names(result, EntityType.ORACLE_TABLE) == {"PRTMST"}

    def test_schema_qualified_tables_keep_their_schema(self):
        result = analyze("select 1 from wms.uc_insp_ent")
        table = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.ORACLE_TABLE
        )
        assert table.schema == "wms"
        assert table.qualified_name == "wms.uc_insp_ent"

    def test_case_and_quoting_fold_to_one_entity(self):
        result = analyze('select 1 from "UC_INSP_ENT" union select 1 from uc_insp_ent')
        assert names(result, EntityType.ORACLE_TABLE) == {"UC_INSP_ENT"}


class TestColumns:
    def test_alias_qualified_columns_resolve_to_their_table(self):
        result = analyze("select e.numctl, e.netwgt from uc_insp_ent e")
        columns = names(result, EntityType.ORACLE_COLUMN)
        assert {"NUMCTL", "NETWGT"} <= columns

        column = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.ORACLE_COLUMN
            and draft.normalized_name == "NETWGT"
        )
        assert column.container == "UC_INSP_ENT"
        assert column.qualified_name == "UC_INSP_ENT.NETWGT"

    def test_columns_of_different_tables_stay_separate(self):
        result = analyze(
            "select e.netwgt, p.netwgt from uc_insp_ent e join prtmst p on 1=1"
        )
        containers = {
            draft.container
            for draft in result.entities
            if draft.entity_type is EntityType.ORACLE_COLUMN
        }
        assert containers == {"UC_INSP_ENT", "PRTMST"}

    def test_insert_column_list_belongs_to_the_target_table(self):
        result = analyze(
            "insert into uc_insp_ent (numctl, prtnum, netwgt) values (1, 2, 3)"
        )
        columns = names(result, EntityType.ORACLE_COLUMN)
        assert {"NUMCTL", "PRTNUM", "NETWGT"} <= columns

    def test_update_set_columns_belong_to_the_updated_table(self):
        result = analyze("update uc_insp_ent set estado = 'X', netwgt = 5 where id = 1")
        columns = names(result, EntityType.ORACLE_COLUMN)
        assert {"ESTADO", "NETWGT"} <= columns

    def test_unqualified_columns_are_not_attributed_to_a_guess(self):
        """Two tables, a bare column: no honest owner, so nothing is recorded."""
        result = analyze("select numctl from uc_insp_ent, prtmst")
        assert names(result, EntityType.ORACLE_COLUMN) == set()

    def test_qualifier_that_matches_no_table_is_ignored(self):
        result = analyze("select foo.bar from uc_insp_ent e")
        assert "BAR" not in names(result, EntityType.ORACLE_COLUMN)


class TestPlSql:
    def test_procedure_function_and_package_declarations(self):
        result = analyze(
            "create or replace package pkg_inspeccion as\n"
            "  procedure registrar_evento(p_id number);\n"
            "  function total_neto return number;\n"
            "end;",
            path="sql/pkg.pks",
        )
        assert "PKG_INSPECCION" in names(result, EntityType.ORACLE_PACKAGE)
        assert "REGISTRAR_EVENTO" in names(result, EntityType.ORACLE_PROCEDURE)
        assert "TOTAL_NETO" in names(result, EntityType.ORACLE_FUNCTION)

    def test_declarations_are_linked_to_their_file(self):
        result = analyze("procedure guardar is begin null; end;")
        assert any(
            edge.relation_type is RelationType.ENTITY_DEFINED_IN_FILE
            for edge in result.relationships
        )

    def test_qualified_calls_are_detected(self):
        result = analyze("begin pkg_inspeccion.registrar_evento(1); end;")
        assert "PKG_INSPECCION" in names(result, EntityType.ORACLE_PACKAGE)
        assert "REGISTRAR_EVENTO" in names(result, EntityType.ORACLE_PROCEDURE)

    def test_builtin_packages_are_not_recorded_as_user_code(self):
        result = analyze("begin dbms_output.put_line('hola'); end;")
        assert "DBMS_OUTPUT" not in names(result, EntityType.ORACLE_PACKAGE)


class TestRealFixtures:
    def test_guardar_inspeccion(self):
        sql = (FIXTURES / "guardar_inspeccion.sql").read_text(encoding="utf-8")
        result = analyze(sql, path="sql/guardar_inspeccion.sql")

        assert "UC_INSP_ENT" in targets(result, RelationType.QUERY_WRITES_TABLE)
        columns = names(result, EntityType.ORACLE_COLUMN)
        assert {"NUMCTL", "PRTNUM", "MUESTRA_SIZE_VER", "NETWGT"} <= columns
        assert "PKG_INSPECCION" in names(result, EntityType.ORACLE_PACKAGE)

    def test_consulta_inspecciones(self):
        sql = (FIXTURES / "consulta_inspecciones.sql").read_text(encoding="utf-8")
        result = analyze(sql, path="sql/consulta_inspecciones.sql")

        read = targets(result, RelationType.QUERY_READS_TABLE)
        assert {"UC_INSP_ENT", "PRTMST", "UC_INSP_DET", "UC_INSP_EST"} <= read
        assert "RECIENTES" not in names(result, EntityType.ORACLE_TABLE)
        assert not targets(result, RelationType.QUERY_WRITES_TABLE)


class TestProvenance:
    def test_every_draft_carries_a_span_and_a_snippet(self):
        result = analyze("select e.numctl from uc_insp_ent e")
        for draft in result.entities:
            assert draft.span is not None, draft.name
            assert draft.evidence_snippet, draft.name

    def test_line_numbers_point_at_the_right_line(self):
        result = analyze("-- cabecera\n-- otra\nselect 1 from uc_insp_ent")
        table = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.ORACLE_TABLE
        )
        assert table.span.start_line == 3

    def test_relationships_are_confirmed_by_direct_syntax(self):
        result = analyze("insert into uc_insp_ent (numctl) values (1)")
        for edge in result.relationships:
            assert edge.confidence == 1.0

    @pytest.mark.parametrize(
        "sql",
        [
            "",
            "   \n\n  ",
            "-- solo un comentario",
            "select",
            "insert into",
            "select * from",
            "'''",
            "/* sin cerrar",
        ],
    )
    def test_malformed_input_does_not_raise(self, sql):
        analyze(sql)
