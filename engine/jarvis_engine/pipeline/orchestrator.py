"""The analysis pipeline.

One pass over a project: scan, diff, persist the inventory, purge the knowledge
that changed files used to justify, re-analyse them, and record what happened.

Three properties this module is responsible for, and which the tests pin down:

* **Nothing is analysed twice for nothing.** Only files whose content hash moved
  are re-read.
* **No stale knowledge survives.** Re-analysing a file first deletes every
  relationship and every piece of evidence that file had produced, so an edge
  whose supporting line was removed disappears with it.
* **One bad file cannot sink the run.** Analyzer failures are caught per file
  and per analyzer, recorded in ``analysis_errors``, and the walk continues.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from ..domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    AnalyzerRegistry,
    EntityDraft,
    RelationshipDraft,
)
from ..domain.confidence import CONFIRMED
from ..domain.models import (
    AnalysisError,
    AnalysisRun,
    Entity,
    Evidence,
    FileRecord,
    Project,
    Relationship,
    ScannedFile,
)
from ..domain.naming import (
    entity_identity_key,
    normalize_name,
    normalize_relative_path,
    relationship_identity_key,
)
from ..domain.types import (
    AnalysisRunStatus,
    ChangeKind,
    EntityType,
    FileAnalysisStatus,
    ProjectStatus,
    RelationType,
    Severity,
    VerificationStatus,
)
from ..indexing.file_types import (
    detect_type,
    extension_of,
    guess_project_type,
    is_analyzable,
)
from ..indexing.policy import ScanPolicy
from ..indexing.scanner import read_text_file, scan_project
from ..persistence.database import transaction
from ..persistence.repositories import Repositories
from .changes import ChangeSet, FileChange, diff

#: Files persisted per transaction while syncing the inventory.
INVENTORY_BATCH_SIZE = 250

#: Longest a single file may hold up the pipeline before it is abandoned.
DEFAULT_FILE_TIMEOUT_SECONDS = 30.0


class CancellationToken:
    """A thread-safe stop flag shared with the UI."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def __call__(self) -> bool:
        return self.is_cancelled


@dataclass
class ProgressEvent:
    """A step of a run, forwarded to the UI so it can show real progress."""

    project_id: str
    phase: str  # scanning | diffing | inventory | analyzing | finalizing
    current: int = 0
    total: int = 0
    message: str = ""
    run_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "phase": self.phase,
            "current": self.current,
            "total": self.total,
            "message": self.message,
        }


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class FileAnalysisOutcome:
    """What happened to one file."""

    file_id: str
    relative_path: str
    entities_created: int = 0
    relationships_created: int = 0
    warnings: int = 0
    errors: int = 0
    analyzers: list[str] = field(default_factory=list)


