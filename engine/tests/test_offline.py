"""HANA must not open the network. Ever.

This is the constraint the whole product rests on: source code goes into the
engine and nothing leaves the machine. It is easy to state, easy to believe, and
easy to break by accident — an analyzer that resolves an XML entity, a library
that phones home for a version check, a stray `urlopen` in a helper.

So it is tested rather than asserted. The socket module is replaced with one that
raises on any attempt to reach out, and a full analysis is run through it: scan,
hash, all six analyzers, persistence, and every query. If any of that opens a
connection the test fails and names the call.
"""

from __future__ import annotations

import shutil
import socket
import ssl  # noqa: F401 -- imported so it subclasses the real socket, not the guard
from pathlib import Path

import pytest

from hana_engine.engine import KnowledgeEngine, build_default_registry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class NetworkAccessAttempted(AssertionError):
    """Raised the moment anything tries to reach the network."""


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch):
    """Make every outbound path fail loudly.

    Patching ``socket.socket`` catches sockets opened directly. The higher-level
    doors are stopped separately because a library could hold a reference from
    before this fixture ran.
    """

    def refuse(*args: object, **kwargs: object):
        raise NetworkAccessAttempted(
            "algo intentó abrir la red durante un análisis local"
        )

    class RefusingSocket:
        """A class, not a function: modules subclass ``socket.socket``."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            refuse()

    monkeypatch.setattr(socket, "socket", RefusingSocket)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    return refuse


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A project touching every analyzer, including the network-shaped bait."""
    root = tmp_path / "proyecto"
    (root / "sql").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "moca").mkdir()
    (root / "config").mkdir()

    shutil.copy(FIXTURES / "sql" / "guardar_inspeccion.sql", root / "sql")
    shutil.copy(FIXTURES / "sql" / "consulta_inspecciones.sql", root / "sql")
    shutil.copy(FIXTURES / "jrxml" / "Usr-RptInspeccion.jrxml", root / "reports")
    shutil.copy(FIXTURES / "moca" / "confirmar_inspeccion.mcmd", root / "moca")
    shutil.copy(FIXTURES / "json" / "apex_inspeccion.json", root / "config")
    return root


class TestNothingLeavesTheMachine:
    def test_a_full_analysis_opens_no_connection(
        self, db_path: Path, project_dir: Path, no_network
    ):
        with KnowledgeEngine(db_path, registry=build_default_registry()) as engine:
            project = engine.open_project(project_dir)
            run = engine.analyze_project(project.id)
            assert run.files_analyzed > 0

    def test_every_query_answers_without_the_network(
        self, db_path: Path, project_dir: Path, no_network
    ):
        with KnowledgeEngine(db_path, registry=build_default_registry()) as engine:
            project = engine.open_project(project_dir)
            engine.analyze_project(project.id)

            queries = engine.queries
            hits = queries.search(project.id, "insp")
            assert hits

            entity_id = hits[0].id
            queries.resolve(project.id, hits[0].normalized_name)
            queries.where_used(entity_id)
            queries.dependents(entity_id)
            queries.dependencies(entity_id)
            queries.tables_of_file(project.id, "sql/guardar_inspeccion.sql")
            queries.apex_items_in_file(project.id, "sql/guardar_inspeccion.sql")
            queries.changes_since(project.id)
            queries.files_with_errors(project.id)
            queries.low_confidence(project.id)
            queries.neighborhood(entity_id, depth=2)
            queries.er_model(project.id)
            queries.freshness(project.id)

    def test_a_jrxml_declaring_an_external_dtd_is_not_fetched(
        self, db_path: Path, tmp_path: Path, no_network
    ):
        """An XML parser that resolves entities would call out to the internet.

        This is the classic way a "local" tool starts making requests, and with a
        hostile file it is also how it starts reading /etc/passwd.
        """
        root = tmp_path / "malicioso"
        root.mkdir()
        (root / "reporte.jrxml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE jasperReport SYSTEM "http://example.invalid/jasper.dtd">\n'
            '<jasperReport name="Trampa">\n'
            '  <field name="numctl" class="java.lang.String"/>\n'
            "</jasperReport>\n",
            encoding="utf-8",
        )

        with KnowledgeEngine(db_path, registry=build_default_registry()) as engine:
            project = engine.open_project(root)
            # Must not raise NetworkAccessAttempted. A parse failure recorded as
            # an analysis error would be acceptable; a fetch would not.
            engine.analyze_project(project.id)

    def test_the_guard_itself_works(self, no_network):
        """A test that cannot fail proves nothing."""
        with pytest.raises(NetworkAccessAttempted):
            socket.create_connection(("example.invalid", 80))


class TestNoListeningPorts:
    def test_the_ipc_server_speaks_over_pipes_only(self):
        """The sidecar protocol is JSON-Lines on stdin/stdout.

        A port would mean anything on the machine — or the network, depending on
        the bind — could talk to the engine that holds the user's source code.
        """
        import inspect

        from hana_engine.ipc import server

        source = inspect.getsource(server)
        for forbidden in ("socket", "bind(", "listen(", "http", "localhost"):
            assert forbidden not in source.replace(
                "No sockets, no ports, no HTTP server", ""
            ), f"el servidor IPC menciona '{forbidden}'"
