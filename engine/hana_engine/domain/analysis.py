"""The analyzer plugin contract.

Analyzers never touch SQLite and never invent identifiers. They read a file and
emit *drafts*: statements of what they believe, each carrying the evidence that
justifies it. The pipeline resolves drafts against the knowledge base,
deduplicates them and assigns IDs.

A draft's :attr:`EntityDraft.ref` is its identity key, so an analyzer can refer
to an entity it emitted — or to one another analyzer emitted — without knowing
any database state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .confidence import CONFIRMED, clamp, default_status_for
from .naming import entity_identity_key, normalize_name
from .types import EntityType, RelationType, Severity, VerificationStatus


@dataclass(frozen=True)
class SourceSpan:
    """A range of lines in a file, 1-indexed and inclusive."""

    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        if self.start_line < 1:
            raise ValueError(f"start_line must be >= 1, got {self.start_line}")
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line ({self.end_line}) precedes start_line ({self.start_line})"
            )


@dataclass
class EntityDraft:
    """An entity an analyzer believes exists, with its provenance."""

    entity_type: EntityType
    name: str
    span: SourceSpan | None = None
    schema: str | None = None
    container: str | None = None
    qualified_name: str | None = None
    description: str | None = None
    confidence: float = CONFIRMED
    verification_status: VerificationStatus | None = None
    evidence_snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = clamp(self.confidence)
        if self.verification_status is None:
            self.verification_status = default_status_for(self.confidence)
        if (
            self.verification_status is VerificationStatus.CONFIRMED
            and self.confidence < CONFIRMED
        ):
            raise ValueError(
                "an entity cannot be 'confirmed' with confidence "
                f"{self.confidence}: {self.entity_type}/{self.name}"
            )

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name, self.entity_type)

    @property
    def ref(self) -> str:
        """Identity key — stable across analyzers and across runs."""
        return entity_identity_key(
            self.entity_type,
            self.normalized_name,
            schema=self.schema,
            container=self.container,
        )


@dataclass
class RelationshipDraft:
    """A claim connecting two entity refs, with the source text that supports it."""

    source_ref: str
    relation_type: RelationType
    target_ref: str
    span: SourceSpan | None = None
    evidence_snippet: str = ""
    confidence: float = CONFIRMED
    status: VerificationStatus | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = clamp(self.confidence)
        if self.status is None:
            self.status = default_status_for(self.confidence)
        if self.status is VerificationStatus.CONFIRMED and self.confidence < CONFIRMED:
            raise ValueError(
                "a relationship cannot be 'confirmed' with confidence "
                f"{self.confidence}: {self.source_ref} -> {self.target_ref}"
            )


@dataclass
class AnalyzerMessage:
    """A warning or a non-fatal error raised while reading a file."""

    code: str
    message: str
    severity: Severity = Severity.WARNING
    span: SourceSpan | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Everything one analyzer learned from one file."""

    entities: list[EntityDraft] = field(default_factory=list)
    relationships: list[RelationshipDraft] = field(default_factory=list)
    warnings: list[AnalyzerMessage] = field(default_factory=list)
    errors: list[AnalyzerMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def extend(self, other: AnalysisResult) -> None:
        self.entities.extend(other.entities)
        self.relationships.extend(other.relationships)
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)
        self.metadata.update(other.metadata)

    @property
    def is_empty(self) -> bool:
        return not (self.entities or self.relationships)


@dataclass
class AnalysisContext:
    """Everything an analyzer is allowed to see.

    Deliberately narrow: an analyzer gets one file's text and its identity. It
    has no database handle, no network, and no way to reach other files. That is
    what makes analyzers safe to run over untrusted project content.
    """

    project_id: str
    file_id: str
    relative_path: str
    absolute_path: str
    extension: str
    detected_type: str
    content: str
    analysis_run_id: str | None = None

    _lines: Sequence[str] | None = field(default=None, init=False, repr=False)

    @property
    def lines(self) -> Sequence[str]:
        if self._lines is None:
            self._lines = self.content.splitlines()
        return self._lines

    def line_of_offset(self, offset: int) -> int:
        """Return the 1-indexed line number containing a character offset."""
        return self.content.count("\n", 0, max(0, offset)) + 1

    def span_of_offsets(self, start: int, end: int) -> SourceSpan:
        return SourceSpan(self.line_of_offset(start), self.line_of_offset(max(start, end)))

    def snippet(self, span: SourceSpan | None, *, max_chars: int = 600) -> str:
        """Return the source text for a span, truncated for storage."""
        if span is None:
            return ""
        selected = self.lines[span.start_line - 1 : span.end_line]
        text = "\n".join(selected).strip()
        if len(text) > max_chars:
            return text[: max_chars - 1] + "…"
        return text


class Analyzer(ABC):
    """Base class for every analyzer plugin.

    Implementations must be pure with respect to the outside world: no file
    execution, no network, no evaluation of expressions found in the source.
    """

    #: Stable identifier recorded on every entity, relationship and evidence row.
    name: str = "analyzer"

    #: Lower-case extensions including the dot, e.g. ``[".sql", ".pks"]``.
    supported_extensions: Sequence[str] = ()

    #: Higher runs first; lets a specific analyzer see a file before a generic one.
    priority: int = 0

    #: Bump when this analyzer learns to extract something new. Files analysed by
    #: an older version are re-read even though their content has not changed.
    version: int = 1

    def can_analyze(self, file_path: str, content: str) -> bool:
        """Return True when this analyzer should read the file.

        The default implementation matches on extension. Override to sniff
        content — a ``.txt`` holding a MOCA pipeline, for instance.
        """
        lowered = file_path.lower()
        return any(lowered.endswith(ext) for ext in self.supported_extensions)

    @abstractmethod
    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        """Extract entities and relationships from one file."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Analyzer {self.name}>"


class AnalyzerRegistry:
    """The plugin table.

    Analyzers register here at import time. The pipeline asks the registry which
    analyzers apply to a file; it never hard-codes a list.
    """

    def __init__(self) -> None:
        self._analyzers: list[Analyzer] = []

    def register(self, analyzer: Analyzer) -> Analyzer:
        if any(existing.name == analyzer.name for existing in self._analyzers):
            raise ValueError(f"analyzer already registered: {analyzer.name}")
        self._analyzers.append(analyzer)
        self._analyzers.sort(key=lambda a: (-a.priority, a.name))
        return analyzer

    def unregister(self, name: str) -> None:
        self._analyzers = [a for a in self._analyzers if a.name != name]

    def all(self) -> Sequence[Analyzer]:
        return tuple(self._analyzers)

    def fingerprint(self) -> str:
        """Identify this set of analyzers together with their capabilities.

        Stored with every file's knowledge so the pipeline can recognise that a
        file was analysed by an *older* suite. It includes each analyzer's
        ``version``, which is what an author bumps after teaching one something
        new — without it, a capability added today would never reach the files
        analysed yesterday, and the gap would appear as an unexplained blank.
        """
        parts = [
            f"{analyzer.name}@{getattr(analyzer, 'version', 1)}"
            for analyzer in self._analyzers
        ]
        return ";".join(sorted(parts)) or "empty"

    def for_file(self, file_path: str, content: str) -> Iterable[Analyzer]:
        """Yield the analyzers that accept this file, highest priority first."""
        for analyzer in self._analyzers:
            try:
                if analyzer.can_analyze(file_path, content):
                    yield analyzer
            except Exception:  # noqa: BLE001 - a broken plugin must not stop the rest
                continue

    def __len__(self) -> int:
        return len(self._analyzers)
