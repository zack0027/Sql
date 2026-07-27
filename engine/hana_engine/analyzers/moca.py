"""Blue Yonder / JDA MOCA analyzer.

A MOCA command file is a pipeline: segments joined by ``|``, where each segment
is either a native command, a bracketed SQL block, or a ``publish data`` that
hands named values to the next segment.

Nothing is sent anywhere. The MOCA commands found here are never executed and no
connection to a MOCA server is ever opened.

The useful knowledge in a pipeline is the *flow of variables*: which segment
publishes ``@numctl`` and which ones consume it. That is what this analyzer
recovers, along with the tables touched by any embedded SQL.
"""

from __future__ import annotations

import re

from ..domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    Analyzer,
    AnalyzerMessage,
    EntityDraft,
    RelationshipDraft,
)
from ..domain.confidence import CONFIRMED, STRONG_INFERENCE
from ..domain.types import EntityType, RelationType, Severity, VerificationStatus
from .sqltext import blank_noise, cte_names, find_statements, table_references

#: `@variable`. `@?` is the error-status marker, not a name, and `@@` is a
#: system variable prefix in some dialects.
_VARIABLE = re.compile(r"@{1,2}([A-Za-z_][A-Za-z0-9_]*)")

#: `catch(@?)` and friends.
_CATCH = re.compile(r"\bcatch\s*\(\s*@\?\s*\)", re.IGNORECASE)

#: `publish data where a = @x and b = @y` — the names on the left are published.
_PUBLISH = re.compile(r"\bpublish\s+data\b(.*)", re.IGNORECASE | re.DOTALL)
_ASSIGNMENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*@?([A-Za-z_][A-Za-z0-9_]*)?")

#: A command name is the leading verb sequence of a segment.
_COMMAND_NAME = re.compile(r"^\s*([a-zA-Z][a-zA-Z0-9_]*(?:\s+[a-zA-Z][a-zA-Z0-9_]*)*)")


