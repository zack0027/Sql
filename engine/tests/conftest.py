"""Shared fixtures."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from hana_engine.domain.analysis import AnalyzerRegistry  # noqa: E402
from hana_engine.engine import KnowledgeEngine  # noqa: E402
from hana_engine.persistence.database import open_knowledge_base  # noqa: E402
from hana_engine.persistence.repositories import Repositories  # noqa: E402


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "knowledge" / "hana.db"


@pytest.fixture
def connection(db_path: Path):
    conn = open_knowledge_base(db_path)
    yield conn
    conn.close()


@pytest.fixture
def repos(connection) -> Repositories:
    return Repositories(connection)


@pytest.fixture
def engine(db_path: Path):
    """An engine with an empty analyzer registry.

    Tests that need analyzers register their own, which is exactly how Etapa 2
    will plug the real ones in.
    """
    instance = KnowledgeEngine(db_path, registry=AnalyzerRegistry())
    yield instance
    instance.close()


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """A small project tree copied from ``fixtures/``.

    Layout mirrors a real Oracle/APEX/Jasper delivery: SQL scripts, a report, a
    MOCA command, a JSON descriptor, plus noise that must be ignored.
    """
    root = tmp_path / "project"
    (root / "sql").mkdir(parents=True)
    (root / "reports" / "images").mkdir(parents=True)
    (root / "moca").mkdir()
    (root / "config").mkdir()

    fixtures = REPO_ROOT / "fixtures"
    shutil.copy(fixtures / "sql" / "guardar_inspeccion.sql", root / "sql")
    shutil.copy(fixtures / "sql" / "consulta_inspecciones.sql", root / "sql")
    shutil.copy(fixtures / "jrxml" / "Usr-RptInspeccion.jrxml", root / "reports")
    shutil.copy(fixtures / "moca" / "confirmar_inspeccion.mcmd", root / "moca")
    shutil.copy(fixtures / "json" / "apex_inspeccion.json", root / "config")

    # A binary asset a report can reference.
    (root / "reports" / "images" / "checkboxOn.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    )

    # Noise that the default ignore list must exclude.
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text(
        "module.exports = 1;", encoding="utf-8"
    )
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "output.log").write_text("built\n", encoding="utf-8")

    return root
