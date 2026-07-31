"""Oracle and MOCA log analyzer.

Reads a log and records the errors it contains as entities, linked to the code
they name. This is what makes HANA a knowledge engine rather than a code index:
"ORA-01400 on UC_INSP_ENT.NUMCTL happened eleven times, and here is what fixed
it" is knowledge nobody can get from reading the source.

**Recurrence comes for free.** An error's identity is its code plus the object
it names, so the same failure in ten logs is one entity with ten pieces of
evidence. Counting them is counting the evidence rows, and the pipeline already
writes one per sighting.

**What it will and will not link.** A log names objects but rarely says what
kind of thing they are, and inventing a type would put a false node in the
graph. So a reference is only linked when the *error itself* establishes the
kind:

* ``ORA-06512: at "WMS.PKG_INSPECCION", line 42`` — a PL/SQL stack line, so
  that name is a package or a standalone routine. Oracle's own structure says
  so.
* ``("WMS"."UC_INSP_ENT"."NUMCTL")`` in ORA-01400 or ORA-12899 — three parts,
  so schema, table, column.

Everything else the log mentions is kept on the error as text, where it informs
the reader without pretending to be an edge.

Objects named this way are recorded at :data:`MENTION` confidence. A log proves
Oracle knows the object exists; it does not prove the project's code contains
it. Where the code *did* declare it, the identity keys match and the two merge
into one entity — and where they do not, an object that only a log knows about
is itself worth seeing.

Nothing here is executed, and no log is modified.
"""

from __future__ import annotations

import re

from ..domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    Analyzer,
    EntityDraft,
    RelationshipDraft,
)
from ..domain.confidence import CONFIRMED, MENTION
from ..domain.types import EntityType, RelationType

#: An Oracle-family error code: ORA-01400, PLS-00201, TNS-12541, IMP-00013.
#: MOCA logs its own failures in the same shape, so one pattern covers both.
_ERROR_CODE = re.compile(r"\b([A-Z]{2,5}-\d{4,5})\b")

#: The message that follows a code on the same line.
_CODED_LINE = re.compile(r"\b([A-Z]{2,5}-\d{4,5})\s*:\s*(.*)")

#: `at "WMS.PKG_INSPECCION", line 42` — a PL/SQL stack frame. The quoted name is
#: a package or a standalone routine; Oracle puts nothing else there.
_STACK_FRAME = re.compile(
    r'\bat\s+"([A-Za-z_][\w$#]*)\.([A-Za-z_][\w$#]*)"(?:\s*,\s*line\s+(\d+))?',
    re.IGNORECASE,
)

#: `("WMS"."UC_INSP_ENT"."NUMCTL")` — three quoted parts: schema, table, column.
_QUOTED_COLUMN = re.compile(
    r'"([A-Za-z_][\w$#]*)"\s*\.\s*"([A-Za-z_][\w$#]*)"\s*\.\s*"([A-Za-z_][\w$#]*)"'
)

#: Codes that carry no information about a specific object. ORA-06512 is the
#: stack frame itself and ORA-06510 its wrapper: recording them as distinct
#: problems would bury the error that actually failed under its own traceback.
_STACK_CODES = frozenset({"ORA-06512", "ORA-06510"})

#: Digits inside a message vary between occurrences of the same problem. The
#: signature keeps the shape and drops the specifics, so ten sightings of one
#: failure are one entity rather than ten.
_VARIABLE = re.compile(r"\d+")

_MAX_MESSAGE = 300


