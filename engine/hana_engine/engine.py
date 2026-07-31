"""The engine facade.

Everything above this module — the CLI, the IPC sidecar, and eventually the
Tauri commands — talks to HANA through this class. It owns the connection, the
repositories, the analyzer registry and the pipeline, and it never imports
anything from Tauri, React or the network.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .domain.analysis import AnalyzerRegistry
from .domain.models import AnalysisRun, Annotation, Project, ScannedFile
from .domain.naming import annotation_key
from .domain.types import ProjectStatus
from .indexing.policy import ScanPolicy
from .indexing.scanner import ScanSecurityError, resolve_project_root
from .persistence.database import has_fts5, open_knowledge_base
from .persistence.repositories import Repositories
from .pipeline.orchestrator import (
    AnalysisPipeline,
    CancellationToken,
    ProgressCallback,
)
from .query import QueryEngine

#: Name of the knowledge base file inside the data directory.
DATABASE_FILENAME = "hana.db"


def default_data_directory() -> Path:
    """Where HANA keeps its knowledge base when the caller does not say.

    Respects ``HANA_DATA_DIR`` first — the packaged app sets it to Tauri's
    per-user app-data folder so the database never lands next to the binary.
    """
    override = os.environ.get("HANA_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "HanaKnowledgeEngine"
    xdg = os.environ.get("XDG_DATA_HOME")
    base_path = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base_path / "hana-knowledge-engine"


@dataclass
class EngineStatus:
    """What the home screen shows about the engine itself."""

    version: str
    database_path: str
    fts5_available: bool
    analyzers: list[str] = field(default_factory=list)
    projects: int = 0
    entities: int = 0
    relationships: int = 0
    model_provider: str = "disabled"
    offline: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectStats:
    """Per-project counters for the home screen and the explorer header."""

    project_id: str
    files: int = 0
    files_by_status: dict[str, int] = field(default_factory=dict)
    files_by_extension: dict[str, int] = field(default_factory=dict)
    entities: int = 0
    entities_by_type: dict[str, int] = field(default_factory=dict)
    relationships: int = 0
    relationships_by_type: dict[str, int] = field(default_factory=dict)
    evidence: int = 0
    errors: int = 0
    last_analysis_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectPathError(ValueError):
    """Raised when a folder cannot be adopted as a project."""


class KnowledgeEngine:
    """Open, analyse and query local knowledge bases."""

    VERSION = "0.1.0"

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        registry: AnalyzerRegistry | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else default_data_directory() / DATABASE_FILENAME
        self.connection = open_knowledge_base(self.db_path)
        self.repos = Repositories(self.connection)
        self.registry = registry if registry is not None else build_default_registry()
        self.pipeline = AnalysisPipeline(self.repos, self.registry)
        #: Answers questions about the graph. Deterministic: no model involved.
        self.queries = QueryEngine(
            self.connection, suite=self.registry.fingerprint()
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> KnowledgeEngine:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- projects -----------------------------------------------------------

    def open_project(
        self, root_path: str | Path, name: str | None = None
    ) -> Project:
        """Adopt a folder as a project, or return the project that already owns it.

        The path is canonicalised first, so the same folder reached through a
        symlink, a relative path or a different letter case maps to one project
        rather than several.
        """
        try:
            resolved = resolve_project_root(root_path)
        except ScanSecurityError as exc:
            raise ProjectPathError(str(exc)) from exc

        canonical = str(resolved)
        existing = self.repos.projects.get_by_root_path(canonical)
        if existing is not None:
            return existing

        project = Project(
            name=name or resolved.name or canonical,
            root_path=canonical,
            status=ProjectStatus.CREATED,
        )
        project.settings = {"scan": ScanPolicy().to_dict()}
        self.repos.projects.create(project)
        self.connection.commit()
        return project

    def get_project(self, project_id: str) -> Project | None:
        return self.repos.projects.get(project_id)

    def recent_projects(self, limit: int = 20) -> list[Project]:
        return self.repos.projects.list_recent(limit)

    def delete_project(self, project_id: str) -> None:
        """Forget a project and everything HANA learned from it.

        Only the knowledge base is touched; nothing on disk is removed.
        """
        self.repos.projects.delete(project_id)
        self.connection.commit()

    def scan_policy_for(self, project: Project) -> ScanPolicy:
        return ScanPolicy.from_dict(project.settings.get("scan"))

    def update_scan_policy(self, project_id: str, policy: ScanPolicy) -> None:
        project = self.repos.projects.get(project_id)
        if project is None:
            raise ProjectPathError(f"unknown project: {project_id}")
        settings = dict(project.settings)
        settings["scan"] = policy.to_dict()
        self.repos.projects.update_settings(project_id, settings)
        self.connection.commit()

    # -- analysis -----------------------------------------------------------

    def analyze_project(
        self,
        project_id: str,
        *,
        scanned_files: list[ScannedFile] | None = None,
        trigger: str = "manual",
        on_progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> AnalysisRun:
        project = self.repos.projects.get(project_id)
        if project is None:
            raise ProjectPathError(f"unknown project: {project_id}")
        return self.pipeline.run(
            project,
            scanned_files=scanned_files,
            policy=self.scan_policy_for(project),
            trigger=trigger,
            on_progress=on_progress,
            cancellation=cancellation,
        )

    def analysis_history(self, project_id: str, limit: int = 25) -> list[AnalysisRun]:
        return self.repos.runs.history(project_id, limit)

    def latest_run(self, project_id: str) -> AnalysisRun | None:
        return self.repos.runs.latest(project_id)

    # -- human judgement ----------------------------------------------------

    def annotate_entity(
        self,
        project_id: str,
        entity_id: str,
        verdict: str,
        *,
        note: str | None = None,
        author: str | None = None,
    ) -> Annotation:
        """Record a person's verdict on an entity.

        Takes the id because that is what a caller has in hand, and stores the
        identity key, because that is what survives a reanalysis.
        """
        entity = self.repos.entities.get(entity_id)
        if entity is None:
            raise ValueError(f"no existe la entidad {entity_id!r}")
        annotation = self.repos.annotations.set(
            project_id, "entity", entity.identity_key, verdict, note=note, author=author
        )
        self.repos.annotations.apply_to_project(project_id)
        self.connection.commit()
        return annotation

    def annotate_relationship(
        self,
        project_id: str,
        relationship_id: str,
        verdict: str,
        *,
        note: str | None = None,
        author: str | None = None,
    ) -> Annotation:
        relationship = self.repos.relationships.get(relationship_id)
        if relationship is None:
            raise ValueError(f"no existe la relación {relationship_id!r}")
        source = self.repos.entities.get(relationship.source_entity_id)
        target = self.repos.entities.get(relationship.target_entity_id)
        if source is None or target is None:
            raise ValueError("la relación apunta a una entidad que ya no existe")
        annotation = self.repos.annotations.set(
            project_id,
            "relationship",
            annotation_key(
                source.identity_key, relationship.relation_type, target.identity_key
            ),
            verdict,
            note=note,
            author=author,
        )
        self.repos.annotations.apply_to_project(project_id)
        self.connection.commit()
        return annotation

    def clear_annotation(
        self, project_id: str, target_kind: str, target_key: str
    ) -> bool:
        """Withdraw a verdict.

        The row it marked keeps ``manual`` until the next analysis rebuilds it.
        Reverting it here would mean guessing what the analyzer had said before
        a person overruled it, and that is not recorded anywhere.
        """
        removed = self.repos.annotations.clear(project_id, target_kind, target_key)
        self.connection.commit()
        return removed

    def annotations(self, project_id: str) -> list[dict[str, Any]]:
        return self.repos.annotations.resolved(project_id)

    # -- reporting ----------------------------------------------------------

    def status(self) -> EngineStatus:
        projects = self.connection.execute(
            "SELECT COUNT(*) AS n FROM projects"
        ).fetchone()["n"]
        return EngineStatus(
            version=self.VERSION,
            database_path=str(self.db_path),
            fts5_available=has_fts5(self.connection),
            analyzers=[analyzer.name for analyzer in self.registry.all()],
            projects=int(projects),
            entities=self.repos.entities.count(),
            relationships=self.repos.relationships.count(),
            model_provider="disabled",
            offline=True,
        )

    def project_stats(self, project_id: str) -> ProjectStats:
        project = self.repos.projects.get(project_id)
        return ProjectStats(
            project_id=project_id,
            files=self.repos.files.count(project_id),
            files_by_status=self.repos.files.count_by_status(project_id),
            files_by_extension=self.repos.files.count_by_extension(project_id),
            entities=self.repos.entities.count(project_id),
            entities_by_type=self.repos.entities.count_by_type(project_id),
            relationships=self.repos.relationships.count(project_id),
            relationships_by_type=self.repos.relationships.count_by_type(project_id),
            evidence=self.repos.evidence.count(project_id),
            errors=self.repos.errors.count(project_id),
            last_analysis_at=project.last_analysis_at if project else None,
        )

    def file_tree(self, project_id: str) -> list[dict[str, Any]]:
        """Flat list of files for the explorer; the UI builds the tree.

        Sending a flat, sorted list keeps the payload small and lets the
        frontend virtualise the tree without the engine guessing at what is
        expanded.
        """
        return [
            {
                "id": record.id,
                "relative_path": record.relative_path,
                "extension": record.extension,
                "detected_type": record.detected_type,
                "size_bytes": record.size_bytes,
                "analysis_status": record.analysis_status.value,
                "modified_at": record.modified_at,
                "is_modified": record.analyzed_hash != record.content_hash,
                "skip_reason": record.skip_reason.value if record.skip_reason else None,
            }
            for record in self.repos.files.list_by_project(project_id)
        ]


def build_default_registry() -> AnalyzerRegistry:
    """Assemble the analyzer registry.

    Registration order does not matter — the registry sorts by descending
    priority — but the priorities do: a specific analyzer should see a file
    before a generic one, so that the label recorded on the resulting knowledge
    names the analyzer that actually understood the syntax.

    Several analyzers may claim the same file, and that is intended. A ``.sql``
    holding an APEX process is read by both :class:`SqlAnalyzer` (tables,
    columns) and :class:`ApexAnalyzer` (items, page, column mappings); their
    findings merge into one graph through the shared identity keys.
    """
    from .analyzers.apex import ApexAnalyzer
    from .analyzers.jrxml import JrxmlAnalyzer
    from .analyzers.moca import MocaAnalyzer
    from .analyzers.sql import SqlAnalyzer
    from .analyzers.structured import CodeAnalyzer, JsonAnalyzer

    registry = AnalyzerRegistry()
    for analyzer in (
        JrxmlAnalyzer(),
        MocaAnalyzer(),
        SqlAnalyzer(),
        ApexAnalyzer(),
        JsonAnalyzer(),
        CodeAnalyzer(),
    ):
        registry.register(analyzer)
    return registry
