"""Oracle APEX analyzer.

Finds bind-variable references — ``:P117_NUMCTL``, ``:APP_USER`` — and turns them
into APEX items, pages and, where the SQL makes it provable, mappings from an
item to the column it feeds.

Two rules of the product show up sharply here:

* **An inference is always labelled as one.** ``P117_NUMCTL`` almost certainly
  belongs to page 117, because that is the APEX naming convention — but a
  convention is not syntax. The page and its ``APEX_PAGE_CONTAINS_ITEM`` edge are
  recorded as *inferred* at 0.90, never as confirmed.
* **A mapping needs proof.** ``APEX_ITEM_MAPS_TO_COLUMN`` is only emitted when an
  INSERT lists the column and the item in matching positions, or an UPDATE
  assigns the item to the column. Everything else is left unsaid.
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
from ..domain.confidence import CONFIRMED, STRONG_INFERENCE
from ..domain.types import EntityType, RelationType, VerificationStatus
from .sqltext import QUALIFIED, blank_noise, split_schema, unquote

#: `:P117_NUMCTL`, `:APP_USER`. Excludes `:=` (PL/SQL assignment) and `::`.
_BIND = re.compile(r"(?<![:\w]):([A-Za-z][A-Za-z0-9_$#]*)\b(?!\s*=)")

#: An item name that follows the APEX page convention: P<page>_<name>.
_PAGE_ITEM = re.compile(r"^P(\d{1,5})_(.+)$", re.IGNORECASE)

#: Built-in APEX substitution strings, which are not page items.
_APPLICATION_ITEMS = frozenset(
    {
        "APP_USER", "APP_ID", "APP_PAGE_ID", "APP_SESSION", "APP_ALIAS",
        "APP_UNIQUE_PAGE_ID", "REQUEST", "DEBUG", "SESSION", "APP_SCHEMA_OWNER",
    }
)

#: `insert into T (a, b) values (x, y)` — column list and value list together.
_INSERT_VALUES = re.compile(
    rf"\binsert\s+into\s+({QUALIFIED})\s*\(([^)]*)\)\s*values\s*\(([^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)
#: `set col = :ITEM` inside an UPDATE.
_SET_ASSIGNMENT = re.compile(
    rf"({QUALIFIED})\s*=\s*:([A-Za-z][A-Za-z0-9_$#]*)", re.IGNORECASE
)
_UPDATE_TARGET = re.compile(rf"\bupdate\s+({QUALIFIED})", re.IGNORECASE)


class ApexAnalyzer(Analyzer):
    """Extracts APEX items, pages and their column mappings."""

    name = "apex"
    supported_extensions = (".sql", ".plsql", ".pls", ".pkb", ".prc", ".js", ".txt")
    priority = 40

    def can_analyze(self, file_path: str, content: str) -> bool:
        # Cheap gate: no colon-bind anywhere means nothing to find, whatever the
        # extension says.
        return ":" in content and super().can_analyze(file_path, content)

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        result = AnalysisResult()
        cleaned = blank_noise(context.content)

        items = self._collect_items(context, cleaned, result)
        if items:
            self._collect_mappings(context, cleaned, items, result)

        result.metadata["apex_items"] = len(items)
        return result

    # -- items and pages ----------------------------------------------------

    def _collect_items(
        self, context: AnalysisContext, cleaned: str, result: AnalysisResult
    ) -> dict[str, EntityDraft]:
        items: dict[str, EntityDraft] = {}
        pages: dict[str, EntityDraft] = {}

        for match in _BIND.finditer(cleaned):
            name = match.group(1)
            upper = name.upper()
            if upper in _APPLICATION_ITEMS:
                continue

            page_match = _PAGE_ITEM.match(name)
            if page_match is None:
                # A bind variable that is not an APEX item — a PL/SQL parameter,
                # for instance. Not our business.
                continue

            span = context.span_of_offsets(match.start(1), match.end(1))
            if upper not in items:
                item = EntityDraft(
                    EntityType.APEX_ITEM,
                    name,
                    span=span,
                    evidence_snippet=context.snippet(span),
                    metadata={"page": int(page_match.group(1))},
                )
                items[upper] = item
                result.entities.append(item)

            page_number = page_match.group(1).lstrip("0") or "0"
            if page_number not in pages:
                page = EntityDraft(
                    EntityType.APEX_PAGE,
                    page_number,
                    span=span,
                    description=f"Página APEX {page_number}",
                    confidence=STRONG_INFERENCE,
                    verification_status=VerificationStatus.INFERRED,
                    evidence_snippet=context.snippet(span),
                    metadata={"inferred_from": "convención de nombres P<pagina>_<item>"},
                )
                pages[page_number] = page
                result.entities.append(page)

            result.relationships.append(
                RelationshipDraft(
                    source_ref=pages[page_number].ref,
                    relation_type=RelationType.APEX_PAGE_CONTAINS_ITEM,
                    target_ref=items[upper].ref,
                    span=span,
                    evidence_snippet=context.snippet(span),
                    # The convention is strong but it is still a convention.
                    confidence=STRONG_INFERENCE,
                    status=VerificationStatus.INFERRED,
                )
            )

        return items

    # -- item -> column mappings --------------------------------------------

    def _collect_mappings(
        self,
        context: AnalysisContext,
        cleaned: str,
        items: dict[str, EntityDraft],
        result: AnalysisResult,
    ) -> None:
        for match in _INSERT_VALUES.finditer(cleaned):
            _, table_name = split_schema(match.group(1))
            columns = _split_list(match.group(2))
            values = _split_list(match.group(3))
            if not table_name or len(columns) != len(values):
                # Positional pairing is only sound when the lists line up.
                continue

            # strict=True is safe: the length check above already rejected any
            # statement whose lists do not line up.
            for (column_name, column_offset), (value, value_offset) in zip(
                columns, values, strict=True
            ):
                item = self._item_of(value, items)
                if item is None or not _is_identifier(column_name):
                    continue
                # The evidence spans from the column in the INSERT list to the
                # item in the VALUES list — the two halves that together prove
                # the mapping. Anchoring both ends on the statement, as an
                # earlier version did, sent every mapping to the same useless
                # `) values (` line.
                self._emit_mapping(
                    context,
                    item,
                    table_name,
                    column_name,
                    match.start(2) + column_offset,
                    match.start(3) + value_offset,
                    result,
                )

        for update in _UPDATE_TARGET.finditer(cleaned):
            _, table_name = split_schema(update.group(1))
            if not table_name:
                continue
            region = cleaned[update.end() : _statement_end(cleaned, update.end())]
            for assignment in _SET_ASSIGNMENT.finditer(region):
                qualifier, column_name = split_schema(assignment.group(1))
                item = items.get(assignment.group(2).upper())
                if item is None or not _is_identifier(column_name):
                    continue
                _ = qualifier  # an alias here still refers to the update target
                self._emit_mapping(
                    context,
                    item,
                    table_name,
                    column_name,
                    update.end() + assignment.start(1),
                    update.end() + assignment.start(2),
                    result,
                )

    def _emit_mapping(
        self,
        context: AnalysisContext,
        item: EntityDraft,
        table_name: str,
        column_name: str,
        column_offset: int,
        value_offset: int,
        result: AnalysisResult,
    ) -> None:
        start, end = sorted((column_offset, value_offset))
        span = context.span_of_offsets(start, end)
        column = EntityDraft(
            EntityType.ORACLE_COLUMN,
            column_name,
            span=span,
            container=table_name.upper(),
            qualified_name=f"{table_name.upper()}.{column_name.upper()}",
            evidence_snippet=context.snippet(span),
        )
        result.entities.append(column)
        result.relationships.append(
            RelationshipDraft(
                source_ref=item.ref,
                relation_type=RelationType.APEX_ITEM_MAPS_TO_COLUMN,
                target_ref=column.ref,
                span=span,
                evidence_snippet=context.snippet(span),
                # The statement itself pairs them; nothing is being guessed.
                confidence=CONFIRMED,
            )
        )

    @staticmethod
    def _item_of(value: str, items: dict[str, EntityDraft]) -> EntityDraft | None:
        stripped = value.strip()
        if not stripped.startswith(":"):
            return None
        return items.get(stripped[1:].strip().upper())


def _split_list(raw: str) -> list[tuple[str, int]]:
    """Split a comma-separated list into ``(text, offset)`` pairs.

    The offset is where the item's first non-space character sits inside ``raw``,
    which is what lets each mapping cite its own position instead of the whole
    statement's.
    """
    items: list[tuple[str, int]] = []
    position = 0
    for piece in raw.split(","):
        stripped = piece.strip()
        offset = position + (len(piece) - len(piece.lstrip())) if stripped else position
        items.append((stripped, offset))
        position += len(piece) + 1  # the comma
    return items


def _is_identifier(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$#]*", unquote(name)))


def _statement_end(cleaned: str, start: int) -> int:
    """End of the statement beginning at ``start`` — its ``;`` or end of text."""
    semicolon = cleaned.find(";", start)
    return len(cleaned) if semicolon == -1 else semicolon
