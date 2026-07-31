"""Manual annotations, and the one property that makes them worth having.

A verdict that disappears on the next analysis is worse than no verdict at all:
the person who recorded it has no reason to check, and finds out much later that
their work was thrown away. Most of this file is about that single risk.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hana_engine.domain.naming import annotation_key
from hana_engine.domain.types import EntityType, RelationType
from hana_engine.engine import KnowledgeEngine, build_default_registry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "inspeccion"
    (root / "sql").mkdir(parents=True)
    (root / "config").mkdir()
    shutil.copy(FIXTURES / "sql" / "guardar_inspeccion.sql", root / "sql")
    shutil.copy(FIXTURES / "sql" / "consulta_inspecciones.sql", root / "sql")
    shutil.copy(FIXTURES / "json" / "apex_inspeccion.json", root / "config")
    return root


@pytest.fixture
def engine(db_path: Path, project_dir: Path):
    instance = KnowledgeEngine(db_path, registry=build_default_registry())
    project = instance.open_project(project_dir)
    instance.analyze_project(project.id)
    instance.project_id = project.id
    yield instance
    instance.close()


def find(engine, name: str, entity_type: EntityType):
    hits = engine.queries.resolve(engine.project_id, name, entity_type=entity_type)
    assert hits, f"no se encontró {name}"
    return hits[0]


def page_item_edge(engine):
    """The inferred edge from APEX page 117 to one of its items."""
    page = find(engine, "117", EntityType.APEX_PAGE)
    for edge in engine.repos.relationships.outgoing(page.id):
        if edge.relation_type is RelationType.APEX_PAGE_CONTAINS_ITEM:
            return edge
    raise AssertionError("no se encontró la relación página→item")


class TestRecordingAVerdict:
    def test_confirming_an_entity_marks_it_manual(self, engine):
        """The status the schema always allowed and nothing ever wrote."""
        page = find(engine, "117", EntityType.APEX_PAGE)
        assert page.verification_status == "inferred"

        engine.annotate_entity(engine.project_id, page.id, "confirmed", note="es la 117")

        after = engine.repos.entities.get(page.id)
        assert after.verification_status.value == "manual"

    def test_confidence_is_left_alone(self, engine):
        """Confidence answers "how sure is HANA", which a human verdict is not.

        Writing 1.0 here would dress a person's opinion up as the machine having
        become more certain, and the next reader could not tell them apart.
        """
        page = find(engine, "117", EntityType.APEX_PAGE)
        before = engine.repos.entities.get(page.id).confidence

        engine.annotate_entity(engine.project_id, page.id, "confirmed")

        assert engine.repos.entities.get(page.id).confidence == before

    def test_rejecting_is_recorded_as_such(self, engine):
        page = find(engine, "117", EntityType.APEX_PAGE)
        engine.annotate_entity(
            engine.project_id, page.id, "rejected", note="esa página no existe"
        )
        stored = engine.annotations(engine.project_id)
        assert stored[0]["verdict"] == "rejected"
        assert stored[0]["note"] == "esa página no existe"

    def test_the_note_is_the_point(self, engine):
        """Without the why, an annotation is a click nobody else can use."""
        page = find(engine, "117", EntityType.APEX_PAGE)
        engine.annotate_entity(
            engine.project_id, page.id, "confirmed", note="confirmado con Fabián"
        )
        assert engine.annotations(engine.project_id)[0]["note"] == "confirmado con Fabián"

    def test_a_relationship_can_be_judged_too(self, engine):
        edge = page_item_edge(engine)
        engine.annotate_relationship(engine.project_id, edge.id, "rejected")
        assert engine.repos.relationships.get(edge.id).status.value == "manual"

    def test_a_second_verdict_replaces_the_first(self, engine):
        page = find(engine, "117", EntityType.APEX_PAGE)
        engine.annotate_entity(engine.project_id, page.id, "confirmed")
        engine.annotate_entity(engine.project_id, page.id, "rejected", note="me equivoqué")

        stored = engine.annotations(engine.project_id)
        assert len(stored) == 1
        assert stored[0]["verdict"] == "rejected"

    def test_withdrawing_a_verdict(self, engine):
        page = find(engine, "117", EntityType.APEX_PAGE)
        engine.annotate_entity(engine.project_id, page.id, "confirmed")
        entity = engine.repos.entities.get(page.id)

        assert engine.clear_annotation(engine.project_id, "entity", entity.identity_key)
        assert engine.annotations(engine.project_id) == []

    def test_an_unknown_verdict_is_refused(self, engine):
        page = find(engine, "117", EntityType.APEX_PAGE)
        with pytest.raises(ValueError):
            engine.annotate_entity(engine.project_id, page.id, "quizás")

    def test_annotating_something_that_does_not_exist_is_refused(self, engine):
        with pytest.raises(ValueError):
            engine.annotate_entity(engine.project_id, "fantasma", "confirmed")


class TestSurvivingReanalysis:
    """The whole reason annotations live in their own table."""

    def test_a_verdict_survives_an_unchanged_reanalysis(self, engine):
        page = find(engine, "117", EntityType.APEX_PAGE)
        engine.annotate_entity(engine.project_id, page.id, "confirmed")

        engine.analyze_project(engine.project_id)

        assert engine.repos.entities.get(page.id).verification_status.value == "manual"

    def test_a_verdict_survives_the_file_being_edited(self, engine, project_dir):
        """The case that would actually lose the work.

        Editing a file deletes its relationships and rebuilds them from source.
        A verdict stored on the rebuilt row would be gone — silently.
        """
        page = find(engine, "117", EntityType.APEX_PAGE)
        engine.annotate_entity(engine.project_id, page.id, "confirmed", note="revisado")

        target = project_dir / "sql" / "guardar_inspeccion.sql"
        target.write_text(
            target.read_text(encoding="utf-8") + "\n-- un comentario nuevo\n",
            encoding="utf-8",
        )
        run = engine.analyze_project(engine.project_id)
        assert run.files_modified == 1

        after = find(engine, "117", EntityType.APEX_PAGE)
        assert after.verification_status == "manual"
        assert engine.annotations(engine.project_id)[0]["note"] == "revisado"

    def test_a_relationship_verdict_survives_the_file_being_edited(
        self, engine, project_dir
    ):
        """The harder half: relationship rows are deleted outright and rebuilt."""
        edge = page_item_edge(engine)
        source = engine.repos.entities.get(edge.source_entity_id)
        target_entity = engine.repos.entities.get(edge.target_entity_id)
        key = annotation_key(
            source.identity_key, edge.relation_type, target_entity.identity_key
        )
        engine.annotate_relationship(engine.project_id, edge.id, "rejected")

        script = project_dir / "sql" / "guardar_inspeccion.sql"
        script.write_text(
            script.read_text(encoding="utf-8") + "\n-- otro comentario\n",
            encoding="utf-8",
        )
        engine.analyze_project(engine.project_id)

        rebuilt = page_item_edge(engine)
        assert rebuilt.status.value == "manual"
        assert engine.annotations(engine.project_id)[0]["target_key"] == key

    def test_an_annotation_whose_target_vanished_is_kept_not_deleted(
        self, engine, project_dir
    ):
        """Code comes back. A verdict thrown away does not.

        The target is the INSERT statement itself, which only this file
        produces — page 117 would be a poor choice, because the APEX JSON
        declares it too and it would survive the file being emptied.
        """
        query = find(engine, "insert#2", EntityType.SQL_QUERY)
        engine.annotate_entity(engine.project_id, query.id, "confirmed")

        script = project_dir / "sql" / "guardar_inspeccion.sql"
        script.write_text("select 1 from dual;\n", encoding="utf-8")
        engine.analyze_project(engine.project_id)

        stored = engine.annotations(engine.project_id)
        assert len(stored) == 1
        # It matches nothing right now, and says so rather than pretending.
        assert stored[0]["resolved_id"] is None

    def test_it_reattaches_when_the_code_comes_back(self, engine, project_dir):
        query = find(engine, "insert#2", EntityType.SQL_QUERY)
        engine.annotate_entity(engine.project_id, query.id, "confirmed", note="ok")
        script = project_dir / "sql" / "guardar_inspeccion.sql"
        original = script.read_text(encoding="utf-8")

        script.write_text("select 1 from dual;\n", encoding="utf-8")
        engine.analyze_project(engine.project_id)
        script.write_text(original, encoding="utf-8")
        engine.analyze_project(engine.project_id)

        stored = engine.annotations(engine.project_id)
        assert stored[0]["resolved_id"] is not None
        restored = engine.repos.entities.get(stored[0]["resolved_id"])
        assert restored.verification_status.value == "manual"
        assert stored[0]["note"] == "ok"


class TestIsolation:
    def test_annotations_do_not_leak_between_projects(self, engine, tmp_path):
        page = find(engine, "117", EntityType.APEX_PAGE)
        engine.annotate_entity(engine.project_id, page.id, "confirmed")

        other_root = tmp_path / "otro"
        (other_root / "sql").mkdir(parents=True)
        shutil.copy(FIXTURES / "sql" / "guardar_inspeccion.sql", other_root / "sql")
        other = engine.open_project(other_root)
        engine.analyze_project(other.id)

        assert engine.annotations(other.id) == []
        assert len(engine.annotations(engine.project_id)) == 1

    def test_deleting_a_project_takes_its_annotations(self, engine):
        page = find(engine, "117", EntityType.APEX_PAGE)
        engine.annotate_entity(engine.project_id, page.id, "confirmed")
        engine.delete_project(engine.project_id)
        assert engine.repos.annotations.count(engine.project_id) == 0
