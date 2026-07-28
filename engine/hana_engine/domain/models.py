"""Domain records.

These dataclasses are the only shape in which knowledge moves through the
engine. Repositories translate them to and from SQLite rows; the IPC layer
translates them to and from JSON. Nothing else is allowed to invent its own
shape for a table row.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .confidence import CONFIRMED, clamp
from .ids import new_ulid
from .types import (
    AnalysisRunStatus,
    ChangeKind,
    EntityType,
    FileAnalysisStatus,
    ProjectStatus,
    RelationType,
    Severity,
    SkipReason,
    VerificationStatus,
)


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


@dataclass
class Project:
    """A root folder that HANA has been pointed at."""

    id: str = field(default_factory=new_ulid)
    name: str = ""
    root_path: str = ""
    project_type: str = "unknown"
    status: ProjectStatus = ProjectStatus.CREATED
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    last_analysis_at: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Project:
        return cls(
            id=row["id"],
            name=row["name"],
            root_path=row["root_path"],
            project_type=row["project_type"],
            status=ProjectStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_analysis_at=row["last_analysis_at"],
            settings=_loads(row["settings_json"]),
        )


@dataclass
class FileRecord:
    """A file inside a project, as the knowledge base remembers it."""

    id: str = field(default_factory=new_ulid)
    project_id: str = ""
    relative_path: str = ""
    absolute_path: str = ""
    extension: str = ""
    detected_type: str = "unknown"
    size_bytes: int = 0
    content_hash: str | None = None
    modified_at: str | None = None
    analysis_status: FileAnalysisStatus = FileAnalysisStatus.PENDING
    analyzed_hash: str | None = None
    #: Version of the analyzer suite that produced this file's knowledge. When it
    #: stops matching the running suite the file is re-read, even though not one
    #: of its bytes has moved.
    analyzed_by: str | None = None
    last_analyzed_at: str | None = None
    is_deleted: bool = False
    skip_reason: SkipReason | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> FileRecord:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            relative_path=row["relative_path"],
            absolute_path=row["absolute_path"],
            extension=row["extension"],
            detected_type=row["detected_type"],
            size_bytes=row["size_bytes"],
            content_hash=row["content_hash"],
            modified_at=row["modified_at"],
            analysis_status=FileAnalysisStatus(row["analysis_status"]),
            analyzed_hash=row["analyzed_hash"],
            analyzed_by=row["analyzed_by"] if "analyzed_by" in row.keys() else None,
            last_analyzed_at=row["last_analyzed_at"],
            is_deleted=bool(row["is_deleted"]),
            skip_reason=SkipReason(row["skip_reason"]) if row["skip_reason"] else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class FileVersion:
    """One observed state of a file. Never updated, only appended."""

    id: str = field(default_factory=new_ulid)
    file_id: str = ""
    project_id: str = ""
    content_hash: str = ""
    size_bytes: int = 0
    modified_at: str | None = None
    change_kind: ChangeKind = ChangeKind.ADDED
    analysis_run_id: str | None = None
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> FileVersion:
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            project_id=row["project_id"],
            content_hash=row["content_hash"],
            size_bytes=row["size_bytes"],
            modified_at=row["modified_at"],
            change_kind=ChangeKind(row["change_kind"]),
            analysis_run_id=row["analysis_run_id"],
            created_at=row["created_at"],
        )


@dataclass
class Entity:
    """Something identifiable that an analyzer found in a file."""

    id: str = field(default_factory=new_ulid)
    project_id: str = ""
    entity_type: EntityType = EntityType.UNKNOWN
    name: str = ""
    normalized_name: str = ""
    identity_key: str = ""
    qualified_name: str | None = None
    description: str | None = None
    source_file_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    confidence: float = CONFIRMED
    verification_status: VerificationStatus = VerificationStatus.CONFIRMED
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.confidence = clamp(self.confidence)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Entity:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            entity_type=EntityType(row["entity_type"]),
            name=row["name"],
            normalized_name=row["normalized_name"],
            identity_key=row["identity_key"],
            qualified_name=row["qualified_name"],
            description=row["description"],
            source_file_id=row["source_file_id"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            confidence=row["confidence"],
            verification_status=VerificationStatus(row["verification_status"]),
            metadata=_loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class Relationship:
    """A directed, sourced claim connecting two entities."""

    id: str = field(default_factory=new_ulid)
    project_id: str = ""
    source_entity_id: str = ""
    relation_type: RelationType = RelationType.ENTITY_MENTIONS_ENTITY
    target_entity_id: str = ""
    identity_key: str = ""
    source_file_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    evidence_snippet: str | None = None
    confidence: float = CONFIRMED
    status: VerificationStatus = VerificationStatus.CONFIRMED
    analyzer: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.confidence = clamp(self.confidence)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Relationship:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            source_entity_id=row["source_entity_id"],
            relation_type=RelationType(row["relation_type"]),
            target_entity_id=row["target_entity_id"],
            identity_key=row["identity_key"],
            source_file_id=row["source_file_id"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            evidence_snippet=row["evidence_snippet"],
            confidence=row["confidence"],
            status=VerificationStatus(row["status"]),
            analyzer=row["analyzer"],
            metadata=_loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class Evidence:
    """The receipt for a fact: file, lines, snippet, analyzer, confidence.

    Exactly one of ``entity_id`` / ``relationship_id`` is set. ``original_name``
    keeps the spelling as it appeared in the source, which is what lets a
    deduplicated entity still show ``uc_insp_ent`` where the file said so.
    """

    id: str = field(default_factory=new_ulid)
    project_id: str = ""
    entity_id: str | None = None
    relationship_id: str | None = None
    file_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    snippet: str = ""
    original_name: str | None = None
    analyzer: str = ""
    confidence: float = CONFIRMED
    status: VerificationStatus = VerificationStatus.CONFIRMED
    analysis_run_id: str | None = None
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.confidence = clamp(self.confidence)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Evidence:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            entity_id=row["entity_id"],
            relationship_id=row["relationship_id"],
            file_id=row["file_id"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            snippet=row["snippet"],
            original_name=row["original_name"],
            analyzer=row["analyzer"],
            confidence=row["confidence"],
            status=VerificationStatus(row["status"]),
            analysis_run_id=row["analysis_run_id"],
            created_at=row["created_at"],
        )


@dataclass
class AnalysisRun:
    """One pass of the pipeline over a project."""

    id: str = field(default_factory=new_ulid)
    project_id: str = ""
    status: AnalysisRunStatus = AnalysisRunStatus.RUNNING
    trigger: str = "manual"
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    files_scanned: int = 0
    files_added: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    files_unchanged: int = 0
    files_analyzed: int = 0
    files_skipped: int = 0
    #: Files re-read because a newer analyzer can learn more from them, even
    #: though their content never changed. Not persisted: it describes this run's
    #: reason for working, not a property of the project.
    files_reanalyzed: int = 0
    entities_created: int = 0
    relationships_created: int = 0
    error_count: int = 0
    message: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> AnalysisRun:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            status=AnalysisRunStatus(row["status"]),
            trigger=row["trigger"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            files_scanned=row["files_scanned"],
            files_added=row["files_added"],
            files_modified=row["files_modified"],
            files_deleted=row["files_deleted"],
            files_unchanged=row["files_unchanged"],
            files_analyzed=row["files_analyzed"],
            files_skipped=row["files_skipped"],
            entities_created=row["entities_created"],
            relationships_created=row["relationships_created"],
            error_count=row["error_count"],
            message=row["message"],
        )


@dataclass
class AnalysisError:
    """A failure that did not stop the run.

    Analyzer crashes land here instead of aborting the project, which is the
    difference between "one JRXML is malformed" and "the analysis produced
    nothing".
    """

    id: str = field(default_factory=new_ulid)
    project_id: str = ""
    analysis_run_id: str | None = None
    file_id: str | None = None
    analyzer: str = ""
    severity: Severity = Severity.ERROR
    code: str = ""
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> AnalysisError:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            analysis_run_id=row["analysis_run_id"],
            file_id=row["file_id"],
            analyzer=row["analyzer"],
            severity=Severity(row["severity"]),
            code=row["code"],
            message=row["message"],
            detail=_loads(row["detail_json"]),
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class ScannedFile:
    """A file as the scanner saw it on disk, before it meets the database.

    This is the contract between the Rust scanner and the Python engine. The
    Python scanner in ``indexing/scanner.py`` produces the same shape, and the
    Rust crate serialises to exactly these field names.
    """

    relative_path: str
    absolute_path: str
    extension: str
    size_bytes: int
    content_hash: str | None
    modified_at: str | None
    detected_type: str = "unknown"
    skip_reason: SkipReason | None = None

    @property
    def is_skipped(self) -> bool:
        return self.skip_reason is not None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScannedFile:
        reason = data.get("skip_reason")
        return cls(
            relative_path=data["relative_path"],
            absolute_path=data["absolute_path"],
            extension=data.get("extension", ""),
            size_bytes=int(data.get("size_bytes", 0)),
            content_hash=data.get("content_hash"),
            modified_at=data.get("modified_at"),
            detected_type=data.get("detected_type", "unknown"),
            skip_reason=SkipReason(reason) if reason else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "absolute_path": self.absolute_path,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "content_hash": self.content_hash,
            "modified_at": self.modified_at,
            "detected_type": self.detected_type,
            "skip_reason": self.skip_reason.value if self.skip_reason else None,
        }
