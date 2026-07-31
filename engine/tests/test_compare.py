"""Comparing two environments by their graphs.

The scenario throughout: DEV has a column, a table and a procedure that PROD
does not. A text diff would drown that in reformatting; comparing entities and
claims should surface exactly those three and little else.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hana_engine.engine import KnowledgeEngine, build_default_registry
from hana_engine.query.compare import COMPARABLE_THRESHOLD

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _plant(root: Path) -> Path:
    (root / "sql").mkdir(parents=True)
    for name in ("guardar_inspeccion.sql", "consulta_inspecciones.sql"):
        shutil.copy(FIXTURES / "sql" / name, root / "sql")
    shutil.copy(FIXTURES / "sql" / "pkg_inspeccion.pkb", root / "sql")
    return root


def _age(root: Path) -> None:
    """Turn a copy into the older PROD: no NETWGT, no resumen()."""
    script = root / "sql" / "guardar_inspeccion.sql"
    text = script.read_text(encoding="utf-8")
    text = text.replace("        netwgt,\n", "").replace("        :P117_NETWGT,\n", "")
    script.write_text(text, encoding="utf-8")

    body = root / "sql" / "pkg_inspeccion.pkb"
    source = body.read_text(encoding="utf-8")
    start = source.index("    procedure resumen")
    end = source.index("end pkg_inspeccion;")
    body.write_text(source[:start] + source[end:], encoding="utf-8")


@pytest.fixture
def compared(db_path: Path, tmp_path: Path):
    engine = KnowledgeEngine(db_path, registry=build_default_registry())
    dev = _plant(tmp_path / "dev")
    prod = _plant(tmp_path / "prod")
    _age(prod)

    left = engine.open_project(dev)
    right = engine.open_project(prod)
    engine.analyze_project(left.id)
    engine.analyze_project(right.id)
    yield engine, left.id, right.id
    engine.close()


def names(grouped: dict, kind: str) -> set[str]:
    return {hit["name"] for hit in grouped.get(kind, [])}


def claims(grouped: dict, relation: str) -> set[tuple[str, str]]:
    return {
        (item["source_name"], item["target_name"])
        for item in grouped.get(relation, [])
    }


class TestWhatChanged:
    def test_an_entity_that_only_exists_in_one_side(self, compared):
        engine, left, right = compared
        report = engine.queries.compare(left, right)
        assert "resumen" in names(report.entities_only_left, "OracleProcedure")
        assert "uc_insp_rsm" in names(report.entities_only_left, "OracleTable")

    def test_the_apex_item_that_disappeared(self, compared):
        engine, left, right = compared
        report = engine.queries.compare(left, right)
        assert "P117_NETWGT" in names(report.entities_only_left, "ApexItem")

    def test_a_query_that_stopped_using_a_column(self, compared):
        """The interesting kind: the column still exists, the write does not."""
        engine, left, right = compared
        report = engine.queries.compare(left, right)
        assert ("insert#2", "netwgt") in claims(
            report.relations_only_left, "QUERY_USES_COLUMN"
        )
        # The column itself survives, because another script still reads it.
        assert "netwgt" not in names(report.entities_only_left, "OracleColumn")

    def test_nothing_is_reported_as_missing_from_the_older_side(self, compared):
        """PROD is a strict subset here; inventing differences would be a bug."""
        engine, left, right = compared
        report = engine.queries.compare(left, right)
        assert report.entities_only_right == {}

    def test_identical_projects_produce_an_empty_report(self, db_path, tmp_path):
        engine = KnowledgeEngine(db_path, registry=build_default_registry())
        one = engine.open_project(_plant(tmp_path / "uno"))
        two = engine.open_project(_plant(tmp_path / "dos"))
        engine.analyze_project(one.id)
        engine.analyze_project(two.id)

        report = engine.queries.compare(one.id, two.id)
        assert report.entities_only_left == {}
        assert report.entities_only_right == {}
        assert report.relations_only_left == {}
        assert report.relations_only_right == {}
        assert report.shared_entities > 0
        engine.close()

    def test_containment_edges_are_not_reported(self, compared):
        """They restate the entity list instead of adding to it."""
        engine, left, right = compared
        report = engine.queries.compare(left, right)
        assert "FILE_CONTAINS_ENTITY" not in report.relations_only_left
        assert "ENTITY_DEFINED_IN_FILE" not in report.relations_only_left

    def test_the_summary_counts_both_sides(self, compared):
        engine, left, right = compared
        report = engine.queries.compare(left, right)
        assert report.left.entities > report.right.entities
        assert report.shared_entities > 0
        assert report.shared_relations > 0


class TestComparability:
    """The guard against comparing the wrong two things."""

    def test_two_unrelated_projects_are_flagged(self, db_path, tmp_path):
        engine = KnowledgeEngine(db_path, registry=build_default_registry())
        one = engine.open_project(_plant(tmp_path / "uno"))

        other = tmp_path / "otro"
        (other / "scripts").mkdir(parents=True)
        shutil.copy(
            FIXTURES / "sql" / "guardar_inspeccion.sql",
            other / "scripts" / "distinto.sql",
        )
        two = engine.open_project(other)
        engine.analyze_project(one.id)
        engine.analyze_project(two.id)

        report = engine.queries.compare(one.id, two.id)
        assert report.comparable is False
        assert report.path_overlap < COMPARABLE_THRESHOLD
        # The wording has to say it is the comparison that is wrong, not the code.
        assert "no sean dos versiones del mismo" in report.warning
        engine.close()

    def test_the_same_layout_is_comparable(self, compared):
        engine, left, right = compared
        report = engine.queries.compare(left, right)
        assert report.comparable is True
        assert report.warning is None
        assert report.path_overlap == pytest.approx(1.0)

    def test_an_unknown_project_yields_nothing(self, compared):
        engine, left, _ = compared
        assert engine.queries.compare(left, "fantasma") is None
        assert engine.queries.compare("fantasma", left) is None


class TestLimits:
    def test_truncation_is_reported(self, compared):
        engine, left, right = compared
        report = engine.queries.compare(left, right, limit=1)
        assert report.truncated is True

    def test_an_untruncated_report_says_so(self, compared):
        engine, left, right = compared
        assert engine.queries.compare(left, right, limit=1000).truncated is False
