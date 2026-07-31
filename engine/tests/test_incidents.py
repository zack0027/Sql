"""Errors read from logs, and what people did about them.

The idea the original specification called the reason for the name "knowledge
engine": HANA can find the failures, but only a person knows what fixed them,
and the value is entirely in the two halves meeting on the tenth recurrence
two years later.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hana_engine.analyzers.logs import LogAnalyzer
from hana_engine.domain.analysis import AnalysisContext
from hana_engine.domain.types import EntityType, RelationType
from hana_engine.engine import KnowledgeEngine, build_default_registry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def analyze(text: str, path: str = "logs/prueba.log"):
    context = AnalysisContext(
        project_id="P",
        file_id="F",
        relative_path=path,
        absolute_path=f"/tmp/{path}",
        extension=".log",
        detected_type="log",
        content=text,
    )
    return LogAnalyzer().analyze(context)


def errors(result) -> list:
    return [d for d in result.entities if d.entity_type is EntityType.ERROR]


class TestReadingALog:
    def test_it_finds_an_oracle_error(self):
        result = analyze("ORA-00942: table or view does not exist")
        assert [d.name for d in errors(result)] == ["ORA-00942"]

    def test_the_message_is_kept(self):
        result = analyze("ORA-00942: table or view does not exist")
        assert errors(result)[0].description == "table or view does not exist"

    def test_it_finds_other_oracle_families(self):
        result = analyze(
            "PLS-00201: identifier 'PKG_X' must be declared\n"
            "TNS-12541: TNS:no listener"
        )
        assert {d.name for d in errors(result)} == {"PLS-00201", "TNS-12541"}

    def test_ordinary_prose_is_not_an_error(self):
        result = analyze("Todo fue bien. El proceso termino a las 03:15.")
        assert errors(result) == []

    def test_a_line_number_points_at_the_line(self):
        result = analyze("hola\nque tal\nORA-00942: table or view does not exist")
        assert errors(result)[0].span.start_line == 3

    def test_it_recognises_a_log_whatever_it_is_called(self):
        """Real logs are named `salida.txt` or nothing at all."""
        analyzer = LogAnalyzer()
        assert analyzer.can_analyze("salida.txt", "ORA-00942: no existe")
        assert not analyzer.can_analyze("notas.txt", "una nota cualquiera")


class TestWhatTheErrorNames:
    def test_a_quoted_column_is_linked(self):
        result = analyze(
            'ORA-01400: cannot insert NULL into ("WMS"."UC_INSP_ENT"."NUMCTL")'
        )
        targets = {
            (d.entity_type, d.normalized_name)
            for d in result.entities
            if d.entity_type is not EntityType.ERROR
        }
        assert (EntityType.ORACLE_TABLE, "UC_INSP_ENT") in targets
        assert (EntityType.ORACLE_COLUMN, "NUMCTL") in targets

    def test_named_objects_are_only_mentions(self):
        """A log proves Oracle knows the object; not that the code declares it."""
        result = analyze(
            'ORA-01400: cannot insert NULL into ("WMS"."UC_INSP_ENT"."NUMCTL")'
        )
        for draft in result.entities:
            if draft.entity_type is EntityType.ORACLE_TABLE:
                assert draft.confidence < 1.0

    def test_a_plsql_stack_frame_names_the_routine(self):
        result = analyze(
            'ORA-01400: cannot insert NULL into ("WMS"."T"."C")\n'
            'ORA-06512: at "WMS.PKG_INSPECCION", line 42'
        )
        packages = [
            d for d in result.entities if d.entity_type is EntityType.ORACLE_PACKAGE
        ]
        assert [d.normalized_name for d in packages] == ["PKG_INSPECCION"]

    def test_a_stack_frame_is_not_a_separate_problem(self):
        """ORA-06512 is the traceback, not the failure; it would bury the real one."""
        result = analyze(
            'ORA-01400: cannot insert NULL into ("WMS"."T"."C")\n'
            'ORA-06512: at "WMS.PKG_X", line 42\n'
            "ORA-06512: at line 1"
        )
        assert [d.name for d in errors(result)] == ["ORA-01400"]

    def test_the_stack_attaches_to_the_error_above_it(self):
        result = analyze(
            'ORA-01400: cannot insert NULL into ("WMS"."T"."C")\n'
            'ORA-06512: at "WMS.PKG_X", line 42'
        )
        by_ref = {d.ref: d for d in result.entities}
        links = [
            (by_ref[e.source_ref].name, by_ref[e.target_ref].normalized_name)
            for e in result.relationships
            if e.relation_type is RelationType.ERROR_AFFECTS_ENTITY
        ]
        assert ("ORA-01400", "PKG_X") in links

    def test_an_error_naming_nothing_links_to_nothing(self):
        result = analyze("ORA-00942: table or view does not exist")
        assert [
            e
            for e in result.relationships
            if e.relation_type is RelationType.ERROR_AFFECTS_ENTITY
        ] == []


class TestRecurrence:
    def test_the_same_failure_twice_is_one_entity(self):
        """Identity is the code plus the object, so recurrence is free."""
        line = 'ORA-01400: cannot insert NULL into ("WMS"."T"."C")'
        result = analyze(f"{line}\nalgo pasa\n{line}")
        assert len({d.ref for d in errors(result)}) == 1
        assert len(errors(result)) == 2  # two sightings of one thing

    def test_the_same_code_on_different_objects_stays_apart(self):
        result = analyze(
            'ORA-01400: cannot insert NULL into ("WMS"."T"."C")\n'
            'ORA-01400: cannot insert NULL into ("WMS"."OTRA"."X")'
        )
        assert len({d.ref for d in errors(result)}) == 2


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "inspeccion"
    (root / "sql").mkdir(parents=True)
    (root / "logs").mkdir()
    shutil.copy(FIXTURES / "sql" / "guardar_inspeccion.sql", root / "sql")
    shutil.copy(FIXTURES / "sql" / "consulta_inspecciones.sql", root / "sql")
    shutil.copy(FIXTURES / "logs" / "inspeccion.log", root / "logs")
    return root


@pytest.fixture
def engine(db_path: Path, project_dir: Path):
    instance = KnowledgeEngine(db_path, registry=build_default_registry())
    project = instance.open_project(project_dir)
    instance.analyze_project(project.id)
    instance.project_id = project.id
    yield instance
    instance.close()


def incident(engine, code: str) -> dict:
    for item in engine.incidents(engine.project_id):
        if item["name"] == code:
            return item
    raise AssertionError(f"no se encontró {code}")


class TestThroughThePipeline:
    def test_recurrence_is_counted_across_the_log(self, engine):
        """Two sightings of ORA-01400, one in each night's run."""
        assert incident(engine, "ORA-01400")["times_seen"] == 2
        assert incident(engine, "ORA-12899")["times_seen"] == 1

    def test_the_most_repeated_comes_first(self, engine):
        found = engine.incidents(engine.project_id)
        assert found[0]["name"] == "ORA-01400"

    def test_it_reaches_the_code_through_a_declared_inference(self, engine):
        """The log says `WMS.UC_INSP_ENT`; the scripts never declare a schema.

        Merging them is forbidden — unknown must not match known — so the
        correspondence is reported as an inference instead, with the file and
        line of the code it probably means.
        """
        affected = incident(engine, "ORA-01400")["affects"]
        table = next(
            item for item in affected if item["entity_type"] == "OracleTable"
        )
        same = table["probably_same_as"]
        assert same, "el error no llegó al código"
        assert same[0]["normalized_name"] == "UC_INSP_ENT"
        assert same[0]["verification_status"] == "inferred"
        assert same[0]["confidence"] < 1.0
        assert same[0]["file_path"].endswith(".sql")

    def test_the_two_entities_are_never_merged(self, engine):
        """The invariant this had to work around, checked directly."""
        keys = {
            row["identity_key"]
            for row in engine.connection.execute(
                "SELECT identity_key FROM entities"
                " WHERE project_id = ? AND entity_type = ? AND normalized_name = ?",
                (engine.project_id, "OracleTable", "UC_INSP_ENT"),
            )
        }
        assert "OracleTable|WMS||UC_INSP_ENT" in keys
        assert "OracleTable|||UC_INSP_ENT" in keys

    def test_an_unqualified_entity_does_not_guess_a_schema(self, engine):
        """The bridge is one-directional; the other way would be a guess."""
        affected = incident(engine, "ORA-01400")["affects"]
        for item in affected:
            for same in item["probably_same_as"]:
                assert same["normalized_name"] == item["normalized_name"]


