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
from dataclasses import dataclass

from ..domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    Analyzer,
    EntityDraft,
    RelationshipDraft,
    SourceSpan,
)
from ..domain.confidence import CONFIRMED
from ..domain.naming import normalize_name
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

#: Oracle's old outer-join marker, `r.prtnum(+)`, is character-for-character a
#: qualified call. Nothing but a `+` ever sits inside those parentheses.
_OUTER_JOIN_MARKER = re.compile(r"\s*\+\s*\)")

_ROUTINE_TYPES = frozenset({EntityType.ORACLE_PROCEDURE, EntityType.ORACLE_FUNCTION})

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
    #: 4 — records which table a column belongs to as an edge, not only as a
    #: container, so impact can walk from a column to what reads its table.
    #: 3 — learned the call graph: which routine calls which, and from where.
    #: 2 — learned join conditions (table-to-table links) and comma-separated
    #: FROM lists, the old-style join.
    version = 4

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        result = AnalysisResult()
        cleaned = blank_noise(context.content)
        excluded = cte_names(cleaned)

        declared = self._collect_declarations(context, cleaned, result)

        # Statements are resolved before calls because a call can sit inside
        # one — `select pkg.total(x) from dual` — and then the query is the
        # honest caller.
        statements = find_statements(cleaned)
        analysed: list[_AnalysedStatement] = []
        for ordinal, statement in enumerate(statements, start=1):
            analysed.append(
                self._collect_statement(context, statement, ordinal, excluded, result)
            )

        self._collect_calls(context, cleaned, declared, analysed, result)

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
    ) -> _AnalysedStatement:
        tables = table_references(statement, excluded)
        if not tables:
            return _AnalysedStatement(statement, None, {})

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
        return _AnalysedStatement(statement, query, by_qualifier)

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
            # The owner was already established — it is what `container` holds,
            # and it only ever comes from explicit syntax. Recording it as an
            # edge states nothing new; it makes the fact walkable, which is what
            # lets a column's impact reach the reports that read its table.
            #
            # The evidence spans from the table reference to the column, because
            # neither line proves the ownership alone: `update uc_insp_ent e`
            # says what `e` is, and `set e.estado = ...` says what belongs to it.
            # Citing only the second would open a line that never names the table.
            ownership = span
            if owner.span is not None:
                ownership = SourceSpan(
                    min(owner.span.start_line, span.start_line),
                    max(owner.span.end_line, span.end_line),
                )
            result.relationships.append(
                RelationshipDraft(
                    source_ref=owner.ref,
                    relation_type=RelationType.TABLE_HAS_COLUMN,
                    target_ref=column.ref,
                    span=ownership,
                    evidence_snippet=context.snippet(ownership),
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
    ) -> list[_Declared]:
        declared: list[_Declared] = []

        for declaration in _find_declarations(cleaned):
            span = context.span_of_offsets(
                declaration.name_offset, declaration.name_offset
            )
            draft = EntityDraft(
                declaration.entity_type,
                declaration.name,
                span=span,
                schema=declaration.schema,
                container=declaration.container,
                qualified_name=declaration.qualified_name,
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
            declared.append(_Declared(declaration, draft))

        return declared

    def _collect_calls(
        self,
        context: AnalysisContext,
        cleaned: str,
        declared: list[_Declared],
        analysed: list[_AnalysedStatement],
        result: AnalysisResult,
    ) -> None:
        """Record who calls what.

        The edge that matters is caller → called. A package listing a routine
        is containment, not a call, and answering "what breaks if I change
        this?" with a containment edge would name the package and stop there.

        Only qualified calls are reported. A bare `foo(...)` is far more often
        a built-in or a local variable, and there is no way from one file to
        tell which — inventing the edge would put a false claim in the graph.
        """
        regions = _routine_regions(declared, len(cleaned))
        declaration_spans = [
            (item.declaration.start, item.declaration.end) for item in declared
        ]
        local_packages, local_routines = _local_index(declared)

        for match in _QUALIFIED_CALL.finditer(cleaned):
            package = unquote(match.group(1))
            routine = unquote(match.group(2))
            if package.upper() in _BUILTIN_PACKAGES:
                continue
            # A qualified declaration — `create procedure wms.registrar(...)` —
            # is character-for-character a call. It is a definition, not a use.
            if any(start <= match.start() < end for start, end in declaration_spans):
                continue
            if _OUTER_JOIN_MARKER.match(cleaned, match.end()):
                continue
            if _is_column_of_a_table(match.start(), package, analysed):
                continue

            span = context.span_of_offsets(match.start(1), match.end(2))
            snippet = context.snippet(span)

            package_draft = local_packages.get(package.upper())
            if package_draft is None:
                package_draft = EntityDraft(
                    EntityType.ORACLE_PACKAGE,
                    package,
                    span=span,
                    evidence_snippet=snippet,
                )
                result.entities.append(package_draft)

            # Within this file we know whether the target is a procedure or a
            # function, so we say so. From another file we cannot tell, and a
            # call site never reveals it — so it is recorded as a procedure and
            # the metadata says the kind was not established.
            routine_draft = local_routines.get((package.upper(), routine.upper()))
            declared_here = routine_draft is not None
            if routine_draft is None:
                routine_draft = EntityDraft(
                    EntityType.ORACLE_PROCEDURE,
                    routine,
                    span=span,
                    container=package.upper(),
                    qualified_name=f"{package.upper()}.{routine.upper()}",
                    evidence_snippet=snippet,
                    metadata={"routine_kind": "unknown"},
                )
                result.entities.append(routine_draft)

            result.relationships.append(
                RelationshipDraft(
                    source_ref=package_draft.ref,
                    relation_type=RelationType.ENTITY_DEPENDS_ON_ENTITY,
                    target_ref=routine_draft.ref,
                    span=span,
                    evidence_snippet=snippet,
                    confidence=CONFIRMED,
                )
            )

            caller_ref, caller_kind = _caller_at(
                match.start(), regions, analysed, context
            )
            if caller_ref == routine_draft.ref:
                # Direct recursion. True, but an edge from a thing to itself
                # adds nothing to an impact answer and draws a loop on every
                # diagram.
                continue

            result.relationships.append(
                RelationshipDraft(
                    source_ref=caller_ref,
                    relation_type=RelationType.PROCEDURE_CALLS_PROCEDURE,
                    target_ref=routine_draft.ref,
                    span=span,
                    evidence_snippet=snippet,
                    confidence=CONFIRMED,
                    metadata={
                        "caller_kind": caller_kind,
                        "target_declared_in_file": declared_here,
                    },
                )
            )


@dataclass(frozen=True)
class _Declaration:
    """A PL/SQL declaration, with the stretch of text it occupies."""

    entity_type: EntityType
    name: str
    schema: str | None
    container: str | None
    name_offset: int
    start: int
    end: int

    @property
    def qualified_name(self) -> str | None:
        if self.container:
            return f"{self.container}.{normalize_name(self.name, self.entity_type)}"
        return f"{self.schema}.{self.name}" if self.schema else None


@dataclass(frozen=True)
class _Declared:
    """A declaration paired with the draft that was emitted for it."""

    declaration: _Declaration
    draft: EntityDraft


@dataclass(frozen=True)
class _AnalysedStatement:
    """A statement, the query entity it produced, and its table qualifiers.

    ``query`` is None when the statement named no table, which happens for
    `select pkg.total(x) from dual` — worth knowing, because then the file is
    the only honest caller left.
    """

    statement: Statement
    query: EntityDraft | None
    by_qualifier: dict[str, EntityDraft]


def _find_declarations(cleaned: str) -> list[_Declaration]:
    """Every package, procedure and function declared in the file, in order.

    A routine's ``container`` is the package it sits inside, which is what lets
    `procedure registrar_evento` in a package body and a call to
    `pkg_inspeccion.registrar_evento` elsewhere resolve to the same entity.
    Without it the two would be different rows and the call graph would have a
    hole exactly where the interesting edges are.
    """
    packages: list[tuple[int, str]] = []
    found: list[_Declaration] = []

    for match in _PACKAGE.finditer(cleaned):
        schema, name = split_schema(match.group(1))
        if not name:
            continue
        normalized = normalize_name(name, EntityType.ORACLE_PACKAGE)
        packages.append((match.start(), normalized))
        found.append(
            _Declaration(
                EntityType.ORACLE_PACKAGE,
                name,
                schema,
                None,
                match.start(1),
                match.start(),
                match.end(),
            )
        )

    packages.sort()

    for pattern, entity_type in (
        (_PROCEDURE, EntityType.ORACLE_PROCEDURE),
        (_FUNCTION, EntityType.ORACLE_FUNCTION),
    ):
        for match in pattern.finditer(cleaned):
            schema, name = split_schema(match.group(1))
            if not name:
                continue
            found.append(
                _Declaration(
                    entity_type,
                    name,
                    schema,
                    _enclosing_package(packages, match.start()),
                    match.start(1),
                    match.start(),
                    match.end(),
                )
            )

    found.sort(key=lambda declaration: declaration.start)
    return found


def _enclosing_package(packages: list[tuple[int, str]], offset: int) -> str | None:
    """The package a routine at ``offset`` belongs to, if any."""
    enclosing = None
    for start, name in packages:
        if start < offset:
            enclosing = name
        else:
            break
    return enclosing


def _routine_regions(
    declared: list[_Declared], total: int
) -> list[tuple[int, int, EntityDraft]]:
    """Half-open ranges of text owned by each routine.

    A routine runs until the next one is declared. That is approximate — the
    gap between `end pkg_a;` and the next `procedure` nominally belongs to
    neither — but nothing is called there, and a real PL/SQL parser is a far
    larger commitment than the question warrants.
    """
    routines = [
        item for item in declared if item.declaration.entity_type in _ROUTINE_TYPES
    ]
    regions: list[tuple[int, int, EntityDraft]] = []
    for index, item in enumerate(routines):
        nxt = index + 1
        following = routines[nxt].declaration.start if nxt < len(routines) else total
        regions.append((item.declaration.start, following, item.draft))
    return regions


def _local_index(
    declared: list[_Declared],
) -> tuple[dict[str, EntityDraft], dict[tuple[str, str], EntityDraft]]:
    """Declarations of this file, keyed the way a call site names them."""
    packages: dict[str, EntityDraft] = {}
    routines: dict[tuple[str, str], EntityDraft] = {}
    for item in declared:
        draft = item.draft
        if draft.entity_type is EntityType.ORACLE_PACKAGE:
            packages.setdefault(draft.normalized_name, draft)
        elif draft.entity_type in _ROUTINE_TYPES and draft.container:
            routines.setdefault((draft.container, draft.normalized_name), draft)
    return packages, routines


def _is_column_of_a_table(
    offset: int, qualifier: str, analysed: list[_AnalysedStatement]
) -> bool:
    """True when `x.y(` is a column of a table in the surrounding statement.

    Inside a query, a qualifier that names one of its own tables or aliases is
    a column reference, not a package.
    """
    for item in analysed:
        if item.statement.start <= offset < item.statement.end:
            return qualifier.upper() in item.by_qualifier
    return False


def _caller_at(
    offset: int,
    regions: list[tuple[int, int, EntityDraft]],
    analysed: list[_AnalysedStatement],
    context: AnalysisContext,
) -> tuple[str, str]:
    """Who is making the call at ``offset``, and what kind of thing it is.

    In order of preference: the routine that encloses it, the query it sits
    inside, and failing both the file itself. The last case is the loose body
    of a script or an anonymous block — real code with a real caller, so
    reporting no caller at all would lose the edge, and inventing a routine
    would put a thing in the graph that does not exist.
    """
    for start, end, draft in regions:
        if start <= offset < end:
            return draft.ref, "routine"
    for item in analysed:
        if item.query is not None and item.statement.start <= offset < item.statement.end:
            return item.query.ref, "query"
    return _file_ref(context), "file"


def _file_ref(context: AnalysisContext) -> str:
    """Identity key of the File entity the pipeline creates for this file."""
    from ..domain.naming import entity_identity_key

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