class LogAnalyzer(Analyzer):
    """Extracts runtime errors, and the code they name, from log files."""

    name = "logs"
    supported_extensions = (".log", ".err", ".trc", ".out")
    priority = 40
    version = 1

    def can_analyze(self, file_path: str, content: str) -> bool:
        """Match on extension, or on a log's contents whatever it is called.

        Logs are routinely named ``salida.txt`` or ``20260731`` with no
        extension at all. Requiring a known suffix would miss most real ones,
        and the test — an Oracle-family error code near the start — is specific
        enough that ordinary prose never trips it.
        """
        if super().can_analyze(file_path, content):
            return True
        head = content[:20000]
        return bool(_ERROR_CODE.search(head))

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        result = AnalysisResult()
        seen: set[str] = set()

        for number, line in enumerate(context.lines, start=1):
            match = _CODED_LINE.search(line)
            if match is None:
                continue
            code = match.group(1).upper()
            if code in _STACK_CODES:
                # Still useful: the frame names the routine that raised.
                self._link_stack_frame(context, line, number, seen, result)
                continue

            message = match.group(2).strip()[:_MAX_MESSAGE]
            error = self._record_error(context, code, message, number, result)
            self._link_named_objects(context, line, number, error, result)

        result.metadata["log_errors"] = len(
            [draft for draft in result.entities if draft.entity_type is EntityType.ERROR]
        )
        return result

    # -- errors -------------------------------------------------------------

    def _record_error(
        self,
        context: AnalysisContext,
        code: str,
        message: str,
        line: int,
        result: AnalysisResult,
    ) -> EntityDraft:
        span = _span_of_line(context, line)
        column = _first_column(message)
        draft = EntityDraft(
            EntityType.ERROR,
            code,
            span=span,
            # Two ORA-00942 about different tables are different problems, and
            # the same one recurring is one problem. The container is what makes
            # that distinction, and an unknown object stays separate from a
            # known one rather than collapsing onto it.
            container=column,
            qualified_name=f"{code} · {column}" if column else None,
            description=message or None,
            evidence_snippet=context.snippet(span),
            confidence=CONFIRMED,
            metadata={"code": code, "signature": _signature(message)},
        )
        result.entities.append(draft)
        return draft

    # -- what the error names -----------------------------------------------

    def _link_named_objects(
        self,
        context: AnalysisContext,
        line: str,
        number: int,
        error: EntityDraft,
        result: AnalysisResult,
    ) -> None:
        span = _span_of_line(context, number)
        for match in _QUOTED_COLUMN.finditer(line):
            schema, table, column = (part.upper() for part in match.groups())
            table_draft = EntityDraft(
                EntityType.ORACLE_TABLE,
                table,
                span=span,
                schema=schema,
                qualified_name=f"{schema}.{table}",
                evidence_snippet=context.snippet(span),
                confidence=MENTION,
            )
            column_draft = EntityDraft(
                EntityType.ORACLE_COLUMN,
                column,
                span=span,
                schema=schema,
                container=table,
                qualified_name=f"{table}.{column}",
                evidence_snippet=context.snippet(span),
                confidence=MENTION,
            )
            result.entities.extend([table_draft, column_draft])
            for target in (table_draft, column_draft):
                result.relationships.append(
                    RelationshipDraft(
                        source_ref=error.ref,
                        relation_type=RelationType.ERROR_AFFECTS_ENTITY,
                        target_ref=target.ref,
                        span=span,
                        evidence_snippet=context.snippet(span),
                        # The link is stated by the error message itself.
                        confidence=CONFIRMED,
                    )
                )

    def _link_stack_frame(
        self,
        context: AnalysisContext,
        line: str,
        number: int,
        seen: set[str],
        result: AnalysisResult,
    ) -> None:
        """Attach the routine a PL/SQL stack frame names to the errors above it.

        The frame does not describe a new problem — it says where the previous
        error was raised — so it produces no error entity of its own.
        """
        span = _span_of_line(context, number)
        for match in _STACK_FRAME.finditer(line):
            schema, routine = match.group(1).upper(), match.group(2).upper()
            key = f"{schema}.{routine}"
            if key in seen:
                continue
            seen.add(key)
            package = EntityDraft(
                EntityType.ORACLE_PACKAGE,
                routine,
                span=span,
                schema=schema,
                qualified_name=key,
                evidence_snippet=context.snippet(span),
                confidence=MENTION,
                metadata={"seen_in": "plsql_stack"},
            )
            result.entities.append(package)

            # Every error recorded so far in this file plausibly passed through
            # this frame. Only the most recent one is linked: a stack belongs to
            # the failure immediately above it, and linking all of them would
            # attach unrelated errors to the same routine.
            previous = _last_error(result)
            if previous is not None:
                result.relationships.append(
                    RelationshipDraft(
                        source_ref=previous.ref,
                        relation_type=RelationType.ERROR_AFFECTS_ENTITY,
                        target_ref=package.ref,
                        span=span,
                        evidence_snippet=context.snippet(span),
                        confidence=CONFIRMED,
                        metadata={"from": "plsql_stack"},
                    )
                )


def _span_of_line(context: AnalysisContext, line: int):
    from ..domain.analysis import SourceSpan

    return SourceSpan(line, line)


def _last_error(result: AnalysisResult) -> EntityDraft | None:
    for draft in reversed(result.entities):
        if draft.entity_type is EntityType.ERROR:
            return draft
    return None


def _first_column(message: str) -> str | None:
    """The object an error message names, as ``TABLE.COLUMN`` when it says so."""
    match = _QUOTED_COLUMN.search(message)
    if match is None:
        return None
    _, table, column = (part.upper() for part in match.groups())
    return f"{table}.{column}"


def _signature(message: str) -> str:
    """The message with its varying numbers removed."""
    return _VARIABLE.sub("#", message).strip()