class MocaAnalyzer(Analyzer):
    """Extracts MOCA commands, their variables and any embedded SQL."""

    name = "moca"
    supported_extensions = (".mcmd", ".moca", ".mcom")
    priority = 55

    def can_analyze(self, file_path: str, content: str) -> bool:
        if super().can_analyze(file_path, content):
            return True
        # A .txt holding a pipeline is still MOCA. Require two signals so an
        # ordinary document with an email address in it does not qualify.
        lowered = file_path.lower()
        if not lowered.endswith(".txt"):
            return False
        return "|" in content and _VARIABLE.search(content) is not None

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        result = AnalysisResult()
        cleaned = blank_noise(context.content)

        segments = _split_pipeline(cleaned)
        variables: dict[str, EntityDraft] = {}
        # variable -> the command that published it, and the ones that read it.
        publishers: dict[str, EntityDraft] = {}
        consumers: dict[str, list[EntityDraft]] = {}

        for ordinal, (start, end) in enumerate(segments, start=1):
            text = cleaned[start:end]
            if not text.strip():
                continue
            command = self._command_entity(context, text, ordinal, start, end)
            result.entities.append(command)

            self._collect_variables(
                context, text, start, command, variables, consumers, result
            )
            self._collect_publications(
                context, text, start, command, publishers, variables, result
            )
            self._collect_sql(context, text, start, command, result)

            if _CATCH.search(text):
                command.metadata["handles_errors"] = True

        self._link_flow(publishers, consumers, result)
        result.metadata["moca_segments"] = len(segments)
        return result

    # -- segments -----------------------------------------------------------

    def _command_entity(
        self,
        context: AnalysisContext,
        text: str,
        ordinal: int,
        start: int,
        end: int,
    ) -> EntityDraft:
        match = _COMMAND_NAME.match(text.lstrip("[ \n"))
        label = match.group(1).strip() if match else f"segmento#{ordinal}"
        span = context.span_of_offsets(start, end)
        return EntityDraft(
            EntityType.MOCA_COMMAND,
            f"{label} #{ordinal}",
            span=span,
            container=context.relative_path,
            description=f"Segmento {ordinal} del pipeline MOCA",
            evidence_snippet=context.snippet(span),
            metadata={"position": ordinal},
        )

    def _collect_variables(
        self,
        context: AnalysisContext,
        text: str,
        base: int,
        command: EntityDraft,
        variables: dict[str, EntityDraft],
        consumers: dict[str, list[EntityDraft]],
        result: AnalysisResult,
    ) -> None:
        for match in _VARIABLE.finditer(text):
            name = match.group(1)
            span = context.span_of_offsets(base + match.start(), base + match.end())
            key = name.upper()
            consumers.setdefault(key, []).append(command)
            if key not in variables:
                draft = EntityDraft(
                    EntityType.MOCA_VARIABLE,
                    name,
                    span=span,
                    container=context.relative_path,
                    evidence_snippet=context.snippet(span),
                )
                variables[key] = draft
                result.entities.append(draft)

            result.relationships.append(
                RelationshipDraft(
                    source_ref=command.ref,
                    relation_type=RelationType.MOCA_COMMAND_USES_VARIABLE,
                    target_ref=variables[key].ref,
                    span=span,
                    evidence_snippet=context.snippet(span),
                    confidence=CONFIRMED,
                )
            )

    def _collect_publications(
        self,
        context: AnalysisContext,
        text: str,
        base: int,
        command: EntityDraft,
        publishers: dict[str, EntityDraft],
        variables: dict[str, EntityDraft],
        result: AnalysisResult,
    ) -> None:
        publish = _PUBLISH.search(text)
        if publish is None:
            return
        command.metadata["publishes"] = True

        for match in _ASSIGNMENT.finditer(publish.group(1)):
            name = match.group(1)
            key = name.upper()
            offset = base + publish.start(1) + match.start(1)
            span = context.span_of_offsets(offset, offset + len(name))
            if key not in variables:
                draft = EntityDraft(
                    EntityType.MOCA_VARIABLE,
                    name,
                    span=span,
                    container=context.relative_path,
                    evidence_snippet=context.snippet(span),
                )
                variables[key] = draft
                result.entities.append(draft)
            publishers.setdefault(key, command)

    def _collect_sql(
        self,
        context: AnalysisContext,
        text: str,
        base: int,
        command: EntityDraft,
        result: AnalysisResult,
    ) -> None:
        excluded = cte_names(text)
        for statement in find_statements(text):
            for reference in table_references(statement, excluded):
                offset = base + reference.offset
                span = context.span_of_offsets(offset, offset)
                table = EntityDraft(
                    EntityType.ORACLE_TABLE,
                    reference.name,
                    span=span,
                    schema=reference.schema,
                    evidence_snippet=context.snippet(span),
                )
                result.entities.append(table)
                result.relationships.append(
                    RelationshipDraft(
                        source_ref=command.ref,
                        relation_type=(
                            RelationType.QUERY_WRITES_TABLE
                            if reference.written
                            else RelationType.QUERY_READS_TABLE
                        ),
                        span=span,
                        target_ref=table.ref,
                        evidence_snippet=context.snippet(span),
                        confidence=CONFIRMED,
                    )
                )

    def _link_flow(
        self,
        publishers: dict[str, EntityDraft],
        consumers: dict[str, list[EntityDraft]],
        result: AnalysisResult,
    ) -> None:
        """Connect the command that publishes a value to the ones that read it.

        The edge runs between *commands*, not between variables: a variable is a
        single named thing in the file, so a variable-to-variable edge would be a
        self-loop that says nothing. What carries meaning is "segment 3 depends
        on segment 1, because segment 1 published ``@numctl``".

        Marked as inferred: MOCA resolves names at run time through the stack, so
        matching by name is a very good guess, not a proof.
        """
        for key, publisher in publishers.items():
            downstream = [
                command
                for command in consumers.get(key, [])
                if command.ref != publisher.ref
            ]
            if not downstream:
                result.warnings.append(
                    AnalyzerMessage(
                        code="published_but_unused",
                        message=f"@{key} se publica pero ningún comando lo consume",
                        severity=Severity.WARNING,
                        detail={"variable": key},
                    )
                )
                continue

            for consumer in downstream:
                result.relationships.append(
                    RelationshipDraft(
                        source_ref=consumer.ref,
                        relation_type=RelationType.ENTITY_DEPENDS_ON_ENTITY,
                        target_ref=publisher.ref,
                        span=consumer.span,
                        evidence_snippet=f"consume @{key}",
                        confidence=STRONG_INFERENCE,
                        status=VerificationStatus.INFERRED,
                        metadata={"variable": key},
                    )
                )


def _split_pipeline(text: str) -> list[tuple[int, int]]:
    """Split on ``|`` at the top level, ignoring brackets and parentheses.

    A ``|`` inside ``[...]`` belongs to the SQL or the expression in that block,
    not to the pipeline.
    """
    segments: list[tuple[int, int]] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "[(":
            depth += 1
        elif char in "])":
            depth = max(0, depth - 1)
        elif char == "|" and depth == 0:
            segments.append((start, index))
            start = index + 1
    segments.append((start, len(text)))
    return segments
