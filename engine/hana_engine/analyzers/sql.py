"""SQL and PL/SQL analyzer.

Reads a script and reports which tables each statement *reads* and which it
*writes* — the distinction the whole product turns on, because "where is this
table used?" is a different question from "what modifies this table?".

Nothing is executed. The analyzer works entirely on text that has already had
comments and string literals blanked out by :mod:`.sqltext`, so a table named in
a comment can never be mistaken for a reference.

What it deliberately does not do: attribute an unqualified column to a table.
``select numctl from a, b`` gives no honest way to know which table owns
``numctl``, and inventing an answer would put a false edge in the graph. Columns
are only recorded when the source makes the owner explicit — through an alias, a
qualified name, an INSERT column list or an UPDATE SET clause.
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
from ..domain.confidence import CONFIRMED
from ..domain.types import EntityType, RelationType
from .sqltext import (
    IDENTIFIER,
    QUALIFIED,
    Statement,
    blank_noise,
    cte_names,
    find_statements,
    join_conditions,
    qualified_columns,
    split_schema,
    table_references,
    unquote,
)

# --- PL/SQL declarations ----------------------------------------------------

_PACKAGE = re.compile(
    rf"\bpackage\s+(?:body\s+)?({QUALIFIED})", re.IGNORECASE
)
_PROCEDURE = re.compile(rf"\bprocedure\s+({QUALIFIED})", re.IGNORECASE)
_FUNCTION = re.compile(rf"\bfunction\s+({QUALIFIED})", re.IGNORECASE)

#: A qualified call: `pkg.proc(` or `schema.pkg.proc(`. Only qualified calls are
#: reported — a bare `foo(` is far more often a built-in or a local variable.
_QUALIFIED_CALL = re.compile(
    rf"\b({IDENTIFIER})\s*\.\s*({IDENTIFIER})\s*\(", re.IGNORECASE
)

#: Oracle built-ins that appear qualified but are not user procedures.
_BUILTIN_PACKAGES = frozenset(
    {
        "DBMS_OUTPUT", "DBMS_SQL", "DBMS_LOB", "DBMS_UTILITY", "UTL_FILE",
        "UTL_RAW", "APEX_UTIL", "APEX_APPLICATION", "HTP", "OWA_UTIL", "JSON",
    }
)

#: `insert into T (a, b, c)` — the column list.
_INSERT_COLUMNS = re.compile(
    rf"\binsert\s+into\s+({QUALIFIED})\s*\(([^)]*)\)", re.IGNORECASE
)
#: `set a = ..., b = ...` inside an UPDATE.
_SET_CLAUSE = re.compile(r"\bset\b(.*?)(?:\bwhere\b|$)", re.IGNORECASE | re.DOTALL)
_SET_COLUMN = re.compile(rf"({QUALIFIED})\s*=", re.IGNORECASE)


class SqlAnalyzer(Analyzer):
    """Extracts Oracle objects and their usage from SQL and PL/SQL."""

    name = "sql"
    supported_extensions = (
        ".sql", ".plsql", ".pls", ".pks", ".pkb", ".prc", ".fnc",
        ".trg", ".spc", ".bdy", ".vw",
    )
    priority = 50

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        result = AnalysisResult()
        cleaned = blank_noise(context.content)
        excluded = cte_names(cleaned)

        self._collect_declarations(context, cleaned, result)
        self._collect_calls(context, cleaned, result)

        statements = find_statements(cleaned)
        for ordinal, statement in enumerate(statements, start=1):
            self._collect_statement(context, statement, ordinal, excluded, result)

        result.metadata["sql_statements"] = len(statements)
        return result

    # -- statements ---------------------------------------------------------

    def _collect_statement(
        self,
        context: AnalysisContext,
        statement: Statement,
        ordinal: int,
        excluded: set[str],
        result: AnalysisResult,
    ) -> None:
        tables = table_references(statement, excluded)
        if not tables:
            return

        span = context.span_of_offsets(statement.start, statement.end)
        query = EntityDraft(
            EntityType.SQL_QUERY,
            f"{statement.kind}#{ordinal}",
            span=span,
            container=context.relative_path,
            description=f"Sentencia {statement.kind.upper()} en {context.relative_path}",
            evidence_snippet=context.snippet(span),
            metadata={"kind": statement.kind, "writes": statement.writes},
        )
        result.entities.append(query)

        # alias (and bare table name) -> the table draft it stands for
        by_qualifier: dict[str, EntityDraft] = {}
        written_table: EntityDraft | None = None

        for reference in tables:
            table_span = context.span_of_offsets(reference.offset, reference.offset)
            table = EntityDraft(
                EntityType.ORACLE_TABLE,
                reference.name,
                span=table_span,
                schema=reference.schema,
                qualified_name=(
                    f"{reference.schema}.{reference.name}" if reference.schema else None
                ),
                evidence_snippet=context.snippet(table_span),
            )
            result.entities.append(table)

            result.relationships.append(
                RelationshipDraft(
                    source_ref=query.ref,
                    relation_type=(
                        RelationType.QUERY_WRITES_TABLE
                        if reference.written
                        else RelationType.QUERY_READS_TABLE
                    ),
                    target_ref=table.ref,
                    span=table_span,
                    evidence_snippet=context.snippet(table_span),
                    confidence=CONFIRMED,
                )
            )

            by_qualifier[reference.name.upper()] = table
            if reference.alias:
                by_qualifier[reference.alias.upper()] = table
            if reference.written and written_table is None:
                written_table = table

        self._collect_columns(
            context, statement, query, by_qualifier, written_table, result
        )
        self._collect_joins(context, statement, by_qualifier, result)

    def _collect_joins(
        self,
        context: AnalysisContext,
        statement: Statement,
        by_qualifier: dict[str, EntityDraft],
        result: AnalysisResult,
    ) -> None:
        """Record which tables a statement relates, and on which columns.

        This is what makes an entity-relationship view possible without ever
        touching the database. It is recorded as confirmed, because a join
        condition is direct syntax — but its metadata says plainly that it came
        from a query and not from a declared constraint, so nobody mistakes the
        drawing for the schema.
        """
        seen: set[str] = set()

        for condition in join_conditions(statement):
            left = by_qualifier.get(condition.left_qualifier.upper())
            right = by_qualifier.get(condition.right_qualifier.upper())
            # A qualifier that matches no table in this statement is not a join;
            # guessing which table it meant would fabricate an edge.
            if left is None or right is None or left.ref == right.ref:
                continue

            # One edge per pair regardless of direction: A joined to B is the
            # same fact as B joined to A, and drawing both would double every
            # line in the diagram.
            pair = "|".join(sorted([left.ref, right.ref]))
            if pair in seen:
                continue
            seen.add(pair)

            span = context.span_of_offsets(condition.offset, condition.offset)
            result.relationships.append(
                RelationshipDraft(
                    source_ref=left.ref,
                    relation_type=RelationType.TABLE_JOINS_TABLE,
                    target_ref=right.ref,
                    span=span,
                    evidence_snippet=context.snippet(span),
                    confidence=CONFIRMED,
                    metadata={
                        "left_column": condition.left_column.upper(),
                        "right_column": condition.right_column.upper(),
                        "source": "join_condition",
                    },
                )
            )

    def _collect_columns(
        self,
        context: AnalysisContext,
        statement: Statement,
        query: EntityDraft,
        by_qualifier: dict[str, EntityDraft],
        written_table: EntityDraft | None,
        result: AnalysisResult,
    ) -> None:
        seen: set[str] = set()

        def record(column_name: str, owner: EntityDraft, offset: int) -> None:
            key = f"{owner.ref}|{column_name.upper()}"
            if key in seen:
                return
            seen.add(key)
            span = context.span_of_offsets(offset, offset)
            column = EntityDraft(
                EntityType.ORACLE_COLUMN,
                column_name,
                span=span,
                schema=owner.schema,
                container=owner.normalized_name,
                qualified_name=f"{owner.normalized_name}.{column_name.upper()}",
                evidence_snippet=context.snippet(span),
            )
            result.entities.append(column)
            result.relationships.append(
                RelationshipDraft(
                    source_ref=query.ref,
                    relation_type=RelationType.QUERY_USES_COLUMN,
                    target_ref=column.ref,
                    span=span,
                    evidence_snippet=context.snippet(span),
                    confidence=CONFIRMED,
                )
            )

        # alias.column — the qualifier names the owner outright
        for reference in qualified_columns(statement):
            owner = by_qualifier.get(reference.qualifier.upper())
            if owner is not None:
                record(reference.column, owner, reference.offset)

        # insert into T (a, b, c) — the owner is the insert target
        for match in _INSERT_COLUMNS.finditer(statement.text):
            _, table_name = split_schema(match.group(1))
            owner = by_qualifier.get(table_name.upper())
            if owner is None:
                continue
            for column in _split_column_list(match.group(2)):
                offset = statement.start + match.start(2)
                record(column, owner, offset)

        # update T set a = ... — the owner is the table being written
        if statement.kind == "update":
            owner = written_table
            set_match = _SET_CLAUSE.search(statement.text)
            if owner is not None and set_match:
                for column_match in _SET_COLUMN.finditer(set_match.group(1)):
                    qualifier, column = split_schema(column_match.group(1))
                    target = by_qualifier.get(qualifier.upper()) if qualifier else owner
                    if target is not None:
                        record(
                            column,
                            target,
                            statement.start + set_match.start(1) + column_match.start(1),
                        )

    # -- declarations and calls ---------------------------------------------

    def _collect_declarations(
        self, context: AnalysisContext, cleaned: str, result: AnalysisResult
    ) -> None:
        for pattern, entity_type in (
            (_PACKAGE, EntityType.ORACLE_PACKAGE),
            (_PROCEDURE, EntityType.ORACLE_PROCEDURE),
            (_FUNCTION, EntityType.ORACLE_FUNCTION),
        ):
            for match in pattern.finditer(cleaned):
                schema, name = split_schema(match.group(1))
                if not name:
                    continue
                span = context.span_of_offsets(match.start(1), match.start(1))
                draft = EntityDraft(
                    entity_type,
                    name,
                    span=span,
                    schema=schema,
                    qualified_name=f"{schema}.{name}" if schema else None,
                    evidence_snippet=context.snippet(span),
                    metadata={"declared_in": context.relative_path},
                )
                result.entities.append(draft)
                result.relationships.append(
                    RelationshipDraft(
                        source_ref=draft.ref,
                        relation_type=RelationType.ENTITY_DEFINED_IN_FILE,
                        target_ref=_file_ref(context),
                        span=span,
                        evidence_snippet=context.snippet(span),
                        confidence=CONFIRMED,
                    )
                )

    def _collect_calls(
        self, context: AnalysisContext, cleaned: str, result: AnalysisResult
    ) -> None:
        declared = {
            match.group(1).upper()
            for pattern in (_PACKAGE, _PROCEDURE, _FUNCTION)
            for match in pattern.finditer(cleaned)
        }

        for match in _QUALIFIED_CALL.finditer(cleaned):
            package = unquote(match.group(1))
            routine = unquote(match.group(2))
            if package.upper() in _BUILTIN_PACKAGES:
                continue
            # `t.column(...)` is not a call; a qualifier that matched a
            # declaration in this file is the package we are inside of.
            if routine.upper() in declared:
                continue

            span = context.span_of_offsets(match.start(1), match.end(2))
            package_draft = EntityDraft(
                EntityType.ORACLE_PACKAGE,
                package,
                span=span,
                evidence_snippet=context.snippet(span),
            )
            routine_draft = EntityDraft(
                EntityType.ORACLE_PROCEDURE,
                routine,
                span=span,
                container=package.upper(),
                qualified_name=f"{package.upper()}.{routine.upper()}",
                evidence_snippet=context.snippet(span),
            )
            result.entities.extend([package_draft, routine_draft])
            result.relationships.append(
                RelationshipDraft(
                    source_ref=package_draft.ref,
                    relation_type=RelationType.ENTITY_DEPENDS_ON_ENTITY,
                    target_ref=routine_draft.ref,
                    span=span,
                    evidence_snippet=context.snippet(span),
                    confidence=CONFIRMED,
                )
            )


def _file_ref(context: AnalysisContext) -> str:
    """Identity key of the File entity the pipeline creates for this file."""
    from ..domain.naming import entity_identity_key, normalize_name

    return entity_identity_key(
        EntityType.FILE, normalize_name(context.relative_path, EntityType.FILE)
    )


def _split_column_list(raw: str) -> list[str]:
    """Split an INSERT column list, ignoring anything that is not an identifier."""
    columns: list[str] = []
    for piece in raw.split(","):
        candidate = unquote(piece.strip())
        if candidate and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$#]*", candidate):
            columns.append(candidate)
    return columns
