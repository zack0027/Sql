"""Incremental change detection.

Compares what the scanner just saw on disk against what the knowledge base
remembers, and classifies every path as added, modified, unchanged or deleted.

Detection is by **content hash, never by mtime**. Copying a project, checking it
out again or touching a file all change timestamps without changing content;
re-analysing thousands of files because of that would make incremental analysis
worthless.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from ..domain.models import FileRecord, ScannedFile
from ..domain.types import ChangeKind


@dataclass(frozen=True)
class FileChange:
    """One path's verdict."""

    kind: ChangeKind
    relative_path: str
    scanned: ScannedFile | None = None
    record: FileRecord | None = None

    @property
    def needs_analysis(self) -> bool:
        return self.kind in (ChangeKind.ADDED, ChangeKind.MODIFIED)


@dataclass
class ChangeSet:
    """The full comparison, grouped by verdict."""

    added: list[FileChange] = field(default_factory=list)
    modified: list[FileChange] = field(default_factory=list)
    unchanged: list[FileChange] = field(default_factory=list)
    deleted: list[FileChange] = field(default_factory=list)

    def all_changes(self) -> Iterable[FileChange]:
        yield from self.added
        yield from self.modified
        yield from self.unchanged
        yield from self.deleted

    def to_analyze(self) -> list[FileChange]:
        return self.added + self.modified

    @property
    def counts(self) -> dict[str, int]:
        return {
            ChangeKind.ADDED.value: len(self.added),
            ChangeKind.MODIFIED.value: len(self.modified),
            ChangeKind.UNCHANGED.value: len(self.unchanged),
            ChangeKind.DELETED.value: len(self.deleted),
        }

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted)


def _has_changed(record: FileRecord, scanned: ScannedFile) -> bool:
    if record.content_hash != scanned.content_hash:
        return True
    if record.content_hash is None:
        # Both sides unhashed: the file was skipped. It still counts as changed
        # if the reason or the size moved — a file that grew past the size limit,
        # or shrank back under it, is genuinely different to the engine.
        if record.skip_reason != scanned.skip_reason:
            return True
        if record.size_bytes != scanned.size_bytes:
            return True
    return False


def diff(
    scanned_files: Sequence[ScannedFile],
    known: Mapping[str, FileRecord],
) -> ChangeSet:
    """Classify a scan against the known state of a project.

    ``known`` must include soft-deleted files: a path that comes back reuses its
    original row, so its version history survives the round trip.
    """
    changes = ChangeSet()
    seen_paths: set[str] = set()

    for scanned in scanned_files:
        seen_paths.add(scanned.relative_path)
        record = known.get(scanned.relative_path)

        if record is None:
            changes.added.append(
                FileChange(ChangeKind.ADDED, scanned.relative_path, scanned=scanned)
            )
            continue

        if record.is_deleted:
            # Resurrected: treated as added so it gets re-analysed, but carrying
            # the existing record so the same row (and its history) is reused.
            changes.added.append(
                FileChange(
                    ChangeKind.ADDED,
                    scanned.relative_path,
                    scanned=scanned,
                    record=record,
                )
            )
            continue

        kind = ChangeKind.MODIFIED if _has_changed(record, scanned) else ChangeKind.UNCHANGED
        target = changes.modified if kind is ChangeKind.MODIFIED else changes.unchanged
        target.append(
            FileChange(kind, scanned.relative_path, scanned=scanned, record=record)
        )

    for path, record in known.items():
        if path in seen_paths or record.is_deleted:
            continue
        changes.deleted.append(
            FileChange(ChangeKind.DELETED, path, record=record)
        )

    return changes
