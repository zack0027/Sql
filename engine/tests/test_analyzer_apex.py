"""Oracle APEX analyzer."""

from __future__ import annotations

from pathlib import Path

from hana_engine.analyzers.apex import ApexAnalyzer
from hana_engine.domain.analysis import AnalysisContext
from hana_engine.domain.confidence import STRONG_INFERENCE
from hana_engine.domain.types import EntityType, RelationType, VerificationStatus

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
    return ApexAnalyzer().analyze(context)


def names(result, entity_type: EntityType) -> set[str]:
    return {
        draft.normalized_name
        for draft in result.entities
        if draft.entity_type is entity_type
    }


def mappings(result) -> set[tuple[str, str]]:
    """(item, TABLE.COLUMN) pairs proved by the source."""
    by_ref = {draft.ref: draft for draft in result.entities}
    return {
        (
            by_ref[edge.source_ref].normalized_name,
            by_ref[edge.target_ref].qualified_name,
        )
        for edge in result.relationships
        if edge.relation_type is RelationType.APEX_ITEM_MAPS_TO_COLUMN
    }


class TestItems:
    def test_page_items_are_detected(self):
        result = analyze("select * from t where numctl = :P117_NUMCTL")
        assert "P117_NUMCTL" in names(result, EntityType.APEX_ITEM)

    def test_several_items_on_one_page(self):
        result = analyze(
            "select 1 from t where a = :P117_NUMCTL and b = :P117_PRTNUM"
        )
        assert names(result, EntityType.APEX_ITEM) == {"P117_NUMCTL", "P117_PRTNUM"}
        assert names(result, EntityType.APEX_PAGE) == {"117"}

    def test_items_from_different_pages(self):
        result = analyze("select 1 from t where a = :P117_X and b = :P42_Y")
        assert names(result, EntityType.APEX_PAGE) == {"117", "42"}

    def test_application_items_are_not_page_items(self):
        result = analyze("select 1 from t where usuario = :APP_USER and app = :APP_ID")
        assert names(result, EntityType.APEX_ITEM) == set()
        assert names(result, EntityType.APEX_PAGE) == set()

    def test_plsql_assignment_is_not_a_bind_variable(self):
        """`l_x := 1` must not be read as a bind named `=`."""
        result = analyze("begin l_numctl := 1; end;")
        assert names(result, EntityType.APEX_ITEM) == set()

    def test_a_bind_that_is_not_an_apex_item_is_ignored(self):
        result = analyze("select 1 from t where id = :p_parametro")
        assert names(result, EntityType.APEX_ITEM) == set()

    def test_items_inside_comments_are_ignored(self):
        result = analyze("-- usa :P117_NUMCTL\nselect 1 from t")
        assert names(result, EntityType.APEX_ITEM) == set()

    def test_items_inside_string_literals_are_ignored(self):
        result = analyze("select 'texto :P117_NUMCTL' from dual")
        assert names(result, EntityType.APEX_ITEM) == set()

    def test_case_is_folded(self):
        result = analyze("select 1 from t where a = :p117_numctl and b = :P117_NUMCTL")
        assert names(result, EntityType.APEX_ITEM) == {"P117_NUMCTL"}


class TestPageInference:
    def test_the_page_is_inferred_not_confirmed(self):
        """The convention is strong, but a convention is not syntax."""
        result = analyze("select 1 from t where a = :P117_NUMCTL")
        page = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.APEX_PAGE
        )
        assert page.verification_status is VerificationStatus.INFERRED
        assert page.confidence == STRONG_INFERENCE

    def test_the_containment_edge_is_inferred_too(self):
        result = analyze("select 1 from t where a = :P117_NUMCTL")
        edge = next(
            edge
            for edge in result.relationships
            if edge.relation_type is RelationType.APEX_PAGE_CONTAINS_ITEM
        )
        assert edge.status is VerificationStatus.INFERRED
        assert edge.confidence == STRONG_INFERENCE

    def test_the_item_itself_is_confirmed(self):
        """The item's existence *is* direct syntax; only its page is inferred."""
        result = analyze("select 1 from t where a = :P117_NUMCTL")
        item = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.APEX_ITEM
        )
        assert item.verification_status is VerificationStatus.CONFIRMED
        assert item.confidence == 1.0

    def test_the_reason_for_the_inference_is_recorded(self):
        result = analyze("select 1 from t where a = :P117_NUMCTL")
        page = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.APEX_PAGE
        )
        assert "inferred_from" in page.metadata