class AnalysisPipeline:
    """Coordinates one analysis run over one project."""

    def __init__(
        self,
        repositories: Repositories,
        registry: AnalyzerRegistry | None = None,
        *,
        file_timeout_seconds: float = DEFAULT_FILE_TIMEOUT_SECONDS,
    ) -> None:
        self.repos = repositories
        self.registry = registry if registry is not None else AnalyzerRegistry()
        self.file_timeout_seconds = file_timeout_seconds

    # -- public API ---------------------------------------------------------

    def run(
        self,
        project: Project,
        *,
        scanned_files: Sequence[ScannedFile] | None = None,
        policy: ScanPolicy | None = None,
        trigger: str = "manual",
        on_progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> AnalysisRun:
        """Analyse a project and return the completed run record.

        ``scanned_files`` lets the caller supply an inventory produced elsewhere
        — in the desktop app that is the Rust scanner. When omitted the engine
        walks the folder itself.
        """
        run = self.repos.runs.start(project.id, trigger=trigger)
        self.repos.projects.set_status(project.id, ProjectStatus.SCANNING)
        self.repos.connection.commit()

        emit = _progress_emitter(on_progress, project.id, run.id)

        try:
            inventory = self._obtain_inventory(
                project, scanned_files, policy, emit, cancellation
            )
            if _cancelled(cancellation):
                return self._cancel(run, project)

            emit("diffing", 0, 0, "Comparando con el análisis anterior")
            known = self.repos.files.path_index(project.id)
            change_set = diff(inventory, known)

            run.files_scanned = len(inventory)
            run.files_added = len(change_set.added)
            run.files_modified = len(change_set.modified)
            run.files_unchanged = len(change_set.unchanged)
            run.files_deleted = len(change_set.deleted)

            persisted = self._sync_inventory(
                project, run, change_set, emit, cancellation
            )
            if _cancelled(cancellation):
                return self._cancel(run, project)

            self.repos.projects.set_status(project.id, ProjectStatus.ANALYZING)
            self.repos.connection.commit()
            self._analyze_changed(
                project, run, change_set, persisted, emit, cancellation
            )
            if _cancelled(cancellation):
                return self._cancel(run, project)

            emit("finalizing", 0, 0, "Actualizando el proyecto")
            self._finalize_project(project)
            self.repos.runs.finish(run, AnalysisRunStatus.COMPLETED)
            self.repos.connection.commit()
            return run

        except Exception as exc:  # noqa: BLE001 - the run record must survive
            self.repos.connection.rollback()
            self.repos.runs.finish(
                run, AnalysisRunStatus.FAILED, message=f"{type(exc).__name__}: {exc}"
            )
            self.repos.projects.set_status(project.id, ProjectStatus.ERROR)
            self.repos.connection.commit()
            raise

    # -- phases -------------------------------------------------------------

    def _obtain_inventory(
        self,
        project: Project,
        scanned_files: Sequence[ScannedFile] | None,
        policy: ScanPolicy | None,
        emit: Callable[..., None],
        cancellation: CancellationToken | None,
    ) -> list[ScannedFile]:
        if scanned_files is not None:
            emit("scanning", len(scanned_files), len(scanned_files), "Inventario recibido")
            return list(scanned_files)

        effective_policy = policy or ScanPolicy.from_dict(project.settings.get("scan"))
        emit("scanning", 0, 0, f"Escaneando {project.root_path}")

        def report_progress(seen: int, path: str) -> None:
            if seen % 50 == 0:
                emit("scanning", seen, 0, path)

        report = scan_project(
            project.root_path,
            effective_policy,
            on_progress=report_progress,
            should_cancel=cancellation,
        )
        for message in report.errors:
            self._record_error(
                project.id,
                None,
                None,
                analyzer="scanner",
                code="scan_error",
                message=message,
                severity=Severity.WARNING,
            )
        # Skipped files are still inventoried: the user must be able to see that
        # a 40 MB export exists and was deliberately not read.
        return report.files + report.skipped

    def _sync_inventory(
        self,
        project: Project,
        run: AnalysisRun,
        change_set: ChangeSet,
        emit: Callable[..., None],
        cancellation: CancellationToken | None,
    ) -> dict[str, FileRecord]:
        """Write the observed inventory into ``files`` and ``file_versions``.

        Returns the persisted record for every live path, so the analysis phase
        does not have to read them back.
        """
        total = len(list(change_set.all_changes()))
        persisted: dict[str, FileRecord] = {}
        processed = 0
        pending = 0

        for change in change_set.all_changes():
            if _cancelled(cancellation):
                self.repos.connection.commit()
                return persisted
            record = self._apply_change(project, run, change)
            if record is not None:
                persisted[change.relative_path] = record
            processed += 1
            pending += 1
            if pending >= INVENTORY_BATCH_SIZE:
                self.repos.connection.commit()
                pending = 0
                emit("inventory", processed, total, change.relative_path)

        self.repos.connection.commit()
        emit("inventory", processed, total, "Inventario actualizado")
        return persisted

    def _apply_change(
        self, project: Project, run: AnalysisRun, change: FileChange
    ) -> FileRecord | None:
        if change.kind is ChangeKind.DELETED:
            self._apply_deletion(project, run, change)
            return None

        scanned = self._typed(change.scanned)
        assert scanned is not None  # every non-deletion carries a scan result

        if change.record is None:
            record = FileRecord(
                project_id=project.id,
                relative_path=normalize_relative_path(scanned.relative_path),
                absolute_path=scanned.absolute_path,
                extension=scanned.extension,
                detected_type=scanned.detected_type,
                size_bytes=scanned.size_bytes,
                content_hash=scanned.content_hash,
                modified_at=scanned.modified_at,
                skip_reason=scanned.skip_reason,
                analysis_status=FileAnalysisStatus.PENDING,
            )
            self.repos.files.insert(record)
        else:
            record = self.repos.files.update_from_scan(change.record, scanned)
            if change.kind is not ChangeKind.UNCHANGED:
                self.repos.files.set_analysis_status(
                    record.id, FileAnalysisStatus.PENDING
                )

        if change.kind is not ChangeKind.UNCHANGED and scanned.content_hash:
            self.repos.file_versions.record(
                file_id=record.id,
                project_id=project.id,
                content_hash=scanned.content_hash,
                size_bytes=scanned.size_bytes,
                modified_at=scanned.modified_at,
                change_kind=change.kind,
                analysis_run_id=run.id,
            )

        return record

    @staticmethod
    def _typed(scanned: ScannedFile | None) -> ScannedFile | None:
        """Derive the extension and detected type from the path.

        The Rust scanner deliberately does not classify files, so the extension
        table exists in Python only. Re-deriving here means an inventory produced
        natively and one produced by the Python scanner are typed identically.
        """
        if scanned is None:
            return None
        return replace(
            scanned,
            extension=extension_of(scanned.relative_path),
            detected_type=detect_type(scanned.relative_path),
        )

    def _apply_deletion(
        self, project: Project, run: AnalysisRun, change: FileChange
    ) -> None:
        record = change.record
        assert record is not None
        if record.content_hash:
            self.repos.file_versions.record(
                file_id=record.id,
                project_id=project.id,
                content_hash=record.content_hash,
                size_bytes=record.size_bytes,
                modified_at=record.modified_at,
                change_kind=ChangeKind.DELETED,
                analysis_run_id=run.id,
            )
        # The file is gone, so everything it proved is gone with it. The file row
        # and its history stay, which is what makes "what changed?" answerable.
        self._purge_file_knowledge(record.id)
        self.repos.files.mark_deleted(record.id)

    def _analyze_changed(
        self,
        project: Project,
        run: AnalysisRun,
        change_set: ChangeSet,
        persisted: dict[str, FileRecord],
        emit: Callable[..., None],
        cancellation: CancellationToken | None,
    ) -> None:
        candidates = [
            persisted.get(change.relative_path) for change in change_set.to_analyze()
        ]
        targets = [
            record
            for record in candidates
            if record is not None
            and record.skip_reason is None
            and is_analyzable(record.detected_type)
        ]
        total = len(targets)

        for index, record in enumerate(targets, start=1):
            if _cancelled(cancellation):
                self.repos.connection.commit()
                return
            emit("analyzing", index, total, record.relative_path)

            outcome = self._analyze_file(project, run, record)
            run.files_analyzed += 1
            run.entities_created += outcome.entities_created
            run.relationships_created += outcome.relationships_created
            run.error_count += outcome.errors

        run.files_skipped = len(change_set.to_analyze()) - total
        self.repos.connection.commit()
        emit("analyzing", total, total, "Análisis completado")

    # -- per-file analysis --------------------------------------------------

    def _analyze_file(
        self, project: Project, run: AnalysisRun, record: FileRecord
    ) -> FileAnalysisOutcome:
        """Read one file, run every applicable analyzer, persist the results.

        Wrapped in a single transaction: either the file's new knowledge lands
        whole, or the file is left marked failed with its old knowledge already
        purged — never a half-written graph.
        """
        outcome = FileAnalysisOutcome(file_id=record.id, relative_path=record.relative_path)

        try:
            content = read_text_file(record.absolute_path)
        except OSError as exc:
            self._record_error(
                project.id,
                run.id,
                record.id,
                analyzer="pipeline",
                code="unreadable_file",
                message=str(exc),
            )
            self.repos.files.set_analysis_status(record.id, FileAnalysisStatus.FAILED)
            self.repos.connection.commit()
            outcome.errors += 1
            return outcome

        merged = AnalysisResult()
        for analyzer in self.registry.for_file(record.relative_path, content):
            context = AnalysisContext(
                project_id=project.id,
                file_id=record.id,
                relative_path=record.relative_path,
                absolute_path=record.absolute_path,
                extension=record.extension,
                detected_type=record.detected_type,
                content=content,
                analysis_run_id=run.id,
            )
            try:
                result = analyzer.analyze(context)
            except Exception as exc:  # noqa: BLE001 - isolate the plugin
                self._record_error(
                    project.id,
                    run.id,
                    record.id,
                    analyzer=analyzer.name,
                    code="analyzer_exception",
                    message=f"{type(exc).__name__}: {exc}",
                    detail={"traceback": traceback.format_exc(limit=8)},
                )
                outcome.errors += 1
                continue
            outcome.analyzers.append(analyzer.name)
            merged.extend(result)

        for warning in merged.warnings:
            self._record_error(
                project.id,
                run.id,
                record.id,
                analyzer="analyzer",
                code=warning.code,
                message=warning.message,
                severity=Severity.WARNING,
                detail=warning.detail,
            )
            outcome.warnings += 1
        for error in merged.errors:
            self._record_error(
                project.id,
                run.id,
                record.id,
                analyzer="analyzer",
                code=error.code,
                message=error.message,
                detail=error.detail,
            )
            outcome.errors += 1

        try:
            with transaction(self.repos.connection):
                # Order matters. Claims are dropped first, then the new results
                # are written, and only then are orphans collected. Collecting
                # before writing would delete every entity this file still
                # defines and re-insert it under a fresh id, so anything holding
                # an entity id — a bookmark, a graph selection, a saved query —
                # would break on every re-analysis.
                self._forget_file_claims(record.id)
                self._persist_results(project, run, record, merged, outcome)
                self.repos.entities.delete_orphans_of_file(record.id)
                self.repos.files.set_analysis_status(
                    record.id,
                    FileAnalysisStatus.ANALYZED,
                    analyzed_hash=record.content_hash,
                )
        except Exception as exc:  # noqa: BLE001 - persistence must not kill the run
            self._record_error(
                project.id,
                run.id,
                record.id,
                analyzer="pipeline",
                code="persist_failed",
                message=f"{type(exc).__name__}: {exc}",
                detail={"traceback": traceback.format_exc(limit=8)},
            )
            self.repos.files.set_analysis_status(record.id, FileAnalysisStatus.FAILED)
            self.repos.connection.commit()
            outcome.errors += 1

        return outcome

    def _persist_results(
        self,
        project: Project,
        run: AnalysisRun,
        record: FileRecord,
        result: AnalysisResult,
        outcome: FileAnalysisOutcome,
    ) -> None:
        file_entity, created = self._ensure_file_entity(project, record)
        if created:
            outcome.entities_created += 1
        # The file's own existence is its provenance. Recording it means a File
        # entity is never mistaken for an orphan, and the panel can cite where a
        # file node came from like any other entity.
        self._add_evidence(
            project,
            run,
            record,
            entity_id=file_entity.id,
            snippet=record.relative_path,
            original_name=record.relative_path,
            analyzer="pipeline",
        )

        ref_to_id: dict[str, str] = {file_entity.identity_key: file_entity.id}

        for draft in result.entities:
            entity, was_created = self._persist_entity(project, record, draft)
            ref_to_id[draft.ref] = entity.id
            if was_created:
                outcome.entities_created += 1
            self._add_evidence(
                project,
                run,
                record,
                entity_id=entity.id,
                span=draft.span,
                snippet=draft.evidence_snippet,
                original_name=draft.name,
                analyzer=self._analyzer_label(outcome),
                confidence=draft.confidence,
                status=draft.verification_status or VerificationStatus.CONFIRMED,
            )
            # Every entity a file produced is reachable from that file's node.
            self._persist_relationship(
                project,
                run,
                record,
                RelationshipDraft(
                    source_ref=file_entity.identity_key,
                    relation_type=RelationType.FILE_CONTAINS_ENTITY,
                    target_ref=draft.ref,
                    span=draft.span,
                    evidence_snippet=draft.evidence_snippet,
                    confidence=CONFIRMED,
                ),
                ref_to_id,
                outcome,
            )

        for draft in result.relationships:
            self._persist_relationship(project, run, record, draft, ref_to_id, outcome)

    def _persist_entity(
        self, project: Project, record: FileRecord, draft: EntityDraft
    ) -> tuple[Entity, bool]:
        entity = Entity(
            project_id=project.id,
            entity_type=draft.entity_type,
            name=draft.name,
            normalized_name=draft.normalized_name,
            identity_key=draft.ref,
            qualified_name=draft.qualified_name,
            description=draft.description,
            source_file_id=record.id,
            start_line=draft.span.start_line if draft.span else None,
            end_line=draft.span.end_line if draft.span else None,
            confidence=draft.confidence,
            verification_status=draft.verification_status or VerificationStatus.CONFIRMED,
            metadata=draft.metadata,
        )
        return self.repos.entities.upsert(entity)

    def _persist_relationship(
        self,
        project: Project,
        run: AnalysisRun,
        record: FileRecord,
        draft: RelationshipDraft,
        ref_to_id: dict[str, str],
        outcome: FileAnalysisOutcome,
    ) -> None:
        source_id = self._resolve_ref(project.id, draft.source_ref, ref_to_id)
        target_id = self._resolve_ref(project.id, draft.target_ref, ref_to_id)

        if source_id is None or target_id is None:
            missing = draft.source_ref if source_id is None else draft.target_ref
            # A dangling ref is an analyzer bug, not user data being odd — record
            # it so it surfaces instead of silently dropping an edge.
            self._record_error(
                project.id,
                run.id,
                record.id,
                analyzer="pipeline",
                code="unresolved_entity_ref",
                message=f"relación descartada: no existe la entidad {missing!r}",
                severity=Severity.WARNING,
                detail={
                    "relation_type": draft.relation_type.value,
                    "source_ref": draft.source_ref,
                    "target_ref": draft.target_ref,
                },
            )
            outcome.warnings += 1
            return

        relationship = Relationship(
            project_id=project.id,
            source_entity_id=source_id,
            relation_type=draft.relation_type,
            target_entity_id=target_id,
            identity_key=relationship_identity_key(
                source_id, draft.relation_type, target_id, record.id
            ),
            source_file_id=record.id,
            start_line=draft.span.start_line if draft.span else None,
            end_line=draft.span.end_line if draft.span else None,
            evidence_snippet=draft.evidence_snippet or None,
            confidence=draft.confidence,
            status=draft.status or VerificationStatus.CONFIRMED,
            analyzer=self._analyzer_label(outcome),
            metadata=draft.metadata,
        )
        stored = self.repos.relationships.upsert(relationship)
        if stored.id == relationship.id:
            outcome.relationships_created += 1

        self._add_evidence(
            project,
            run,
            record,
            relationship_id=stored.id,
            span=draft.span,
            snippet=draft.evidence_snippet,
            original_name=None,
            analyzer=relationship.analyzer,
            confidence=draft.confidence,
            status=draft.status or VerificationStatus.CONFIRMED,
        )

    def _resolve_ref(
        self, project_id: str, ref: str, ref_to_id: dict[str, str]
    ) -> str | None:
        """Map an identity key to an entity id, consulting the database if needed.

        Relationships may point at entities another file defined — an APEX item
        mapping to a column declared in a different script — so a miss in the
        local map is not an error until the database also comes up empty.
        """
        if ref in ref_to_id:
            return ref_to_id[ref]
        existing = self.repos.entities.get_by_identity(project_id, ref)
        if existing is None:
            return None
        ref_to_id[ref] = existing.id
        return existing.id

    def _ensure_file_entity(
        self, project: Project, record: FileRecord
    ) -> tuple[Entity, bool]:
        identity = entity_identity_key(
            EntityType.FILE,
            normalize_name(record.relative_path, EntityType.FILE),
        )
        entity = Entity(
            project_id=project.id,
            entity_type=EntityType.FILE,
            name=record.relative_path,
            normalized_name=normalize_name(record.relative_path, EntityType.FILE),
            identity_key=identity,
            source_file_id=record.id,
            confidence=CONFIRMED,
            verification_status=VerificationStatus.CONFIRMED,
            metadata={
                "extension": record.extension,
                "detected_type": record.detected_type,
                "size_bytes": record.size_bytes,
            },
        )
        return self.repos.entities.upsert(entity)

    def _add_evidence(
        self,
        project: Project,
        run: AnalysisRun,
        record: FileRecord,
        *,
        entity_id: str | None = None,
        relationship_id: str | None = None,
        span: object | None = None,
        snippet: str = "",
        original_name: str | None = None,
        analyzer: str = "",
        confidence: float = CONFIRMED,
        status: VerificationStatus = VerificationStatus.CONFIRMED,
    ) -> None:
        start = getattr(span, "start_line", None)
        end = getattr(span, "end_line", None)
        self.repos.evidence.add(
            Evidence(
                project_id=project.id,
                entity_id=entity_id,
                relationship_id=relationship_id,
                file_id=record.id,
                start_line=start,
                end_line=end,
                snippet=snippet or "",
                original_name=original_name,
                analyzer=analyzer,
                confidence=confidence,
                status=status,
                analysis_run_id=run.id,
            )
        )

    @staticmethod
    def _analyzer_label(outcome: FileAnalysisOutcome) -> str:
        return outcome.analyzers[-1] if outcome.analyzers else "pipeline"

    # -- housekeeping -------------------------------------------------------

    def _forget_file_claims(self, file_id: str) -> None:
        """Drop the relationships and evidence a file used to provide.

        Entities are deliberately left alone: they are re-asserted by identity
        key moments later, which keeps their ids stable. Whatever the new content
        no longer supports is collected afterwards by
        :meth:`EntityRepository.delete_orphans_of_file`.
        """
        # Relationships first, so their evidence cascades rather than lingering.
        self.repos.relationships.delete_by_file(file_id)
        self.repos.evidence.delete_by_file(file_id)

    def _purge_file_knowledge(self, file_id: str) -> None:
        """Forget everything a file proved. Used when the file itself is gone."""
        self._forget_file_claims(file_id)
        self.repos.errors.delete_by_file(file_id)
        self.repos.entities.delete_orphans_of_file(file_id)

    def _finalize_project(self, project: Project) -> None:
        extensions = self.repos.files.count_by_extension(project.id)
        detected: dict[str, int] = {}
        for record in self.repos.files.list_by_project(project.id):
            detected[record.detected_type] = detected.get(record.detected_type, 0) + 1
        if detected:
            self.repos.projects.set_project_type(
                project.id, guess_project_type(detected)
            )
        self.repos.projects.mark_analyzed(project.id)
        _ = extensions  # counted for the UI; the value itself is read on demand

    def _cancel(self, run: AnalysisRun, project: Project) -> AnalysisRun:
        self.repos.runs.finish(
            run, AnalysisRunStatus.CANCELLED, message="Cancelado por el usuario"
        )
        self.repos.projects.set_status(project.id, ProjectStatus.READY)
        self.repos.connection.commit()
        return run

    def _record_error(
        self,
        project_id: str,
        run_id: str | None,
        file_id: str | None,
        *,
        analyzer: str,
        code: str,
        message: str,
        severity: Severity = Severity.ERROR,
        detail: dict | None = None,
    ) -> None:
        self.repos.errors.add(
            AnalysisError(
                project_id=project_id,
                analysis_run_id=run_id,
                file_id=file_id,
                analyzer=analyzer,
                severity=severity,
                code=code,
                message=message,
                detail=detail or {},
            )
        )


def _cancelled(token: CancellationToken | None) -> bool:
    return token is not None and token.is_cancelled


def _progress_emitter(
    callback: ProgressCallback | None, project_id: str, run_id: str
) -> Callable[..., None]:
    def emit(phase: str, current: int, total: int, message: str) -> None:
        if callback is None:
            return
        callback(
            ProgressEvent(
                project_id=project_id,
                run_id=run_id,
                phase=phase,
                current=current,
                total=total,
                message=message,
            )
        )

    return emit
