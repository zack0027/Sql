"""The answering layer over the wire, and the protocol invariants it depends on.

The analysis once hung forever in the desktop application while every test here
stayed green, because the failure lived in the transport rather than the engine:
a progress message containing "análisis" left the process as a byte the host
could not decode, and the host gave up on the stream. These tests pin the two
properties that failure violated.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from hana_engine.engine import KnowledgeEngine, build_default_registry
from hana_engine.ipc.server import EngineServer, LineWriter

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class CapturingWriter(LineWriter):
    """Keeps the exact frames the server would have written."""

    def __init__(self) -> None:
        super().__init__(io.StringIO())
        self.lines: list[str] = []

    def send(self, payload: dict) -> None:
        from hana_engine.ipc.server import _encode

        line = json.dumps(_encode(payload), ensure_ascii=True, separators=(",", ":"))
        self.lines.append(line)

    def frames(self) -> list[dict]:
        return [json.loads(line) for line in self.lines]

    def responses(self) -> dict:
        return {f["id"]: f for f in self.frames() if "id" in f}


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "inspeccion"
    (root / "sql").mkdir(parents=True)
    (root / "reports").mkdir()
    shutil.copy(FIXTURES / "sql" / "guardar_inspeccion.sql", root / "sql")
    shutil.copy(FIXTURES / "jrxml" / "Usr-RptInspeccion.jrxml", root / "reports")
    return root


@pytest.fixture
def served(db_path: Path, project_dir: Path):
    """A server with an analysed project, ready to answer."""
    engine = KnowledgeEngine(db_path, registry=build_default_registry())
    project = engine.open_project(project_dir)
    engine.analyze_project(project.id)
    server = EngineServer(engine=engine, writer=CapturingWriter())
    yield server, project.id
    engine.close()


def ask(server: EngineServer, requests: list[dict]) -> dict:
    server.writer = CapturingWriter()
    server.serve(iter(json.dumps(request) for request in requests))
    return server.writer.responses()


class TestProtocolIsEncodingProof:
    """The bug that hung the application, pinned so it cannot return."""

    def test_every_frame_is_pure_ascii(self, served):
        """A frame with a raw accented byte killed the host's reader.

        Spanish progress messages carry accents. Emitting them raw made the line
        undecodable under a legacy codepage, so the whole protocol must escape
        non-ASCII instead of trusting the process encoding.
        """
        server, project_id = served
        responses = ask(
            server,
            [
                {"id": "1", "method": "analysis.run", "params": {"project_id": project_id}},
            ],
        )
        assert responses["1"]["ok"] is True
        for line in server.writer.lines:
            line.encode("ascii")  # raises if any frame carries a raw byte

    def test_accented_content_survives_the_round_trip(self, served):
        """Escaping must not lose the text — it is shown to the user."""
        server, _ = served
        writer = CapturingWriter()
        writer.send({"event": "progress", "data": {"message": "Comparando el análisis"}})
        assert "\\u" in writer.lines[0]
        assert json.loads(writer.lines[0])["data"]["message"] == "Comparando el análisis"

    def test_a_leading_byte_order_mark_is_tolerated(self, served):
        """Windows tooling writes a BOM; it is not JSON but it is not a fault."""
        server, project_id = served
        server.writer = CapturingWriter()
        server.serve(iter(['﻿{"id":"1","method":"engine.ping"}']))
        assert server.writer.responses()["1"]["ok"] is True


class TestQueriesOverTheWire:
    def test_search(self, served):
        server, project_id = served
        responses = ask(
            server,
            [{"id": "1", "method": "query.search",
              "params": {"project_id": project_id, "text": "UC_INSP_ENT"}}],
        )
        names = {hit["normalized_name"] for hit in responses["1"]["result"]}
        assert "UC_INSP_ENT" in names

    def test_where_used_carries_evidence(self, served):
        server, project_id = served
        responses = ask(
            server,
            [{"id": "1", "method": "query.resolve",
              "params": {"project_id": project_id, "name": "UC_INSP_ENT",
                         "entity_type": "OracleTable"}}],
        )
        entity_id = responses["1"]["result"][0]["id"]

        responses = ask(
            server,
            [{"id": "2", "method": "query.uses", "params": {"entity_id": entity_id}}],
        )
        hits = responses["2"]["result"]
        assert hits
        for hit in hits:
            assert hit["evidence"]["file_path"]
            assert hit["evidence"]["start_line"]
            assert hit["evidence"]["analyzer"]

    def test_neighborhood_is_a_drawable_graph(self, served):
        server, project_id = served
        responses = ask(
            server,
            [{"id": "1", "method": "query.resolve",
              "params": {"project_id": project_id, "name": "UC_INSP_ENT",
                         "entity_type": "OracleTable"}}],
        )
        entity_id = responses["1"]["result"][0]["id"]

        responses = ask(
            server,
            [{"id": "2", "method": "query.neighborhood",
              "params": {"entity_id": entity_id, "depth": 1}}],
        )
        graph = responses["2"]["result"]
        node_ids = {node["entity"]["id"] for node in graph["nodes"]}
        assert entity_id in node_ids
        for edge in graph["edges"]:
            assert edge["source_id"] in node_ids
            assert edge["target_id"] in node_ids

    def test_apex_items_of_a_file(self, served):
        server, project_id = served
        responses = ask(
            server,
            [{"id": "1", "method": "query.entities_in_file",
              "params": {"project_id": project_id,
                         "relative_path": "sql/guardar_inspeccion.sql",
                         "entity_type": "ApexItem"}}],
        )
        names = {hit["normalized_name"] for hit in responses["1"]["result"]}
        assert "P117_MUESTRA_SIZE_VER" in names

    def test_impact_travels_over_the_wire(self, served):
        server, project_id = served
        resolved = ask(
            server,
            [{"id": "1", "method": "query.resolve",
              "params": {"project_id": project_id,
                         "name": "UC_INSP_ENT.NETWGT",
                         "entity_type": "OracleColumn"}}],
        )["1"]["result"]
        assert resolved, "no se resolvió la columna"

        responses = ask(
            server,
            [{"id": "1", "method": "query.impact",
              "params": {"entity_id": resolved[0]["id"], "depth": 3}}],
        )
        report = responses["1"]["result"]
        assert report["nodes"]
        assert report["truncated"] is False
        # The whole payload the panel needs, including the proof.
        assert {
            "entity", "depth", "path", "min_confidence", "inferred_in_path",
            "relation_type", "evidence",
        } <= set(report["nodes"][0])
        assert report["nodes"][0]["evidence"]["file_path"]

    def test_an_impossible_direction_is_refused_by_name(self, served):
        """A bad argument must not surface as a Python traceback."""
        server, _ = served
        responses = ask(
            server,
            [{"id": "1", "method": "query.impact",
              "params": {"entity_id": "x", "direction": "sideways"}}],
        )
        assert responses["1"]["ok"] is False
        assert responses["1"]["error"]["code"] == "invalid_direction"

    def test_changes_and_errors_and_review(self, served):
        server, project_id = served
        responses = ask(
            server,
            [
                {"id": "1", "method": "query.changes", "params": {"project_id": project_id}},
                {"id": "2", "method": "query.errors", "params": {"project_id": project_id}},
                {"id": "3", "method": "query.low_confidence",
                 "params": {"project_id": project_id, "threshold": 1.0}},
            ],
        )
        assert responses["1"]["result"]["changes"]
        assert any(row["code"] == "undeclared_field" for row in responses["2"]["result"])
        assert any(
            hit["entity_type"] == "ApexPage" for hit in responses["3"]["result"]
        )

    def test_a_missing_parameter_is_a_clean_error(self, served):
        server, _ = served
        responses = ask(server, [{"id": "1", "method": "query.uses", "params": {}}])
        assert responses["1"]["error"]["code"] == "missing_param"

    def test_an_unknown_entity_answers_empty_not_broken(self, served):
        server, _ = served
        responses = ask(
            server,
            [{"id": "1", "method": "query.uses", "params": {"entity_id": "NO_EXISTE"}}],
        )
        assert responses["1"]["ok"] is True
        assert responses["1"]["result"] == []