class TestColumnMappings:
    def test_insert_pairs_columns_with_items_positionally(self):
        result = analyze(
            "insert into uc_insp_ent (numctl, muestra_size_ver)"
            " values (:P117_NUMCTL, :P117_MUESTRA_SIZE_VER)"
        )
        assert mappings(result) == {
            ("P117_NUMCTL", "UC_INSP_ENT.NUMCTL"),
            ("P117_MUESTRA_SIZE_VER", "UC_INSP_ENT.MUESTRA_SIZE_VER"),
        }

    def test_mapping_is_confirmed_because_the_statement_pairs_them(self):
        result = analyze(
            "insert into uc_insp_ent (numctl) values (:P117_NUMCTL)"
        )
        edge = next(
            edge
            for edge in result.relationships
            if edge.relation_type is RelationType.APEX_ITEM_MAPS_TO_COLUMN
        )
        assert edge.confidence == 1.0
        assert edge.status is VerificationStatus.CONFIRMED

    def test_non_item_values_are_skipped_without_shifting_the_pairing(self):
        result = analyze(
            "insert into uc_insp_ent (numctl, usuario, netwgt)"
            " values (:P117_NUMCTL, l_usuario, :P117_NETWGT)"
        )
        assert mappings(result) == {
            ("P117_NUMCTL", "UC_INSP_ENT.NUMCTL"),
            ("P117_NETWGT", "UC_INSP_ENT.NETWGT"),
        }

    def test_mismatched_list_lengths_produce_nothing(self):
        """Positional pairing is only sound when the lists line up."""
        result = analyze(
            "insert into uc_insp_ent (a, b, c) values (:P117_X, :P117_Y)"
        )
        assert mappings(result) == set()

    def test_update_assignments_map_too(self):
        result = analyze(
            "update uc_insp_ent set muestra_size_ver = :P117_MUESTRA_SIZE_VER"
            " where numctl = :P117_NUMCTL"
        )
        assert (
            "P117_MUESTRA_SIZE_VER",
            "UC_INSP_ENT.MUESTRA_SIZE_VER",
        ) in mappings(result)

    def test_a_where_clause_alone_does_not_prove_a_mapping(self):
        """Filtering by an item says nothing about which column it feeds."""
        result = analyze("select 1 from uc_insp_ent where numctl = :P117_NUMCTL")
        assert mappings(result) == set()


class TestRealFixture:
    def test_guardar_inspeccion_reproduces_the_specification_example(self):
        sql = (FIXTURES / "guardar_inspeccion.sql").read_text(encoding="utf-8")
        result = analyze(sql, path="sql/guardar_inspeccion.sql")

        assert {"P117_PRTNUM", "P117_MUESTRA_SIZE_VER", "P117_NETWGT"} <= names(
            result, EntityType.APEX_ITEM
        )
        assert names(result, EntityType.APEX_PAGE) == {"117"}
        assert (
            "P117_MUESTRA_SIZE_VER",
            "UC_INSP_ENT.MUESTRA_SIZE_VER",
        ) in mappings(result)

    def test_app_user_is_not_turned_into_a_page_item(self):
        sql = (FIXTURES / "guardar_inspeccion.sql").read_text(encoding="utf-8")
        result = analyze(sql, path="sql/guardar_inspeccion.sql")
        assert "APP_USER" not in names(result, EntityType.APEX_ITEM)


class TestRobustness:
    def test_every_draft_carries_provenance(self):
        result = analyze("insert into t (a) values (:P117_A)")
        for draft in result.entities:
            assert draft.span is not None
            assert draft.evidence_snippet

    def test_malformed_input_does_not_raise(self):
        for sql in ["", ":", "::", ":P117_", "insert into t () values ()", "update"]:
            analyze(sql)
