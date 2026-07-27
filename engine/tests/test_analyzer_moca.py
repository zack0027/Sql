"""MOCA, JSON and source-code analyzers."""

from __future__ import annotations

from pathlib import Path

from hana_engine.analyzers.moca import MocaAnalyzer
from hana_engine.analyzers.structured import CodeAnalyzer, JsonAnalyzer
from hana_engine.domain.analysis import AnalysisContext
from hana_engine.domain.types import EntityType, RelationType, VerificationStatus

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def context_for(content: str, path: str, extension: str, detected: str):
    return AnalysisContext(
        project_id="P",
        file_id="F",
        relative_path=path,
        absolute_path=f"/tmp/{path}",
        extension=extension,
        detected_type=detected,
        content=content,
    )


def names(result, entity_type: EntityType) -> set[str]:
    return {
        draft.normalized_name
        for draft in result.entities
        if draft.entity_type is entity_type
    }


# ---------------------------------------------------------------------------
class TestMoca:
    def analyze(self, text: str, path: str = "moca/cmd.mcmd"):
        return MocaAnalyzer().analyze(context_for(text, path, ".mcmd", "moca"))

    def test_pipeline_segments_become_commands(self):
        result = self.analyze("publish data where a = 1 | [select 1 from t]")
        assert len(names(result, EntityType.MOCA_COMMAND)) == 2

    def test_a_pipe_inside_brackets_does_not_split(self):
        """`|` within a bracketed block belongs to that block, not the pipeline."""
        result = self.analyze("[select a || b from t] | publish data where x = 1")
        assert len(names(result, EntityType.MOCA_COMMAND)) == 2

    def test_variables_are_detected(self):
        result = self.analyze("[select 1 from t where numctl = @numctl]")
        assert "NUMCTL" in names(result, EntityType.MOCA_VARIABLE)

    def test_commands_are_linked_to_the_variables_they_use(self):
        result = self.analyze("[select 1 from t where numctl = @numctl]")
        assert any(
            edge.relation_type is RelationType.MOCA_COMMAND_USES_VARIABLE
            for edge in result.relationships
        )

    def test_catch_marker_is_not_read_as_a_variable(self):
        """`@?` is the error-status marker. `errmsg` beside it is a real variable."""
        result = self.analyze("catch(@?) [ publish data where errmsg = 'x' ]")
        variables = names(result, EntityType.MOCA_VARIABLE)
        assert "?" not in variables
        assert variables == {"ERRMSG"}

    def test_catch_is_recorded_on_the_command(self):
        result = self.analyze("catch(@?) [ publish data where a = 1 ]")
        command = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.MOCA_COMMAND
        )
        assert command.metadata.get("handles_errors") is True

    def test_published_variables_are_recorded(self):
        result = self.analyze("publish data where numctl = @numctl")
        command = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.MOCA_COMMAND
        )
        assert command.metadata.get("publishes") is True

    def test_embedded_sql_yields_table_relations(self):
        result = self.analyze("[select numctl from uc_insp_ent where numctl = @numctl]")
        assert "UC_INSP_ENT" in names(result, EntityType.ORACLE_TABLE)
        assert any(
            edge.relation_type is RelationType.QUERY_READS_TABLE
            for edge in result.relationships
        )

    def test_embedded_update_is_a_write(self):
        result = self.analyze("[update uc_insp_ent set estado = 'C' where numctl = 1]")
        assert any(
            edge.relation_type is RelationType.QUERY_WRITES_TABLE
            for edge in result.relationships
        )

    def test_variable_flow_is_marked_inferred(self):
        """MOCA resolves names on a stack at run time; matching by name is a guess."""
        result = self.analyze(
            "publish data where numctl = @numctl | [update t set x = 1 where n = @numctl]"
        )
        flow = [
            edge
            for edge in result.relationships
            if edge.relation_type is RelationType.ENTITY_DEPENDS_ON_ENTITY
        ]
        assert flow
        assert all(edge.status is VerificationStatus.INFERRED for edge in flow)

    def test_real_fixture(self):
        text = (FIXTURES / "moca" / "confirmar_inspeccion.mcmd").read_text(
            encoding="utf-8"
        )
        result = self.analyze(text, path="moca/confirmar_inspeccion.mcmd")
        assert {"NUMCTL", "PRTNUM", "NETWGT"} <= names(
            result, EntityType.MOCA_VARIABLE
        )
        assert "UC_INSP_ENT" in names(result, EntityType.ORACLE_TABLE)

    def test_a_txt_holding_a_pipeline_is_accepted(self):
        analyzer = MocaAnalyzer()
        assert analyzer.can_analyze("notas.txt", "publish data | @x")
        assert not analyzer.can_analyze("notas.txt", "correo: alguien@ejemplo.com")

    def test_malformed_input_does_not_raise(self):
        for text in ["", "|", "[", "@", "catch(", "publish data where"]:
            self.analyze(text)


