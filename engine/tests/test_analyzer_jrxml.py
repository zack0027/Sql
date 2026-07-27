"""JasperReports (JRXML) analyzer."""

from __future__ import annotations

from pathlib import Path

from hana_engine.analyzers.jrxml import JrxmlAnalyzer
from hana_engine.domain.analysis import AnalysisContext
from hana_engine.domain.types import EntityType, RelationType, Severity

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "jrxml"
    / "Usr-RptInspeccion.jrxml"
)

MINIMAL = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport name="Rpt">
  <parameter name="P_NUMCTL" class="java.lang.String"/>
  <field name="numctl" class="java.lang.String"/>
  <detail><band>
    <textField><textFieldExpression><![CDATA[$F{numctl}]]></textFieldExpression></textField>
    <textField><textFieldExpression><![CDATA[$P{P_NUMCTL}]]></textFieldExpression></textField>
  </band></detail>
</jasperReport>
"""


def analyze(xml: str, path: str = "reports/Rpt.jrxml"):
    context = AnalysisContext(
        project_id="P",
        file_id="F",
        relative_path=path,
        absolute_path=f"/tmp/{path}",
        extension=".jrxml",
        detected_type="jrxml",
        content=xml,
    )
    return JrxmlAnalyzer().analyze(context)


def names(result, entity_type: EntityType) -> set[str]:
    return {
        draft.normalized_name
        for draft in result.entities
        if draft.entity_type is entity_type
    }


def codes(messages) -> set[str]:
    return {message.code for message in messages}


class TestStructure:
    def test_the_report_takes_its_declared_name(self):
        result = analyze(MINIMAL)
        assert names(result, EntityType.JASPER_REPORT) == {"Rpt"}

    def test_a_report_without_a_name_falls_back_to_the_filename(self):
        result = analyze("<jasperReport/>", path="reports/Usr-RptInspeccion.jrxml")
        assert names(result, EntityType.JASPER_REPORT) == {"Usr-RptInspeccion"}

    def test_fields_parameters_and_variables_are_declared(self):
        result = analyze(FIXTURE.read_text(encoding="utf-8"))
        assert {"numctl", "prtnum", "netwgt", "muestra_size_ver"} <= names(
            result, EntityType.JASPER_FIELD
        )
        assert {"P_NUMCTL", "P_PRTNUM", "P_UNUSED_FLAG"} <= names(
            result, EntityType.JASPER_PARAMETER
        )
        assert "V_TOTAL_NETWGT" in names(result, EntityType.JASPER_VARIABLE)

    def test_names_are_case_sensitive(self):
        """Jasper field names are case sensitive; folding them would merge two."""
        result = analyze(
            '<jasperReport name="R"><field name="netwgt"/><field name="NETWGT"/></jasperReport>'
        )
        assert names(result, EntityType.JASPER_FIELD) == {"netwgt", "NETWGT"}

    def test_the_report_is_linked_to_its_parts(self):
        result = analyze(MINIMAL)
        relations = {edge.relation_type for edge in result.relationships}
        assert RelationType.REPORT_USES_FIELD in relations
        assert RelationType.REPORT_USES_PARAMETER in relations

    def test_namespaced_documents_are_understood(self):
        xml = (
            '<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"'
            ' name="R"><field name="numctl"/></jasperReport>'
        )
        assert names(analyze(xml), EntityType.JASPER_FIELD) == {"numctl"}


class TestInconsistencies:
    def test_a_field_used_but_not_declared_is_reported(self):
        result = analyze(FIXTURE.read_text(encoding="utf-8"))
        assert "undeclared_field" in codes(result.warnings)
        message = next(
            w for w in result.warnings if w.code == "undeclared_field"
        )
        assert message.detail["field"] == "campo_no_declarado"

    def test_a_parameter_declared_but_not_used_is_reported(self):
        result = analyze(FIXTURE.read_text(encoding="utf-8"))
        assert "unused_parameter" in codes(result.warnings)
        unused = {
            w.detail["parameter"]
            for w in result.warnings
            if w.code == "unused_parameter"
        }
        assert "P_UNUSED_FLAG" in unused
        assert "P_NUMCTL" not in unused  # it is used by the query

    def test_a_consistent_report_produces_no_warnings(self):
        assert analyze(MINIMAL).warnings == []

    def test_platform_parameters_are_not_reported_as_dead(self):
        """Blue Yonder injects MOCA_REPORT_* at run time; the author cannot act.

        A real report declares a dozen of them. Flagging every one buries the
        single genuine finding under noise, which is how a warning list stops
        being read at all.
        """
        xml = (
            '<jasperReport name="R">'
            '<parameter name="MOCA_REPORT_CONNECTION" class="java.lang.Object">'
            '<property name="MOCA" value="true"/></parameter>'
            '<parameter name="SUBREPORT_DIR" class="java.lang.String"/>'
            '<parameter name="P_OLVIDADO" class="java.lang.String"/>'
            "</jasperReport>"
        )
        unused = {
            w.detail["parameter"]
            for w in analyze(xml).warnings
            if w.code == "unused_parameter"
        }
        assert unused == {"P_OLVIDADO"}

    def test_a_parameter_carrying_a_property_is_platform_managed(self):
        xml = (
            '<jasperReport name="R">'
            '<parameter name="CUALQUIERA" class="java.lang.String">'
            '<property name="MOCA" value="true"/></parameter>'
            "</jasperReport>"
        )
        assert "unused_parameter" not in codes(analyze(xml).warnings)

    def test_warnings_are_warnings_not_errors(self):
        result = analyze(FIXTURE.read_text(encoding="utf-8"))
        assert all(w.severity is Severity.WARNING for w in result.warnings)
        assert result.errors == []


class TestQuery:
    def test_tables_in_the_query_become_relations(self):
        result = analyze(FIXTURE.read_text(encoding="utf-8"))
        by_ref = {draft.ref: draft for draft in result.entities}
        queried = {
            by_ref[edge.target_ref].normalized_name
            for edge in result.relationships
            if edge.relation_type is RelationType.REPORT_QUERIES_TABLE
        }
        assert {"UC_INSP_ENT", "PRTMST"} <= queried

    def test_a_report_without_a_query_produces_no_table_relations(self):
        result = analyze(MINIMAL)
        assert not any(
            edge.relation_type is RelationType.REPORT_QUERIES_TABLE
            for edge in result.relationships
        )


class TestImagesAndSubreports:
    def test_a_relative_image_path_is_recorded(self):
        result = analyze(FIXTURE.read_text(encoding="utf-8"))
        images = {
            draft.name
            for draft in result.entities
            if draft.entity_type is EntityType.FILE
        }
        assert "images/checkboxOn.png" in images

    def test_relative_images_are_marked_as_such(self):
        result = analyze(FIXTURE.read_text(encoding="utf-8"))
        image = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.FILE
        )
        assert image.metadata["relative"] is True

    def test_an_absolute_image_path_is_not_marked_relative(self):
        xml = (
            '<jasperReport name="R"><image><imageExpression>'
            '<![CDATA["C:/imagenes/logo.png"]]></imageExpression></image></jasperReport>'
        )
        image = next(
            draft
            for draft in analyze(xml).entities
            if draft.entity_type is EntityType.FILE
        )
        assert image.metadata["relative"] is False

    def test_a_conditional_expression_yields_only_the_image_paths(self):
        """Taken from a real report: the compared value is not a file.

        `$F{insptyp}=="Entrada"? "./on.png": "./off.png"` used to register
        "Entrada" as an image, polluting the graph with things that do not exist.
        """
        xml = (
            '<jasperReport name="R"><image><imageExpression><![CDATA['
            '$F{insptyp}=="Entrada"? "./checkboxOn.png": "./checkboxOff.png"'
            "]]></imageExpression></image></jasperReport>"
        )
        images = {
            draft.name
            for draft in analyze(xml).entities
            if draft.entity_type is EntityType.FILE
        }
        assert images == {"./checkboxOn.png", "./checkboxOff.png"}

    def test_subreports_are_recorded(self):
        result = analyze(FIXTURE.read_text(encoding="utf-8"))
        assert "Usr-RptInspeccionDetalle" in names(
            result, EntityType.JASPER_SUBREPORT
        )
        assert any(
            edge.relation_type is RelationType.REPORT_INCLUDES_SUBREPORT
            for edge in result.relationships
        )

    def test_a_computed_subreport_path_is_flagged_not_guessed(self):
        xml = (
            '<jasperReport name="R"><subreport><subreportExpression>'
            "<![CDATA[$P{RUTA} + $F{nombre}]]></subreportExpression></subreport></jasperReport>"
        )
        result = analyze(xml)
        assert "dynamic_subreport" in codes(result.warnings)
        assert names(result, EntityType.JASPER_SUBREPORT) == set()


class TestSafety:
    def test_expressions_are_matched_never_evaluated(self):
        """A Java expression is text to HANA, nothing more."""
        xml = (
            '<jasperReport name="R"><detail><band><textField>'
            "<textFieldExpression><![CDATA[Runtime.getRuntime().exec(\"calc\")]]>"
            "</textFieldExpression></textField></band></detail></jasperReport>"
        )
        result = analyze(xml)
        assert result.errors == []

    def test_a_document_with_a_dtd_is_refused(self):
        """Internal entity expansion is a denial of service, so DTDs are declined."""
        xml = (
            '<?xml version="1.0"?>'
            "<!DOCTYPE lolz [<!ENTITY lol \"lol\">]>"
            '<jasperReport name="R"/>'
        )
        result = analyze(xml)
        assert "dtd_rejected" in codes(result.errors)
        assert result.entities == []

    def test_malformed_xml_is_an_error_not_a_crash(self):
        result = analyze("<jasperReport name='R'><field></jasperReport>")
        assert "malformed_xml" in codes(result.errors)

    def test_an_empty_document_does_not_raise(self):
        assert "malformed_xml" in codes(analyze("").errors)


class TestProvenance:
    def test_declarations_point_at_their_line(self):
        result = analyze(FIXTURE.read_text(encoding="utf-8"))
        field = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.JASPER_FIELD
            and draft.normalized_name == "netwgt"
        )
        line = FIXTURE.read_text(encoding="utf-8").splitlines()[
            field.span.start_line - 1
        ]
        assert 'name="netwgt"' in line

    def test_fields_are_scoped_to_their_report(self):
        """Two reports with a `netwgt` field are two entities, not one."""
        result = analyze(MINIMAL)
        field = next(
            draft
            for draft in result.entities
            if draft.entity_type is EntityType.JASPER_FIELD
        )
        assert field.container == "Rpt"
