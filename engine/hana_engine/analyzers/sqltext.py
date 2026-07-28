"""Shared SQL text utilities.

Three analyzers need to read SQL: the SQL/PL-SQL one, the JRXML one (report
``<queryString>``) and the MOCA one (bracketed statements inside a pipeline).
The tokenising rules live here so all three agree.

No SQL is ever executed. Everything in this module is text manipulation.

The central idea is :func:`blank_noise`: comments and string literals are
replaced by spaces *of the same length*. Every offset therefore still points at
the same character in the original text, so a match found in the cleaned string
can be reported against the real file without any bookkeeping — and a table name
mentioned inside a comment or a quoted string can never be mistaken for a real
reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Words that may follow FROM/JOIN but are never a table name.
_NOT_TABLES = frozenset(
    {
        "SELECT", "WHERE", "GROUP", "ORDER", "HAVING", "UNION", "MINUS",
        "INTERSECT", "CONNECT", "START", "DUAL", "LATERAL", "TABLE", "ONLY",
        "XMLTABLE", "JSON_TABLE", "VALUES", "SET", "USING", "ON", "AND", "OR",
    }
)

#: Keywords that terminate an alias position.
_ALIAS_STOPWORDS = frozenset(
    {
        "ON", "USING", "WHERE", "GROUP", "ORDER", "HAVING", "JOIN", "INNER",
        "LEFT", "RIGHT", "FULL", "OUTER", "CROSS", "UNION", "MINUS", "SET",
        "INTERSECT", "START", "CONNECT", "VALUES", "AND", "OR", "WHEN", "THEN",
        "ELSE", "END", "SELECT", "FROM", "INTO", "AS", "PARTITION", "LOOP",
    }
)

#: An Oracle identifier: optionally quoted, optionally schema-qualified.
IDENTIFIER = r'(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$#]*)'
QUALIFIED = rf'{IDENTIFIER}(?:\s*\.\s*{IDENTIFIER})*'


def blank_noise(sql: str) -> str:
    """Replace comments and string literals with spaces, preserving offsets.

    ``--`` line comments, ``/* */`` block comments, ``'...'`` literals and
    ``q'[...]'`` quoted literals all become runs of spaces. Newlines are kept so
    line numbers stay correct.

    >>> blank_noise("select 1 -- from secrets\\nfrom t")
    'select 1                \\nfrom t'
    """
    out = list(sql)
    index = 0
    length = len(sql)

    def blank_until(start: int, end: int) -> None:
        for position in range(start, min(end, length)):
            if out[position] != "\n":
                out[position] = " "

    while index < length:
        char = sql[index]
        nxt = sql[index + 1] if index + 1 < length else ""

        if char == "-" and nxt == "-":
            end = sql.find("\n", index)
            end = length if end == -1 else end
            blank_until(index, end)
            index = end
        elif char == "/" and nxt == "*":
            end = sql.find("*/", index + 2)
            end = length if end == -1 else end + 2
            blank_until(index, end)
            index = end
        elif char == "'":
            end = index + 1
            while end < length:
                if sql[end] == "'":
                    # '' is an escaped quote inside the literal.
                    if end + 1 < length and sql[end + 1] == "'":
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            blank_until(index, end)
            index = end
        else:
            index += 1

    return "".join(out)


def unquote(name: str) -> str:
    """Strip Oracle double quotes and surrounding whitespace."""
    cleaned = name.strip()
    if len(cleaned) >= 2 and cleaned[0] == '"' and cleaned[-1] == '"':
        return cleaned[1:-1]
    return cleaned


def split_schema(qualified: str) -> tuple[str | None, str]:
    """Split ``SCHEMA.OBJECT`` into ``(schema, object)``.

    Names with three parts (``SCHEMA.PACKAGE.PROC``) keep everything but the
    last component as the qualifier.
    """
    parts = [unquote(part) for part in re.split(r"\s*\.\s*", qualified.strip()) if part]
    if not parts:
        return None, ""
    if len(parts) == 1:
        return None, parts[0]
    return ".".join(parts[:-1]), parts[-1]


@dataclass(frozen=True)
class Statement:
    """One top-level DML statement found in a script."""

    kind: str  # select | insert | update | delete | merge
    start: int
    end: int
    text: str

    @property
    def writes(self) -> bool:
        return self.kind in ("insert", "update", "delete", "merge")


_STATEMENT_START = re.compile(
    r"\b(with|select|insert|update|delete|merge)\b", re.IGNORECASE
)


def find_statements(cleaned: str) -> list[Statement]:
    """Locate DML statements in already-cleaned SQL.

    Each statement runs to the next statement keyword at the same nesting depth,
    to a ``;``, or to end of text. Keywords inside parentheses are skipped, so a
    subquery does not become a statement of its own — its tables still belong to
    the enclosing statement, which is what "this query reads that table" means to
    a user.

    ``WITH`` is a special case. Its CTE bodies live inside parentheses, so they
    are invisible at depth zero, yet the tables they read are unquestionably read
    by the statement. A ``WITH`` therefore swallows everything up to its
    terminating ``;`` and takes its kind from the DML that follows the CTE list.
    """
    statements: list[Statement] = []
    depths = _depth_map(cleaned)

    starts = [
        (match.start(), match.group(1).lower())
        for match in _STATEMENT_START.finditer(cleaned)
        if depths[match.start()] == 0
    ]

    index = 0
    while index < len(starts):
        start, kind = starts[index]
        semicolon = cleaned.find(";", start)
        hard_limit = len(cleaned) if semicolon == -1 else semicolon

        if kind == "with":
            limit = hard_limit
            effective = "select"
            for following_start, following_kind in starts[index + 1 :]:
                if following_start >= limit:
                    break
                if following_kind != "with":
                    effective = following_kind
                    break
            # Everything up to the terminator belongs to this one statement.
            while index + 1 < len(starts) and starts[index + 1][0] < limit:
                index += 1
            statements.append(Statement(effective, start, limit, cleaned[start:limit]))
        else:
            next_start = (
                starts[index + 1][0] if index + 1 < len(starts) else len(cleaned)
            )
            limit = min(next_start, hard_limit)
            statements.append(Statement(kind, start, limit, cleaned[start:limit]))

        index += 1

    return statements


def _depth_map(text: str) -> list[int]:
    """Parenthesis depth at each character position."""
    depths = [0] * (len(text) + 1)
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depths[index] = depth
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
            depths[index] = depth
        else:
            depths[index] = depth
    depths[len(text)] = depth
    return depths


_CTE = re.compile(rf"\bwith\s+({IDENTIFIER})\s+as\s*\(", re.IGNORECASE)
_CTE_NEXT = re.compile(rf",\s*({IDENTIFIER})\s+as\s*\(", re.IGNORECASE)


def cte_names(cleaned: str) -> set[str]:
    """Names introduced by ``WITH ... AS (...)``.

    These look exactly like tables in a ``FROM`` clause but are not tables, and
    recording them as Oracle objects would be a fabrication.
    """
    names = {unquote(match.group(1)).upper() for match in _CTE.finditer(cleaned)}
    if names:
        names |= {unquote(match.group(1)).upper() for match in _CTE_NEXT.finditer(cleaned)}
    return names


# `FROM t`, `JOIN t`, `USING t` — read positions. `USING` covers the source of a
# MERGE; a join's `USING (col)` cannot match because a parenthesis is not an
# identifier.
_READ_SOURCES = re.compile(
    rf"\b(?:from|join|using)\s+({QUALIFIED})\s*({IDENTIFIER})?", re.IGNORECASE
)
# Write positions, per statement kind.
_INSERT_TARGET = re.compile(rf"\binsert\s+into\s+({QUALIFIED})", re.IGNORECASE)
_UPDATE_TARGET = re.compile(
    rf"\bupdate\s+({QUALIFIED})\s*({IDENTIFIER})?", re.IGNORECASE
)
_DELETE_TARGET = re.compile(rf"\bdelete\s+from\s+({QUALIFIED})", re.IGNORECASE)
_MERGE_TARGET = re.compile(
    rf"\bmerge\s+into\s+({QUALIFIED})\s*({IDENTIFIER})?", re.IGNORECASE
)


@dataclass(frozen=True)
class TableRef:
    """A table or view named in a statement."""

    name: str
    schema: str | None
    alias: str | None
    offset: int
    written: bool


def table_references(statement: Statement, excluded: set[str]) -> list[TableRef]:
    """Extract every table a statement reads or writes.

    ``excluded`` holds CTE names, which are filtered out. Offsets are relative to
    the cleaned document, so they map straight back to the source file.
    """
    found: list[TableRef] = []
    seen: set[tuple[str, bool]] = set()

    def add(raw: str, alias: str | None, offset: int, written: bool) -> None:
        schema, name = split_schema(raw)
        if not name or name.upper() in _NOT_TABLES:
            return
        if name.upper() in excluded and schema is None:
            return
        key = (f"{schema or ''}.{name}".upper(), written)
        if key in seen:
            return
        seen.add(key)
        alias_clean = unquote(alias) if alias else None
        if alias_clean and alias_clean.upper() in _ALIAS_STOPWORDS:
            alias_clean = None
        found.append(TableRef(name, schema, alias_clean, offset, written))

    text = statement.text
    base = statement.start

    write_patterns = {
        "insert": _INSERT_TARGET,
        "update": _UPDATE_TARGET,
        "delete": _DELETE_TARGET,
        "merge": _MERGE_TARGET,
    }
    pattern = write_patterns.get(statement.kind)
    if pattern is not None:
        for match in pattern.finditer(text):
            alias = match.group(2) if match.re.groups >= 2 else None
            add(match.group(1), alias, base + match.start(1), True)

    for match in _READ_SOURCES.finditer(text):
        add(match.group(1), match.group(2), base + match.start(1), False)

    # Comma-separated FROM lists — `from a x, b y` — are the old-style join and
    # are everywhere in long-lived Oracle code. Without this only the first
    # table of such a query would be seen, and none of its relationships.
    for clause in _FROM_CLAUSE.finditer(text):
        for name, alias, offset in _split_from_list(clause.group(1), clause.start(1)):
            add(name, alias, base + offset, False)

    return found


#: Everything between FROM and whatever ends the clause.
_FROM_CLAUSE = re.compile(
    r"\bfrom\s+(.*?)(?=\b(?:where|group|order|having|connect|start|union|minus"
    r"|intersect|join|inner|left|right|full|cross|on|set|returning|into)\b|$)",
    re.IGNORECASE | re.DOTALL,
)

_FROM_ITEM = re.compile(rf"^\s*({QUALIFIED})(?:\s+({IDENTIFIER}))?\s*$")


def _split_from_list(clause: str, base: int) -> list[tuple[str, str | None, int]]:
    """Split `a x, b y` into its entries, keeping each one's offset.

    Commas inside parentheses belong to a function call or a subquery, not to
    the table list, so nesting is tracked rather than splitting blindly.
    """
    entries: list[tuple[str, str | None, int]] = []
    depth = 0
    start = 0

    pieces: list[tuple[str, int]] = []
    for index, char in enumerate(clause):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            pieces.append((clause[start:index], start))
            start = index + 1
    pieces.append((clause[start:], start))

    for piece, offset in pieces:
        match = _FROM_ITEM.match(piece)
        if match is None:
            continue
        leading = len(piece) - len(piece.lstrip())
        entries.append((match.group(1), match.group(2), base + offset + leading))

    return entries


_QUALIFIED_COLUMN = re.compile(
    rf"\b({IDENTIFIER})\s*\.\s*({IDENTIFIER})\b(?!\s*\()"
)


@dataclass(frozen=True)
class ColumnRef:
    """A column reference qualified by a table alias or name."""

    qualifier: str
    column: str
    offset: int


@dataclass(frozen=True)
class JoinCondition:
    """Two qualified columns compared with ``=``.

    The building block of an entity-relationship view. A join condition does not
    prove a foreign key exists in the database — HANA never connects to Oracle —
    but it does prove that somebody's SQL relates these two tables on these two
    columns, which is a fact worth drawing.
    """

    left_qualifier: str
    left_column: str
    right_qualifier: str
    right_column: str
    offset: int


#: `a.col = b.col`. Only equality between two *qualified* columns counts: a
#: comparison against a literal or a bind variable is a filter, not a link.
_JOIN_CONDITION = re.compile(
    rf"\b({IDENTIFIER})\s*\.\s*({IDENTIFIER})\s*=\s*({IDENTIFIER})\s*\.\s*({IDENTIFIER})\b"
)


def join_conditions(statement: Statement) -> list[JoinCondition]:
    """Find ``alias.column = alias.column`` comparisons anywhere in a statement.

    Deliberately not restricted to the ``ON`` clause: plenty of production SQL
    joins in the ``WHERE`` clause instead, and that relates the tables just as
    firmly.
    """
    found: list[JoinCondition] = []
    for match in _JOIN_CONDITION.finditer(statement.text):
        left_qualifier = unquote(match.group(1))
        right_qualifier = unquote(match.group(3))
        # `e.numctl = e.numctl` links nothing.
        if left_qualifier.upper() == right_qualifier.upper():
            continue
        found.append(
            JoinCondition(
                left_qualifier,
                unquote(match.group(2)),
                right_qualifier,
                unquote(match.group(4)),
                statement.start + match.start(),
            )
        )
    return found


def qualified_columns(statement: Statement) -> list[ColumnRef]:
    """Find ``alias.column`` references.

    Only qualified columns are reported. A bare column name cannot be attributed
    to a table without resolving the whole query, and guessing would put
    unfounded edges in the graph.
    """
    references: list[ColumnRef] = []
    for match in _QUALIFIED_COLUMN.finditer(statement.text):
        qualifier = unquote(match.group(1))
        column = unquote(match.group(2))
        if column == "*" or column.upper() in _ALIAS_STOPWORDS:
            continue
        references.append(
            ColumnRef(qualifier, column, statement.start + match.start(2))
        )
    return references