# ---------------------------------------------------------------------------
class TestJson:
    def analyze(self, text: str, path: str = "config/a.json"):
        return JsonAnalyzer().analyze(context_for(text, path, ".json", "json"))

    def test_properties_are_recorded_with_their_path(self):
        result = self.analyze('{"application": {"id": 117}}')
        properties = names(result, EntityType.JSON_PROPERTY)
        assert "application" in properties
        assert "application.id" in properties

    def test_arrays_record_one_representative_item(self):
        result = self.analyze('{"pages": [{"id": 1}, {"id": 2}, {"id": 3}]}')
        assert "pages[].id" in names(result, EntityType.JSON_PROPERTY)

    def test_apex_item_values_are_linked(self):
        result = self.analyze('{"name": "P117_NUMCTL"}')
        assert "P117_NUMCTL" in names(result, EntityType.APEX_ITEM)

    def test_table_column_values_are_linked(self):
        result = self.analyze('{"source": "UC_INSP_ENT.NUMCTL"}')
        column = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.ORACLE_COLUMN
        )
        assert column.qualified_name == "UC_INSP_ENT.NUMCTL"

    def test_those_links_are_inferred_not_confirmed(self):
        result = self.analyze('{"source": "UC_INSP_ENT.NUMCTL"}')
        edge = next(
            edge
            for edge in result.relationships
            if edge.relation_type is RelationType.ENTITY_MENTIONS_ENTITY
        )
        assert edge.status is VerificationStatus.INFERRED

    def test_an_ordinary_sentence_is_not_mistaken_for_a_column(self):
        result = self.analyze('{"nota": "Revisar el peso neto."}')
        assert names(result, EntityType.ORACLE_COLUMN) == set()

    def test_malformed_json_is_an_error_not_a_crash(self):
        result = self.analyze('{"a": }')
        assert {message.code for message in result.errors} == {"malformed_json"}

    def test_real_fixture(self):
        text = (FIXTURES / "json" / "apex_inspeccion.json").read_text(encoding="utf-8")
        result = self.analyze(text, path="config/apex_inspeccion.json")
        assert {"P117_NUMCTL", "P117_MUESTRA_SIZE_VER"} <= names(
            result, EntityType.APEX_ITEM
        )


# ---------------------------------------------------------------------------
class TestCode:
    def analyze_py(self, text: str):
        return CodeAnalyzer().analyze(
            context_for(text, "scripts/a.py", ".py", "python")
        )

    def analyze_js(self, text: str):
        return CodeAnalyzer().analyze(context_for(text, "web/a.js", ".js", "javascript"))

    def test_python_functions_and_classes(self):
        result = self.analyze_py("def guardar():\n    pass\n\nclass Inspeccion:\n    pass\n")
        assert {"guardar", "Inspeccion"} <= names(result, EntityType.PYTHON_FUNCTION)

    def test_python_declarations_are_confirmed_because_a_parser_found_them(self):
        result = self.analyze_py("def guardar():\n    pass\n")
        function = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.PYTHON_FUNCTION
        )
        assert function.confidence == 1.0

    def test_python_imports_become_dependencies(self):
        result = self.analyze_py("import os\nfrom pathlib import Path\n")
        assert any(
            edge.relation_type is RelationType.ENTITY_DEPENDS_ON_ENTITY
            for edge in result.relationships
        )

    def test_broken_python_is_an_error_not_a_crash(self):
        result = self.analyze_py("def (:\n")
        assert {message.code for message in result.errors} == {"python_syntax_error"}

    def test_python_is_parsed_never_executed(self):
        """Parsing builds a tree; the module's side effects never happen."""
        marker = Path("/tmp/hana-should-not-exist.txt")
        result = self.analyze_py(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\n"
        )
        assert result.errors == []
        assert not marker.exists()

    def test_javascript_functions_classes_and_arrows(self):
        result = self.analyze_js(
            "function cargar() {}\nclass Panel {}\nconst enviar = (a) => a;\n"
        )
        assert {"cargar", "Panel", "enviar"} <= names(
            result, EntityType.JAVASCRIPT_FUNCTION
        )

    def test_javascript_findings_are_inferred_not_confirmed(self):
        """No JS parser in the standard library, so the confidence says so."""
        result = self.analyze_js("function cargar() {}")
        function = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.JAVASCRIPT_FUNCTION
        )
        assert function.confidence < 1.0
        assert function.verification_status is VerificationStatus.INFERRED

    def test_javascript_names_keep_their_case(self):
        result = self.analyze_js("function getRows() {}")
        assert "getRows" in names(result, EntityType.JAVASCRIPT_FUNCTION)

    def test_apex_items_referenced_from_javascript(self):
        result = self.analyze_js("apex.item('P117_NUMCTL').setValue(1);")
        assert "P117_NUMCTL" in names(result, EntityType.APEX_ITEM)

    def test_javascript_imports(self):
        result = self.analyze_js("import x from './util.js';\nconst y = require('fs');")
        modules = {draft.name for draft in result.entities}
        assert "./util.js" in modules
        assert "fs" in modules

    def test_empty_sources_do_not_raise(self):
        assert self.analyze_py("").entities == []
        assert self.analyze_js("").entities == []
