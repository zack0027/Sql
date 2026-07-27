"""JasperReports (JRXML) analyzer.

Uses a real XML parser, never regular expressions, to read the report's
structure: parameters, fields, variables, the SQL query, images and subreports.

Expressions such as ``$F{netwgt}`` are *matched as text*. They are never
evaluated — a JRXML expression is Java code, and running code found in an
analysed project is exactly what this product promises not to do.

Two findings the analyzer reports as warnings, because they are the mistakes
that actually break reports in production:

* a field referenced by an expression but never declared as ``<field>``;
* a parameter declared but never referenced anywhere.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree

from ..domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    Analyzer,
    AnalyzerMessage,
    EntityDraft,
    RelationshipDraft,
    SourceSpan,
)
from ..domain.confidence import CONFIRMED
from ..domain.types import EntityType, RelationType, Severity
from .sqltext import blank_noise, cte_names, find_statements, table_references

#: `$F{campo}`, `$P{parametro}`, `$V{variable}`.
_EXPRESSION_REFERENCE = re.compile(r"\$([FPV])\{([^}]*)\}")

#: A quoted string inside an expression — how image and subreport paths appear.
_STRING_LITERAL = re.compile(r'"([^"]*)"')

#: Parameter name prefixes owned by the platform, not by the report author.
_PLATFORM_PREFIXES = ("MOCA_", "REPORT_", "JASPER_", "IS_IGNORE_")

#: Individual platform-supplied parameter names.
_PLATFORM_PARAMETERS = frozenset(
    {"SUBREPORT_DIR", "SUBREPORT_directory", "FILTER", "SORT_FIELDS"}
)

#: Elements whose text may reference fields, parameters or variables.
#:
#: ``queryString`` belongs here even though it is not an "expression": a
#: parameter used only as ``$P{P_NUMCTL}`` inside the SQL is very much used, and
#: leaving the query out made the analyzer report live parameters as dead.
_EXPRESSION_TAGS = frozenset(
    {
        "queryString",
        "textFieldExpression", "variableExpression", "imageExpression",
        "subreportExpression", "printWhenExpression", "initialValueExpression",
        "subreportParameterExpression", "groupExpression", "bucketExpression",
        "measureExpression", "hyperlinkReferenceExpression", "anchorNameExpression",
        "dataSourceExpression", "connectionExpression", "returnValue",
    }
)


class JrxmlAnalyzer(Analyzer):
    """Extracts the structure of a JasperReports template."""

    name = "jrxml"
    supported_extensions = (".jrxml",)
    priority = 60

    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        result = AnalysisResult()

        guard = _reject_doctype(context.content)
        if guard is not None:
            result.errors.append(guard)
            return result

        try:
            root = ElementTree.fromstring(context.content)
        except ElementTree.ParseError as error:
            result.errors.append(
                AnalyzerMessage(
                    code="malformed_xml",
                    message=f"JRXML mal formado: {error}",
                    severity=Severity.ERROR,
                    span=_span_of_parse_error(error),
                )
            )
            return result

        report = self._report_entity(context, root)
        result.entities.append(report)

        line_of = _line_index(context.content)
        declared_fields = self._declared(context, root, "field", line_of)
        declared_parameters = self._declared(context, root, "parameter", line_of)
        declared_variables = self._declared(context, root, "variable", line_of)

        self._emit_declarations(
            context, report, declared_fields, EntityType.JASPER_FIELD,
            RelationType.REPORT_USES_FIELD, result,
        )
        self._emit_declarations(
            context, report, declared_parameters, EntityType.JASPER_PARAMETER,
            RelationType.REPORT_USES_PARAMETER, result,
        )
        self._emit_declarations(
            context, report, declared_variables, EntityType.JASPER_VARIABLE,
            RelationType.ENTITY_DEPENDS_ON_ENTITY, result,
        )

        used = self._collect_expression_usage(root)
        self._report_inconsistencies(
            declared_fields,
            declared_parameters,
            used,
            self._platform_parameters(root),
            result,
        )

        self._collect_query(context, root, report, line_of, result)
        self._collect_images(context, root, report, line_of, result)
        self._collect_subreports(context, root, report, line_of, result)

        result.metadata.update(
            {
                "report_name": report.name,
                "fields": len(declared_fields),
                "parameters": len(declared_parameters),
                "variables": len(declared_variables),
            }
        )
        return result

    # -- structure ----------------------------------------------------------

    def _report_entity(
        self, context: AnalysisContext, root: ElementTree.Element
    ) -> EntityDraft:
        name = root.attrib.get("name") or _stem(context.relative_path)
        span = SourceSpan(1, 1)
        return EntityDraft(
            EntityType.JASPER_REPORT,
            name,
            span=span,
            container=context.relative_path,
            description=f"Reporte JasperReports {name}",
            evidence_snippet=context.snippet(span),
        )

    def _declared(
        self,
        context: AnalysisContext,
        root: ElementTree.Element,
        tag: str,
        line_of: dict[str, int],
    ) -> dict[str, int]:
        """Return ``{name: line}`` for every declaration of ``tag``."""
        declared: dict[str, int] = {}
        for element in _iter_tag(root, tag):
            name = element.attrib.get("name")
            if name:
                declared.setdefault(name, line_of.get(f"{tag}:{name}", 1))
        return declared

    def _platform_parameters(self, root: ElementTree.Element) -> set[str]:
        """Parameters supplied by the platform rather than by the report author.

        Blue Yonder injects ``MOCA_REPORT_*`` at run time and marks them with a
        ``<property name="MOCA"/>``; JasperReports owns ``REPORT_*`` and
        ``SUBREPORT_DIR``. None of them is "declared but unused" in any sense the
        author can act on, and reporting them buries the one real finding under
        a dozen false ones.
        """
        injected: set[str] = set()
        for element in _iter_tag(root, "parameter"):
            name = element.attrib.get("name")
            if not name:
                continue
            if name.startswith(_PLATFORM_PREFIXES) or name in _PLATFORM_PARAMETERS:
                injected.add(name)
                continue
            if any(_local(child.tag) == "property" for child in element):
                injected.add(name)
        return injected

    def _emit_declarations(
        self,
        context: AnalysisContext,
        report: EntityDraft,
        declared: dict[str, int],
        entity_type: EntityType,
        relation: RelationType,
        result: AnalysisResult,
    ) -> None:
        for name, line in declared.items():
            span = SourceSpan(line, line)
            draft = EntityDraft(
                entity_type,
                name,
                span=span,
                container=report.normalized_name,
                evidence_snippet=context.snippet(span),
            )
            result.entities.append(draft)
            result.relationships.append(
                RelationshipDraft(
                    source_ref=report.ref,
                    relation_type=relation,
                    target_ref=draft.ref,
                    span=span,
                    evidence_snippet=context.snippet(span),
                    confidence=CONFIRMED,
                )
            )

    def _collect_expression_usage(
        self, root: ElementTree.Element
    ) -> dict[str, set[str]]:
        """Names referenced from expressions, grouped by ``F`` / ``P`` / ``V``."""
        used: dict[str, set[str]] = {"F": set(), "P": set(), "V": set()}
        for element in root.iter():
            if _local(element.tag) not in _EXPRESSION_TAGS:
                continue
            for text in (element.text, element.tail):
                if not text:
                    continue
                for match in _EXPRESSION_REFERENCE.finditer(text):
                    used[match.group(1)].add(match.group(2).strip())
        return used

    def _report_inconsistencies(
        self,
        fields: dict[str, int],
        parameters: dict[str, int],
        used: dict[str, set[str]],
        platform: set[str],
        result: AnalysisResult,
    ) -> None:
        for name in sorted(used["F"] - set(fields)):
            result.warnings.append(
                AnalyzerMessage(
                    code="undeclared_field",
                    message=f"el campo $F{{{name}}} se usa pero no está declarado",
                    severity=Severity.WARNING,
                    detail={"field": name},
                )
            )
        for name in sorted(set(parameters) - used["P"] - platform):
            result.warnings.append(
                AnalyzerMessage(
                    code="unused_parameter",
                    message=f"el parámetro {name} está declarado pero no se usa",
                    severity=Severity.WARNING,
                    detail={"parameter": name},
                )
            )

    # -- query, images, subreports ------------------------------------------

    def _collect_query(
        self,
        context: AnalysisContext,
        root: ElementTree.Element,
        report: EntityDraft,
        line_of: dict[str, int],
        result: AnalysisResult,
    ) -> None:
        for element in _iter_tag(root, "queryString"):
            sql = (element.text or "").strip()
            if not sql:
                continue

            # Where the query's text actually starts in the file. Anchoring every
            # table on the `<queryString>` tag instead sent the reader to a line
            # that does not mention the table at all — and "open the evidence and
            # the proof is there" is the whole promise.
            base_line = _content_line(context.content, sql, line_of.get("queryString", 1))

            cleaned = blank_noise(sql)
            excluded = cte_names(cleaned)
            for statement in find_statements(cleaned):
                for reference in table_references(statement, excluded):
                    line = base_line + sql[: reference.offset].count("\n")
                    span = SourceSpan(line, line)
                    table = EntityDraft(
                        EntityType.ORACLE_TABLE,
                        reference.name,
                        span=span,
                        schema=reference.schema,
                        evidence_snippet=_line_text(context.content, line) or _trim(sql),
                    )
                    result.entities.append(table)
                    result.relationships.append(
                        RelationshipDraft(
                            source_ref=report.ref,
                            relation_type=RelationType.REPORT_QUERIES_TABLE,
                            target_ref=table.ref,
                            span=span,
                            evidence_snippet=_line_text(context.content, line)
                            or _trim(sql),
                            confidence=CONFIRMED,
                        )
                    )

    def _collect_images(
        self,
        context: AnalysisContext,
        root: ElementTree.Element,
        report: EntityDraft,
        line_of: dict[str, int],
        result: AnalysisResult,
    ) -> None:
        for element in _iter_tag(root, "imageExpression"):
            # An image expression is Java, and a real one is routinely a
            # conditional: `$F{tipo}=="Entrada" ? "on.png" : "off.png"`. Taking
            # every quoted literal turned "Entrada" into a file; only literals
            # that actually look like an image path are paths.
            for path in _image_literals(element.text):
                line = line_of.get(f"image:{path}", 1)
                span = SourceSpan(line, line)
                image = EntityDraft(
                    EntityType.FILE,
                    path,
                    span=span,
                    description="Imagen referenciada por un reporte",
                    evidence_snippet=path,
                    metadata={"relative": not _is_absolute(path)},
                )
                result.entities.append(image)
                result.relationships.append(
                    RelationshipDraft(
                        source_ref=report.ref,
                        relation_type=RelationType.REPORT_REFERENCES_IMAGE,
                        target_ref=image.ref,
                        span=span,
                        evidence_snippet=path,
                        confidence=CONFIRMED,
                    )
                )

    def _collect_subreports(
        self,
        context: AnalysisContext,
        root: ElementTree.Element,
        report: EntityDraft,
        line_of: dict[str, int],
        result: AnalysisResult,
    ) -> None:
        for element in _iter_tag(root, "subreportExpression"):
            literals = _string_literals(element.text)
            for path in literals:
                line = line_of.get(f"subreport:{path}", 1)
                span = SourceSpan(line, line)
                subreport = EntityDraft(
                    EntityType.JASPER_SUBREPORT,
                    _stem(path),
                    span=span,
                    evidence_snippet=path,
                    metadata={"path": path},
                )
                result.entities.append(subreport)
                result.relationships.append(
                    RelationshipDraft(
                        source_ref=report.ref,
                        relation_type=RelationType.REPORT_INCLUDES_SUBREPORT,
                        target_ref=subreport.ref,
                        span=span,
                        evidence_snippet=path,
                        confidence=CONFIRMED,
                    )
                )
            if not literals and (element.text or "").strip():
                # A computed subreport path: real, but its target cannot be known
                # without running Java, so it is flagged rather than guessed.
                result.warnings.append(
                    AnalyzerMessage(
                        code="dynamic_subreport",
                        message="la ruta del subreporte es una expresión calculada",
                        severity=Severity.WARNING,
                        detail={"expression": _trim(element.text or "")},
                    )
                )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _local(tag: str) -> str:
    """Strip the XML namespace: ``{ns}field`` -> ``field``."""
    return tag.rsplit("}", 1)[-1]


def _iter_tag(root: ElementTree.Element, tag: str):
    for element in root.iter():
        if _local(element.tag) == tag:
            yield element


def _string_literals(text: str | None) -> list[str]:
    if not text:
        return []
    return [value for value in _STRING_LITERAL.findall(text) if value.strip()]


#: Extensions Jasper can actually render as an image.
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico", ".tif", ".tiff")


def _image_literals(text: str | None) -> list[str]:
    """String literals that name an image file, not arbitrary compared values."""
    return [
        value
        for value in _string_literals(text)
        if value.lower().endswith(_IMAGE_SUFFIXES)
    ]


def _is_absolute(path: str) -> bool:
    return path.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", path) is not None


def _stem(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def _content_line(content: str, fragment: str, fallback: int) -> int:
    """1-based line where ``fragment`` begins in ``content``.

    ``ElementTree`` discards source positions, so the text is located again by
    searching. Both sides are normalised to ``\\n`` first: XML parsers collapse
    ``\\r\\n`` to ``\\n`` as the specification requires, so on a Windows checkout
    the parsed text never matches the bytes on disk and every citation silently
    fell back to the enclosing tag's line. Normalising does not shift line
    numbers, since either ending is still one line break.

    A miss falls back to the caller's guess rather than failing the analysis — a
    slightly wrong citation is a bad answer, a crash is a lost file.
    """
    normalized = _normalize_newlines(content)
    probe = _normalize_newlines(fragment)[:60].strip()
    if not probe:
        return fallback
    index = normalized.find(probe)
    if index == -1:
        return fallback
    return normalized.count("\n", 0, index) + 1


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _line_text(content: str, line: int) -> str:
    """The text of one line, for use as an evidence snippet."""
    lines = content.splitlines()
    if 1 <= line <= len(lines):
        return lines[line - 1].strip()
    return ""


def _trim(text: str, limit: int = 400) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _line_index(content: str) -> dict[str, int]:
    """Map declarations to the line they appear on.

    ``ElementTree`` does not expose source positions, so the line is recovered by
    searching the raw text. It is used only for provenance display; a miss falls
    back to line 1 rather than failing the analysis.
    """
    index: dict[str, int] = {}
    for number, line in enumerate(content.splitlines(), start=1):
        for tag in ("field", "parameter", "variable"):
            match = re.search(rf"<{tag}\s+[^>]*name\s*=\s*\"([^\"]+)\"", line)
            if match:
                index.setdefault(f"{tag}:{match.group(1)}", number)
        if "<queryString" in line:
            index.setdefault("queryString", number)
        for match in _STRING_LITERAL.finditer(line):
            value = match.group(1)
            if "imageExpression" in line or _looks_like_image(value):
                index.setdefault(f"image:{value}", number)
            if "subreportExpression" in line or value.endswith(".jasper"):
                index.setdefault(f"subreport:{value}", number)
    return index


def _looks_like_image(value: str) -> bool:
    return value.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg"))


def _span_of_parse_error(error: ElementTree.ParseError) -> SourceSpan | None:
    line = getattr(error, "position", (None, None))[0]
    return SourceSpan(line, line) if isinstance(line, int) and line >= 1 else None


def _reject_doctype(content: str) -> AnalyzerMessage | None:
    """Refuse documents carrying a DTD.

    ``xml.etree`` does not fetch external entities, but it will happily expand
    internal ones — the "billion laughs" denial of service. HANA reads files it
    did not write, so a template with a DTD is declined outright instead of
    parsed. Refusing costs a warning; parsing could cost the process.
    """
    head = content[:4096].lower()
    if "<!doctype" in head or "<!entity" in head:
        return AnalyzerMessage(
            code="dtd_rejected",
            message=(
                "el JRXML declara un DTD o entidades; no se analiza por seguridad"
            ),
            severity=Severity.ERROR,
        )
    return None
