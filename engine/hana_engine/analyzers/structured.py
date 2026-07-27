"""JSON and source-code analyzers.

Two small analyzers that round out the MVP:

* :class:`JsonAnalyzer` walks a JSON document and records its properties, noting
  the ones whose *value* names something the rest of the graph knows about — a
  table, an APEX item, a report.
* :class:`CodeAnalyzer` reads JavaScript and Python for functions, classes and
  imports.

Python is parsed with :mod:`ast`, which builds a tree without executing a single
statement. JavaScript has no parser in the standard library, so it is matched
with expressions and its findings are marked accordingly — a declaration found
by pattern is not the same kind of fact as one found by a parser, and the
confidence says so.
"""

from __future__ import annotations

import ast
import json
import re

from ..domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    Analyzer,
    AnalyzerMessage,
    EntityDraft,
    RelationshipDraft,
    SourceSpan,
)
from ..domain.confidence import CONFIRMED, MENTION, STRONG_INFERENCE
from ..domain.types import EntityType, RelationType, Severity, VerificationStatus

#: Values that look like an APEX page item.
_APEX_ITEM = re.compile(r"^P\d{1,5}_[A-Za-z0-9_$#]+$")
#: Values that look like `TABLA.COLUMNA`.
_TABLE_COLUMN = re.compile(r"^([A-Za-z][A-Za-z0-9_$#]*)\.([A-Za-z][A-Za-z0-9_$#]*)$")

#: How deep to descend before giving up. Guards against pathological documents.
_MAX_JSON_DEPTH = 24

#: Array elements visited. Bounded so a data dump cannot stall an analysis, and
#: the truncation is reported rather than hidden.
_MAX_ARRAY_ITEMS = 500


class JsonAnalyzer(Analyzer):
    """Records the shape of a JSON document and the identifiers inside it."""

    name = "json"
    supported_extensions = (".json", ".jsonc")
    priority = 30

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        result = AnalysisResult()
        try:
            document = json.loads(context.content)
        except json.JSONDecodeError as error:
            result.errors.append(
                AnalyzerMessage(
                    code="malformed_json",
                    message=f"JSON mal formado: {error.msg}",
                    severity=Severity.ERROR,
                    span=SourceSpan(error.lineno, error.lineno)
                    if error.lineno >= 1
                    else None,
                )
            )
            return result

        line_of = _key_lines(context.content)
        seen: set[str] = set()
        self._walk(context, document, "", 0, line_of, seen, result)
        result.metadata["json_properties"] = len(seen)
        return result

    def _walk(
        self,
        context: AnalysisContext,
        node: object,
        path: str,
        depth: int,
        line_of: dict[str, int],
        seen: set[str],
        result: AnalysisResult,
    ) -> None:
        if depth > _MAX_JSON_DEPTH:
            return

        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}" if path else key
                if child not in seen:
                    seen.add(child)
                    self._emit_property(context, key, child, line_of, result)
                self._reference(context, value, child, line_of, result)
                self._walk(context, value, child, depth + 1, line_of, seen, result)
        elif isinstance(node, list):
            # Every element is visited, not just the first: an APEX descriptor
            # lists its items as an array, and stopping at index 0 silently lost
            # every identifier after it. Property *paths* are deduplicated by
            # `seen`, so the shape is still recorded once however long the array.
            for item in node[:_MAX_ARRAY_ITEMS]:
                self._walk(context, item, f"{path}[]", depth + 1, line_of, seen, result)
            if len(node) > _MAX_ARRAY_ITEMS:
                result.warnings.append(
                    AnalyzerMessage(
                        code="array_truncated",
                        message=(
                            f"el arreglo {path or '(raíz)'} tiene {len(node)} elementos; "
                            f"solo se analizaron los primeros {_MAX_ARRAY_ITEMS}"
                        ),
                        severity=Severity.WARNING,
                        detail={"path": path, "length": len(node)},
                    )
                )

    def _emit_property(
        self,
        context: AnalysisContext,
        key: str,
        path: str,
        line_of: dict[str, int],
        result: AnalysisResult,
    ) -> None:
        line = line_of.get(key, 1)
        span = SourceSpan(line, line)
        result.entities.append(
            EntityDraft(
                EntityType.JSON_PROPERTY,
                path,
                span=span,
                container=context.relative_path,
                evidence_snippet=context.snippet(span),
                metadata={"key": key},
            )
        )

    def _reference(
        self,
        context: AnalysisContext,
        value: object,
        path: str,
        line_of: dict[str, int],
        result: AnalysisResult,
    ) -> None:
        """Link a string value that names something the graph already models."""
        if not isinstance(value, str) or not value.strip():
            return

        line = line_of.get(path.rsplit(".", 1)[-1], 1)
        span = SourceSpan(line, line)
        source_ref = EntityDraft(
            EntityType.JSON_PROPERTY,
            path,
            container=context.relative_path,
        ).ref

        target: EntityDraft | None = None
        if _APEX_ITEM.match(value):
            target = EntityDraft(
                EntityType.APEX_ITEM, value, span=span, evidence_snippet=value
            )
        else:
            match = _TABLE_COLUMN.match(value)
            if match and value.isupper():
                target = EntityDraft(
                    EntityType.ORACLE_COLUMN,
                    match.group(2),
                    span=span,
                    container=match.group(1).upper(),
                    qualified_name=value.upper(),
                    evidence_snippet=value,
                )

        if target is None:
            return

        result.entities.append(target)
        result.relationships.append(
            RelationshipDraft(
                source_ref=source_ref,
                relation_type=RelationType.ENTITY_MENTIONS_ENTITY,
                target_ref=target.ref,
                span=span,
                evidence_snippet=value,
                # A JSON descriptor naming a column is strong evidence of a
                # relationship, but it is a convention, not a definition.
                confidence=STRONG_INFERENCE,
                status=VerificationStatus.INFERRED,
            )
        )


