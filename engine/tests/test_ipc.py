"""The JSON-Lines sidecar and the headless CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from jarvis_engine.cli import main as cli_main
from jarvis_engine.domain.analysis import AnalyzerRegistry
from jarvis_engine.engine import KnowledgeEngine
from jarvis_engine.ipc.server import EngineServer, LineWriter


class CapturingWriter(LineWriter):
    """Collects the frames the server would have written to stdout."""

    def __init__(self) -> None:
        super().__init__(io.StringIO())
        self.frames: list[dict] = []

    def send(self, payload: dict) -> None:
        # Round-trip through JSON so the test sees exactly what a client would,
        # including any value the encoder cannot serialise.
        self.frames.append(json.loads(json.dumps(self._json_ready(payload))))

    @staticmethod
    def _json_ready(payload: dict) -> dict:
        from jarvis_engine.ipc.server import _encode

        return _encode(payload)

    def responses(self) -> list[dict]:
        return [frame for frame in self.frames if "id" in frame]

    def events(self) -> list[dict]:
        return [frame for frame in self.frames if "event" in frame]


def _run(server: EngineServer, requests: list[dict]) -> CapturingWriter:
    lines = [json.dumps(request) for request in requests]
    server.serve(iter(lines))
    return server.writer  # type: ignore[return-value]


@pytest.fixture
def server(db_path: Path) -> EngineServer:
    engine = KnowledgeEngine(db_path, registry=AnalyzerRegistry())
    return EngineServer(engine=engine, writer=CapturingWriter())


class TestSidecar:
    def test_announces_itself_and_answers_a_ping(self, server):
        writer = _run(server, [{"id": "1", "method": "engine.ping"}])
        assert writer.events()[0]["event"] == "ready"
        assert writer.responses()[0] == {
            "id": "1",
            "ok": True,
            "result": {"pong": True, "protocol": 1},
        }

    def test_unknown_methods_return_a_structured_error(self, server):
        writer = _run(server, [{"id": "1", "method": "does.not.exist"}])
        response = writer.responses()[0]
        assert response["ok"] is False
        assert response["error"]["code"] == "unknown_method"

    def test_malformed_json_does_not_kill_the_sidecar(self, server):
        server.serve(iter(["{not json", json.dumps({"id": "2", "method": "engine.ping"})]))
        writer = server.writer
        codes = [
            frame["error"]["code"]
            for frame in writer.responses()
            if frame["ok"] is False
        ]
        assert "invalid_json" in codes
        assert any(frame["ok"] and frame["id"] == "2" for frame in writer.responses())

    def test_missing_parameters_are_reported(self, server):
        writer = _run(server, [{"id": "1", "method": "project.open", "params": {}}])
        assert writer.responses()[0]["error"]["code"] == "missing_param"

    def test_opening_a_bad_path_is_an_invalid_path_error(self, server, tmp_path):
        writer = _run(
            server,
            [
                {
                    "id": "1",
                    "method": "project.open",
                    "params": {"path": str(tmp_path / "ghost")},
                }
            ],
        )
        assert writer.responses()[0]["error"]["code"] == "invalid_path"

    def test_full_project_flow(self, server, sample_project):
        writer = _run(
            server,
            [
                {"id": "1", "method": "project.open", "params": {"path": str(sample_project)}},
                {"id": "2", "method": "project.list"},
                {"id": "3", "method": "engine.status"},
            ],
        )
        responses = {frame["id"]: frame for frame in writer.responses()}
        project = responses["1"]["result"]
        assert project["root_path"] == str(sample_project.resolve())
        assert project["status"] == "created"
        assert len(responses["2"]["result"]) == 1
        assert responses["3"]["result"]["offline"] is True
        assert responses["3"]["result"]["model_provider"] == "disabled"

    def test_analysis_emits_progress_and_a_finished_event(self, server, sample_project):
        writer = _run(
            server,
            [
                {"id": "1", "method": "project.open", "params": {"path": str(sample_project)}},
            ],
        )
        project_id = writer.responses()[0]["result"]["id"]

        server.writer = CapturingWriter()
        writer = _run(
            server,
            [{"id": "2", "method": "analysis.run", "params": {"project_id": project_id}}],
        )
        event_names = {frame["event"] for frame in writer.events()}
        assert "progress" in event_names
        assert "analysis.finished" in event_names

        run = writer.responses()[0]["result"]
        assert run["status"] == "completed"
        assert run["files_added"] > 0

    def test_files_and_stats_are_serialisable(self, server, sample_project):
        writer = _run(
            server,
            [
                {"id": "1", "method": "project.open", "params": {"path": str(sample_project)}},
            ],
        )
        project_id = writer.responses()[0]["result"]["id"]

        server.writer = CapturingWriter()
        writer = _run(
            server,
            [
                {"id": "2", "method": "analysis.run", "params": {"project_id": project_id}},
                {"id": "3", "method": "project.files", "params": {"project_id": project_id}},
                {"id": "4", "method": "project.stats", "params": {"project_id": project_id}},
                {"id": "5", "method": "analysis.history", "params": {"project_id": project_id}},
                {"id": "6", "method": "model.status"},
            ],
        )
        responses = {frame["id"]: frame for frame in writer.responses()}
        files = responses["3"]["result"]
        assert any(item["relative_path"].endswith(".sql") for item in files)
        assert responses["4"]["result"]["files"] == len(files)
        assert len(responses["5"]["result"]) == 1
        assert responses["6"]["result"]["available"] is False

    def test_cancel_is_answered_even_with_no_run_in_flight(self, server):
        writer = _run(server, [{"id": "1", "method": "analysis.cancel", "params": {}}])
        assert writer.responses()[0]["result"] == {"cancelled": 0}

    def test_scan_policy_round_trip(self, server, sample_project):
        writer = _run(
            server,
            [{"id": "1", "method": "project.open", "params": {"path": str(sample_project)}}],
        )
        project_id = writer.responses()[0]["result"]["id"]

        server.writer = CapturingWriter()
        writer = _run(
            server,
            [
                {
                    "id": "2",
                    "method": "project.scan_policy.set",
                    "params": {
                        "project_id": project_id,
                        "policy": {"max_depth": 5, "ignored_directories": [".git"]},
                    },
                },
                {
                    "id": "3",
                    "method": "project.scan_policy.get",
                    "params": {"project_id": project_id},
                },
            ],
        )
        responses = {frame["id"]: frame for frame in writer.responses()}
        assert responses["3"]["result"]["max_depth"] == 5
        assert responses["3"]["result"]["ignored_directories"] == [".git"]


class TestCli:
    def test_open_analyze_and_report(self, db_path, sample_project, capsys):
        assert cli_main(["--db", str(db_path), "--json", "open", str(sample_project)]) == 0
        project_id = json.loads(capsys.readouterr().out)["id"]

        assert (
            cli_main(
                ["--db", str(db_path), "--json", "analyze", project_id, "--quiet"]
            )
            == 0
        )
        run = json.loads(capsys.readouterr().out)
        assert run["status"] == "completed"
        assert run["added"] > 0

        assert cli_main(["--db", str(db_path), "--json", "stats", project_id]) == 0
        stats = json.loads(capsys.readouterr().out)
        assert stats["files"] == run["files_scanned"]

    def test_reanalysing_reports_no_changes(self, db_path, sample_project, capsys):
        cli_main(["--db", str(db_path), "--json", "open", str(sample_project)])
        project_id = json.loads(capsys.readouterr().out)["id"]
        cli_main(["--db", str(db_path), "--json", "analyze", project_id, "--quiet"])
        capsys.readouterr()

        cli_main(["--db", str(db_path), "--json", "analyze", project_id, "--quiet"])
        run = json.loads(capsys.readouterr().out)
        assert run["added"] == 0
        assert run["modified"] == 0
        assert run["unchanged"] > 0

    def test_scan_is_a_dry_run_that_persists_nothing(self, db_path, sample_project, capsys):
        assert cli_main(["--db", str(db_path), "--json", "scan", str(sample_project)]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["files"] > 0

        cli_main(["--db", str(db_path), "--json", "projects"])
        assert json.loads(capsys.readouterr().out) == []

    def test_open_reports_a_missing_folder(self, db_path, tmp_path, capsys):
        code = cli_main(["--db", str(db_path), "open", str(tmp_path / "ghost")])
        assert code == 2
        assert "error" in capsys.readouterr().err

    def test_status_command(self, db_path, capsys):
        assert cli_main(["--db", str(db_path), "--json", "status"]) == 0
        status = json.loads(capsys.readouterr().out)
        assert status["version"]
        assert status["offline"] is True