class TestSolutions:
    def test_writing_down_what_fixed_it(self, engine):
        target = incident(engine, "ORA-01400")
        engine.record_solution(
            engine.project_id, target["id"], "Faltaba la secuencia en PROD."
        )
        assert incident(engine, "ORA-01400")["solutions"][0]["description"] == (
            "Faltaba la secuencia en PROD."
        )

    def test_a_remedy_that_failed_is_kept(self, engine):
        """It saves the next person the same dead end."""
        target = incident(engine, "ORA-01400")
        engine.record_solution(
            engine.project_id, target["id"], "Reiniciar el listener.", worked=False
        )
        stored = incident(engine, "ORA-01400")["solutions"][0]
        assert stored["worked"] is False

    def test_the_ones_that_worked_come_first(self, engine):
        target = incident(engine, "ORA-01400")
        engine.record_solution(
            engine.project_id, target["id"], "Reiniciar el listener.", worked=False
        )
        engine.record_solution(
            engine.project_id, target["id"], "Crear la secuencia.", worked=True
        )
        assert incident(engine, "ORA-01400")["solutions"][0]["worked"] is True

    def test_an_empty_solution_is_refused(self, engine):
        target = incident(engine, "ORA-01400")
        with pytest.raises(ValueError):
            engine.record_solution(engine.project_id, target["id"], "   ")

    def test_only_errors_can_be_solved(self, engine):
        table = engine.queries.resolve(
            engine.project_id, "UC_INSP_ENT", entity_type=EntityType.ORACLE_TABLE
        )[0]
        with pytest.raises(ValueError):
            engine.record_solution(engine.project_id, table.id, "algo")

    def test_a_solution_survives_reanalysing_the_log(self, engine, project_dir):
        """The point of keying it by identity instead of by row id."""
        target = incident(engine, "ORA-01400")
        engine.record_solution(
            engine.project_id, target["id"], "Faltaba la secuencia en PROD."
        )

        log = project_dir / "logs" / "inspeccion.log"
        log.write_text(
            log.read_text(encoding="utf-8") + "\n2026-07-30 03:10:00 otra noche\n",
            encoding="utf-8",
        )
        run = engine.analyze_project(engine.project_id)
        assert run.files_modified == 1

        after = incident(engine, "ORA-01400")
        assert after["solutions"][0]["description"] == "Faltaba la secuencia en PROD."

    def test_forgetting_one(self, engine):
        target = incident(engine, "ORA-01400")
        stored = engine.record_solution(engine.project_id, target["id"], "algo")
        assert engine.forget_solution(stored.id)
        assert incident(engine, "ORA-01400")["solutions"] == []