# ---------------------------------------------------------------------------
# Source code
# ---------------------------------------------------------------------------
_JS_FUNCTION = re.compile(
    r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", re.MULTILINE
)
_JS_ARROW = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"
)
_JS_CLASS = re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")
_JS_IMPORT = re.compile(
    r"""(?:\bimport\b[^;\n]*?from\s*|\brequire\s*\(\s*)['"]([^'"]+)['"]"""
)
#: `$s('P117_X', ...)`, `apex.item('P117_X')`, or a bare quoted item name.
_JS_APEX_ITEM = re.compile(r"""['"](P\d{1,5}_[A-Za-z0-9_$#]+)['"]""")


class CodeAnalyzer(Analyzer):
    """Extracts declarations from JavaScript and Python sources."""

    name = "code"
    supported_extensions = (".js", ".mjs", ".cjs", ".jsx", ".py")
    priority = 20

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        result = AnalysisResult()
        if context.extension == ".py":
            self._analyze_python(context, result)
        else:
            self._analyze_javascript(context, result)
        return result

    # -- Python -------------------------------------------------------------

    def _analyze_python(
        self, context: AnalysisContext, result: AnalysisResult
    ) -> None:
        try:
            # Parsing builds a tree. It does not run the module.
            tree = ast.parse(context.content)
        except SyntaxError as error:
            result.errors.append(
                AnalyzerMessage(
                    code="python_syntax_error",
                    message=f"Python no analizable: {error.msg}",
                    severity=Severity.ERROR,
                    span=SourceSpan(error.lineno, error.lineno)
                    if error.lineno
                    else None,
                )
            )
            return

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._emit(
                    context,
                    EntityType.PYTHON_FUNCTION,
                    node.name,
                    node.lineno,
                    getattr(node, "end_lineno", node.lineno),
                    result,
                    confidence=CONFIRMED,
                )
            elif isinstance(node, ast.ClassDef):
                self._emit(
                    context,
                    EntityType.PYTHON_FUNCTION,
                    node.name,
                    node.lineno,
                    getattr(node, "end_lineno", node.lineno),
                    result,
                    confidence=CONFIRMED,
                    metadata={"kind": "class"},
                )
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", None) or ""
                for alias in node.names:
                    name = module or alias.name
                    self._emit_import(context, name, node.lineno, result)

    # -- JavaScript ---------------------------------------------------------

    def _analyze_javascript(
        self, context: AnalysisContext, result: AnalysisResult
    ) -> None:
        content = context.content
        for pattern, metadata in (
            (_JS_FUNCTION, {"kind": "function"}),
            (_JS_ARROW, {"kind": "arrow"}),
            (_JS_CLASS, {"kind": "class"}),
        ):
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                self._emit(
                    context,
                    EntityType.JAVASCRIPT_FUNCTION,
                    match.group(1),
                    line,
                    line,
                    result,
                    # Found by pattern, not by a parser: a real declaration in
                    # practice, but not the same grade of fact as Python's ast.
                    confidence=STRONG_INFERENCE,
                    metadata=metadata,
                )

        for match in _JS_IMPORT.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
            self._emit_import(context, match.group(1), line, result)

        for match in _JS_APEX_ITEM.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
            span = SourceSpan(line, line)
            item = EntityDraft(
                EntityType.APEX_ITEM,
                match.group(1),
                span=span,
                evidence_snippet=context.snippet(span),
            )
            result.entities.append(item)

    # -- shared -------------------------------------------------------------

    def _emit(
        self,
        context: AnalysisContext,
        entity_type: EntityType,
        name: str,
        start: int,
        end: int,
        result: AnalysisResult,
        *,
        confidence: float,
        metadata: dict | None = None,
    ) -> None:
        span = SourceSpan(start, max(start, end))
        draft = EntityDraft(
            entity_type,
            name,
            span=span,
            container=context.relative_path,
            confidence=confidence,
            evidence_snippet=context.snippet(span, max_chars=200),
            metadata=metadata or {},
        )
        result.entities.append(draft)

    def _emit_import(
        self,
        context: AnalysisContext,
        module: str,
        line: int,
        result: AnalysisResult,
    ) -> None:
        span = SourceSpan(line, line)
        target = EntityDraft(
            EntityType.FILE if module.startswith(".") else EntityType.UNKNOWN,
            module,
            span=span,
            confidence=MENTION,
            evidence_snippet=context.snippet(span, max_chars=200),
            metadata={"kind": "import"},
        )
        result.entities.append(target)
        result.relationships.append(
            RelationshipDraft(
                source_ref=_file_ref(context),
                relation_type=RelationType.ENTITY_DEPENDS_ON_ENTITY,
                target_ref=target.ref,
                span=span,
                evidence_snippet=context.snippet(span, max_chars=200),
                confidence=CONFIRMED,
            )
        )


def _file_ref(context: AnalysisContext) -> str:
    from ..domain.naming import entity_identity_key, normalize_name

    return entity_identity_key(
        EntityType.FILE, normalize_name(context.relative_path, EntityType.FILE)
    )


def _key_lines(content: str) -> dict[str, int]:
    """First line on which each JSON key appears, for provenance."""
    index: dict[str, int] = {}
    for number, line in enumerate(content.splitlines(), start=1):
        for match in re.finditer(r'"([^"]+)"\s*:', line):
            index.setdefault(match.group(1), number)
    return index
