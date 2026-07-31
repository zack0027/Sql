"""Deterministic queries over the knowledge graph.

This is the part of HANA that answers questions. Every answer here is computed
from stored facts by SQL — no model, no heuristics at query time, no guessing.
If the graph does not contain the evidence, the query returns nothing rather
than an invention.

Every result carries its provenance: the file, the exact lines, the fragment
that proves it, the analyzer that found it and how confident it was. A caller
can always ask "why do you say that?" and get an answer that opens a file at a
line.

The ten questions the product promises to answer without a language model:

1. ``where_used``            — ¿dónde se utiliza esta entidad?
2. ``dependents``            — ¿qué depende de esta entidad?
3. ``tables_read_by``        — ¿qué tablas lee esta consulta?
4. ``tables_written_by``     — ¿qué tablas modifica este proceso?
5. ``apex_items_in_file``    — ¿qué items APEX aparecen en este archivo?
6. ``reports_using_table``   — ¿qué reportes utilizan esta tabla?
7. ``images_of_report``      — ¿qué imágenes utiliza este reporte?
8. ``changes_since``         — ¿qué cambió desde el análisis anterior?
9. ``files_with_errors``     — ¿qué archivos presentan errores de análisis?
10. ``low_confidence``       — ¿qué entidades tienen baja confianza?

And the transitive one, which lives in :mod:`.impact` because it is a graph
walk rather than a query: ``impact`` — ¿qué se rompe si toco esto?
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ..domain.types import EntityType, RelationType
from .compare import ComparisonReport, compare_projects
from .impact import (
    DEFAULT_DEPTH,
    DEFAULT_MAX_NODES,
    ImpactReport,
    analyze_impact,
)

#: Relations that mean "this thing reads that table".
_READ_RELATIONS = (
    RelationType.QUERY_READS_TABLE.value,
    RelationType.REPORT_QUERIES_TABLE.value,
)

#: Relations that mean "this thing modifies that table".
_WRITE_RELATIONS = (
    RelationType.QUERY_WRITES_TABLE.value,
    RelationType.APEX_PROCESS_UPDATES_TABLE.value,
)

#: Structural edges. Useful for navigation, noise in a "where is this used?"
#: answer — a file containing an entity is not a *use* of it.
_STRUCTURAL_RELATIONS = (
    RelationType.FILE_CONTAINS_ENTITY.value,
    RelationType.ENTITY_DEFINED_IN_FILE.value,
)


@dataclass
class Evidence:
    """Why HANA believes something, in a form the UI can open."""

    file_path: str | None
    absolute_path: str | None
    start_line: int | None
    end_line: int | None
    snippet: str | None
    analyzer: str
    confidence: float
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EntityHit:
    """An entity, with just enough context to display it."""

    id: str
    entity_type: str
    name: str
    normalized_name: str
    qualified_name: str | None
    confidence: float
    verification_status: str
    file_path: str | None
    start_line: int | None

    @classmethod
    def of(cls, row: sqlite3.Row) -> EntityHit:
        return cls(
            id=row["id"],
            entity_type=row["entity_type"],
            name=row["name"],
            normalized_name=row["normalized_name"],
            qualified_name=row["qualified_name"],
            confidence=row["confidence"],
            verification_status=row["verification_status"],
            file_path=row["relative_path"] if "relative_path" in row.keys() else None,
            start_line=row["start_line"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UsageHit:
    """One place where an entity is used, and the proof."""

    entity: EntityHit
    relation_type: str
    direction: str  # "incoming" | "outgoing"
    evidence: Evidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity.to_dict(),
            "relation_type": self.relation_type,
            "direction": self.direction,
            "evidence": self.evidence.to_dict(),
        }


@dataclass
class GraphNode:
    entity: EntityHit
    depth: int

    def to_dict(self) -> dict[str, Any]:
        return {"entity": self.entity.to_dict(), "depth": self.depth}


@dataclass
class GraphEdge:
    source_id: str
    target_id: str
    relation_type: str
    confidence: float
    status: str
    evidence: Evidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "status": self.status,
            "evidence": self.evidence.to_dict(),
        }


@dataclass
class Neighborhood:
    """A slice of the graph around one entity, for progressive display."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "truncated": self.truncated,
        }


#: Kinds where "nothing refers to this" is a finding rather than a fact about
#: the shape of the graph.
#:
#: The test that decides membership: can an analyzer ever produce an edge
#: *into* this kind? Where the answer is no, every entity of that kind is
#: unreferenced by construction, and reporting them all is not information —
#: it is noise that buries the findings that matter. Measured, not assumed:
#: only these kinds are ever a target of a non-structural edge today.
#:
#: Excluded for that reason, each a different story:
#:
#: * ``ApexPage`` — pages are entry points; nothing in a project points at one.
#: * ``JsonProperty``, ``MocaCommand`` — structure of a file, not code anyone
#:   calls.
#: * ``OraclePackage`` — packages contain routines, nothing depends on the
#:   package itself. "A package nobody uses" is really "none of its routines is
#:   called", a different query.
#: * ``JasperReport`` — the encargo asked for "reports nobody references", and
#:   it cannot be answered honestly yet: no analyzer produces an edge into a
#:   report, so the answer would be every report in the project. It becomes
#:   answerable the day something links a launcher to its report.
#: * ``JavaScriptFunction``, ``PythonFunction`` — declared but never resolved as
#:   call targets, so the same applies.
#:
#: None of them is hidden: asking for a kind by name reaches any of them.
_REVIEWABLE_TYPES = (
    EntityType.ORACLE_TABLE.value,
    EntityType.ORACLE_VIEW.value,
    EntityType.ORACLE_COLUMN.value,
    EntityType.ORACLE_PROCEDURE.value,
    EntityType.ORACLE_FUNCTION.value,
    EntityType.APEX_ITEM.value,
)

_ENTITY_COLUMNS = """
    e.id, e.entity_type, e.name, e.normalized_name, e.qualified_name,
    e.confidence, e.verification_status, e.start_line, f.relative_path
"""

#: The same entity, located by the evidence that brought it into the answer
#: rather than by where it was first defined. For queries scoped to one file:
#: `MIN` picks the first mention in that file, and ignores relationships that
#: recorded no line. Requires `GROUP BY e.id` and a `sf` join on
#: `r.source_file_id`.
_EVIDENCE_ENTITY_COLUMNS = """
    e.id, e.entity_type, e.name, e.normalized_name, e.qualified_name,
    e.confidence, e.verification_status,
    MIN(r.start_line) AS start_line, sf.relative_path AS relative_path
"""

#: FTS5 treats these as operators; a user typing `UC_INSP_ENT.NUMCTL` means them
#: literally.
_FTS_SPECIAL = re.compile(r'["*():^\-]')


class QueryEngine:
    """Answers questions about a project's knowledge graph."""

    def __init__(
        self, connection: sqlite3.Connection, *, suite: str | None = None
    ) -> None:
        self.connection = connection
        #: Fingerprint of the analyzer suite currently installed. Given here so
        #: answers can say "this was produced by an older version" instead of
        #: reporting an absence the caller would read as a fact about the code.
        self.suite = suite

    # -- lookup -------------------------------------------------------------

    def search(
        self, project_id: str, text: str, *, limit: int = 50
    ) -> list[EntityHit]:
        """Full-text search over entity names, falling back to LIKE.

        FTS5 is used when the build supports it. The fallback is not a nicety:
        without it a SQLite compiled without FTS5 would make the whole search
        view silently return nothing.
        """
        term = text.strip()
        if not term:
            return []

        try:
            rows = self.connection.execute(
                f"""
                SELECT {_ENTITY_COLUMNS}
                FROM entities_fts x
                JOIN entities e ON e.rowid = x.rowid
                LEFT JOIN files f ON f.id = e.source_file_id
                WHERE entities_fts MATCH ? AND e.project_id = ?
                ORDER BY bm25(entities_fts), e.normalized_name
                LIMIT ?
                """,
                (_fts_query(term), project_id, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

        if not rows:
            rows = self.connection.execute(
                f"""
                SELECT {_ENTITY_COLUMNS}
                FROM entities e
                LEFT JOIN files f ON f.id = e.source_file_id
                WHERE e.project_id = ?
                  AND (e.normalized_name LIKE ? OR e.name LIKE ?
                       OR e.qualified_name LIKE ?)
                ORDER BY LENGTH(e.normalized_name), e.normalized_name
                LIMIT ?
                """,
                (project_id, f"%{term}%", f"%{term}%", f"%{term}%", limit),
            ).fetchall()

        return [EntityHit.of(row) for row in rows]

    def resolve(
        self,
        project_id: str,
        name: str,
        *,
        entity_type: EntityType | None = None,
    ) -> list[EntityHit]:
        """Find entities by exact name, ignoring case and quoting."""
        cleaned = name.strip().strip('"').upper()
        sql = f"""
            SELECT {_ENTITY_COLUMNS}
            FROM entities e
            LEFT JOIN files f ON f.id = e.source_file_id
            WHERE e.project_id = ?
              AND (UPPER(e.normalized_name) = ? OR UPPER(e.qualified_name) = ?)
        """
        params: list[Any] = [project_id, cleaned, cleaned]
        if entity_type is not None:
            sql += " AND e.entity_type = ?"
            params.append(entity_type.value)
        sql += " ORDER BY e.entity_type, e.normalized_name"
        return [
            EntityHit.of(row) for row in self.connection.execute(sql, params).fetchall()
        ]

    def get(self, entity_id: str) -> EntityHit | None:
        row = self.connection.execute(
            f"""
            SELECT {_ENTITY_COLUMNS}
            FROM entities e
            LEFT JOIN files f ON f.id = e.source_file_id
            WHERE e.id = ?
            """,
            (entity_id,),
        ).fetchone()
        return EntityHit.of(row) if row else None

    # -- 1. ¿Dónde se utiliza esta entidad? ---------------------------------

    def where_used(
        self, entity_id: str, *, include_structural: bool = False, limit: int = 200
    ) -> list[UsageHit]:
        """Every place that refers to this entity, in either direction.

        Structural edges (a file *containing* an entity) are excluded by default:
        they are true but they are not uses, and they would bury the real answer.
        """
        return self._related(
            entity_id,
            direction="both",
            include_structural=include_structural,
            limit=limit,
        )

    # -- 2. ¿Qué depende de esta entidad? / ¿de qué depende? ----------------

    def dependents(self, entity_id: str, *, limit: int = 200) -> list[UsageHit]:
        """Things that would break if this entity changed."""
        return self._related(entity_id, direction="incoming", limit=limit)

    def dependencies(self, entity_id: str, *, limit: int = 200) -> list[UsageHit]:
        """Things this entity relies on."""
        return self._related(entity_id, direction="outgoing", limit=limit)

    # -- 3 y 4. Tablas leídas y modificadas ---------------------------------

    def tables_read_by(self, entity_id: str, *, limit: int = 200) -> list[UsageHit]:
        return self._by_relations(entity_id, _READ_RELATIONS, "outgoing", limit)

    def tables_written_by(self, entity_id: str, *, limit: int = 200) -> list[UsageHit]:
        return self._by_relations(entity_id, _WRITE_RELATIONS, "outgoing", limit)

    def tables_of_file(
        self, project_id: str, relative_path: str, *, written: bool | None = None
    ) -> list[UsageHit]:
        """Tables read or written by everything in one file.

        The file-level question is the one people actually ask — "what does this
        script touch?" — and it spans every statement inside it.
        """
        relations = (
            _WRITE_RELATIONS
            if written is True
            else _READ_RELATIONS
            if written is False
            else _READ_RELATIONS + _WRITE_RELATIONS
        )
        placeholders = ",".join("?" for _ in relations)
        rows = self.connection.execute(
            f"""
            SELECT {_ENTITY_COLUMNS}, r.relation_type, r.confidence AS rel_confidence,
                   r.status AS rel_status, r.analyzer, r.start_line AS ev_start,
                   r.end_line AS ev_end, r.evidence_snippet,
                   sf.relative_path AS evidence_path, sf.absolute_path AS evidence_abs
            FROM relationships r
            JOIN entities e ON e.id = r.target_entity_id
            LEFT JOIN files f ON f.id = e.source_file_id
            JOIN files sf ON sf.id = r.source_file_id
            WHERE r.project_id = ? AND sf.relative_path = ?
              AND r.relation_type IN ({placeholders})
            ORDER BY e.normalized_name
            """,
            (project_id, relative_path, *relations),
        ).fetchall()
        return [self._usage(row, "outgoing") for row in rows]

    # -- 5. ¿Qué items APEX aparecen en este archivo? -----------------------

    def entities_in_file(
        self,
        project_id: str,
        relative_path: str,
        *,
        entity_type: EntityType | None = None,
    ) -> list[EntityHit]:
        """Entities a file produced, optionally narrowed to one type.

        The location reported is the evidence **inside the file asked about**,
        not the entity's canonical definition site. The distinction only shows
        when an entity appears in more than one file — ``P117_PRTNUM`` lives in
        two of the fixtures — and there the canonical site is the wrong answer
        twice over: it names a file the caller did not ask about, and clicking
        it opens somewhere the item may not even be mentioned.

        Where a file mentions the same entity several times, the first
        occurrence wins. It is the one a reader scrolling down meets first.
        """
        sql = f"""
            SELECT {_EVIDENCE_ENTITY_COLUMNS}
            FROM relationships r
            JOIN entities e ON e.id = r.target_entity_id
            JOIN files sf ON sf.id = r.source_file_id
            WHERE r.project_id = ? AND sf.relative_path = ?
        """
        params: list[Any] = [project_id, relative_path]
        if entity_type is not None:
            sql += " AND e.entity_type = ?"
            params.append(entity_type.value)
        sql += " GROUP BY e.id ORDER BY e.entity_type, e.normalized_name"
        return [
            EntityHit.of(row) for row in self.connection.execute(sql, params).fetchall()
        ]

    def apex_items_in_file(
        self, project_id: str, relative_path: str
    ) -> list[EntityHit]:
        return self.entities_in_file(
            project_id, relative_path, entity_type=EntityType.APEX_ITEM
        )

    # -- 6. ¿Qué reportes utilizan esta tabla? ------------------------------

    def reports_using_table(self, entity_id: str) -> list[UsageHit]:
        rows = self.connection.execute(
            f"""
            SELECT {_ENTITY_COLUMNS}, r.relation_type, r.confidence AS rel_confidence,
                   r.status AS rel_status, r.analyzer, r.start_line AS ev_start,
                   r.end_line AS ev_end, r.evidence_snippet,
                   sf.relative_path AS evidence_path, sf.absolute_path AS evidence_abs
            FROM relationships r
            JOIN entities e ON e.id = r.source_entity_id
            LEFT JOIN files f ON f.id = e.source_file_id
            LEFT JOIN files sf ON sf.id = r.source_file_id
            WHERE r.target_entity_id = ? AND e.entity_type = ?
            ORDER BY e.normalized_name
            """,
            (entity_id, EntityType.JASPER_REPORT.value),
        ).fetchall()
        return [self._usage(row, "incoming") for row in rows]

    # -- 7. ¿Qué imágenes utiliza este reporte? -----------------------------

    def images_of_report(self, entity_id: str) -> list[UsageHit]:
        return self._by_relations(
            entity_id, (RelationType.REPORT_REFERENCES_IMAGE.value,), "outgoing", 200
        )

    # -- 8. ¿Qué cambió desde el análisis anterior? -------------------------

    def changes_since(
        self, project_id: str, *, run_id: str | None = None
    ) -> dict[str, Any]:
        """File-level changes recorded by a run, defaulting to the latest.

        Reads ``file_versions``, which is append-only, so the answer survives
        later analyses instead of being overwritten by them.
        """
        if run_id is None:
            row = self.connection.execute(
                "SELECT id FROM analysis_runs WHERE project_id = ?"
                " ORDER BY started_at DESC, id DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if row is None:
                return {"run_id": None, "changes": []}
            run_id = row["id"]

        rows = self.connection.execute(
            """
            SELECT v.change_kind, v.content_hash, v.created_at,
                   f.relative_path, f.absolute_path, f.detected_type
            FROM file_versions v
            JOIN files f ON f.id = v.file_id
            WHERE v.analysis_run_id = ?
            ORDER BY v.change_kind, f.relative_path
            """,
            (run_id,),
        ).fetchall()

        return {
            "run_id": run_id,
            "changes": [
                {
                    "change_kind": row["change_kind"],
                    "relative_path": row["relative_path"],
                    "absolute_path": row["absolute_path"],
                    "detected_type": row["detected_type"],
                    "content_hash": row["content_hash"],
                    "observed_at": row["created_at"],
                }
                for row in rows
            ],
        }

    # -- 9. ¿Qué archivos presentan errores de análisis? --------------------

    def files_with_errors(
        self, project_id: str, *, severity: str | None = None
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT f.relative_path, f.absolute_path, a.severity, a.code,
                   a.message, a.analyzer, a.created_at
            FROM analysis_errors a
            LEFT JOIN files f ON f.id = a.file_id
            WHERE a.project_id = ?
        """
        params: list[Any] = [project_id]
        if severity is not None:
            sql += " AND a.severity = ?"
            params.append(severity)
        sql += " ORDER BY a.severity DESC, f.relative_path, a.code"

        return [
            {
                "relative_path": row["relative_path"],
                "absolute_path": row["absolute_path"],
                "severity": row["severity"],
                "code": row["code"],
                "message": row["message"],
                "analyzer": row["analyzer"],
                "observed_at": row["created_at"],
            }
            for row in self.connection.execute(sql, params).fetchall()
        ]

    # -- 10. ¿Qué entidades tienen baja confianza? --------------------------

    def low_confidence(
        self, project_id: str, *, threshold: float = 0.8, limit: int = 200
    ) -> list[EntityHit]:
        """Knowledge that deserves a human look, weakest first."""
        rows = self.connection.execute(
            f"""
            SELECT {_ENTITY_COLUMNS}
            FROM entities e
            LEFT JOIN files f ON f.id = e.source_file_id
            WHERE e.project_id = ? AND e.confidence < ?
            ORDER BY e.confidence ASC, e.normalized_name
            LIMIT ?
            """,
            (project_id, threshold, limit),
        ).fetchall()
        return [EntityHit.of(row) for row in rows]

    # -- candidates for review ----------------------------------------------

    def orphans(
        self,
        project_id: str,
        *,
        entity_type: EntityType | None = None,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        """Entities nothing in the project refers to.

        Columns nobody reads, reports nobody references, APEX items with no use,
        procedures nobody calls. Useful — and dangerous to phrase carelessly.

        These are **candidates to review**, never "safe to delete". Absence of
        evidence is not evidence of absence: anything invoked dynamically, from
        a scheduler, from another application, or from code outside the analysed
        folder is invisible to a static reader. The caller is expected to say so
        on screen; the ``caveat`` field carries the wording so every surface says
        the same thing.

        Structural edges are ignored on purpose. Every entity is contained by
        its file, so counting that as a reference would find nothing at all.

        Only the kinds in :data:`_REVIEWABLE_TYPES` are reported unless one is
        asked for by name. Nothing is hidden — ``entity_type`` reaches any kind
        — but a JSON property or a MOCA pipeline segment is never referenced by
        anything, by construction, so including them turns a list of two real
        findings into a list of thirty-seven where nobody spots the two.
        """
        placeholders = ",".join("?" for _ in _STRUCTURAL_RELATIONS)
        sql = f"""
            SELECT {_ENTITY_COLUMNS}
            FROM entities e
            LEFT JOIN files f ON f.id = e.source_file_id
            WHERE e.project_id = ?
              AND NOT EXISTS (
                    SELECT 1 FROM relationships r
                    WHERE r.target_entity_id = e.id
                      AND r.relation_type NOT IN ({placeholders})
              )
        """
        params: list[Any] = [project_id, *_STRUCTURAL_RELATIONS]
        if entity_type is not None:
            sql += " AND e.entity_type = ?"
            params.append(entity_type.value)
        else:
            kinds = ",".join("?" for _ in _REVIEWABLE_TYPES)
            sql += f" AND e.entity_type IN ({kinds})"
            params.extend(_REVIEWABLE_TYPES)
        sql += " ORDER BY e.entity_type, e.normalized_name LIMIT ?"
        params.append(limit)

        rows = self.connection.execute(sql, params).fetchall()
        return [EntityHit.of(row).to_dict() for row in rows]

    def orphan_report(
        self, project_id: str, *, limit: int = 300
    ) -> dict[str, Any]:
        """:meth:`orphans` grouped by kind, with the caveat attached."""
        found = self.orphans(project_id, limit=limit)
        by_type: dict[str, list[dict[str, Any]]] = {}
        for hit in found:
            by_type.setdefault(hit["entity_type"], []).append(hit)
        return {
            "total": len(found),
            "by_type": by_type,
            "truncated": len(found) >= limit,
            "caveat": (
                "Candidatos a revisar, no cosas que se puedan borrar. HANA lee "
                "el código de forma estática: lo que se invoca dinámicamente, "
                "desde un planificador, desde otra aplicación o desde fuera de "
                "la carpeta analizada, no lo ve."
            ),
        }

    # -- entity-relationship model ------------------------------------------

    def joined_with(self, entity_id: str) -> list[str]:
        """Tables that share a join condition with this one, in either direction."""
        rows = self.connection.execute(
            """
            SELECT source_entity_id, target_entity_id FROM relationships
            WHERE relation_type = ?
              AND (source_entity_id = ? OR target_entity_id = ?)
            """,
            (RelationType.TABLE_JOINS_TABLE.value, entity_id, entity_id),
        ).fetchall()

        partners = {row["source_entity_id"] for row in rows}
        partners |= {row["target_entity_id"] for row in rows}
        partners.discard(entity_id)
        return sorted(partners)

    def er_model(
        self,
        project_id: str,
        *,
        table_ids: Sequence[str] | None = None,
        focus_id: str | None = None,
    ) -> dict[str, Any]:
        """Tables, their columns, and the joins that relate them.

        Assembled entirely from what the SQL said. The links come from join
        conditions, not from declared foreign keys — HANA never connects to
        Oracle — so the result says so and must not be presented as the
        database's schema. It is the schema *as the code uses it*, which is
        often the more useful picture and occasionally a different one.

        ``focus_id`` narrows the diagram to one table **and the tables it joins
        to**. Narrowing to the table alone would be useless: a link needs both of
        its ends present, so a single-table diagram is always a box on its own,
        which says "this table relates to nothing" — the opposite of the truth.
        """
        if focus_id is not None:
            table_ids = [focus_id, *self.joined_with(focus_id)]

        params: list[Any] = [project_id, EntityType.ORACLE_TABLE.value]
        sql = f"""
            SELECT {_ENTITY_COLUMNS}
            FROM entities e
            LEFT JOIN files f ON f.id = e.source_file_id
            WHERE e.project_id = ? AND e.entity_type = ?
        """
        if table_ids:
            placeholders = ",".join("?" for _ in table_ids)
            sql += f" AND e.id IN ({placeholders})"
            params.extend(table_ids)
        sql += " ORDER BY e.normalized_name"

        tables = [EntityHit.of(row) for row in self.connection.execute(sql, params)]
        if not tables:
            return {"tables": [], "links": [], "derived_from": "join_conditions"}

        by_name = {table.normalized_name.upper(): table for table in tables}
        identifiers = [table.id for table in tables]
        wanted = ",".join("?" for _ in identifiers)

        column_rows = self.connection.execute(
            """
            SELECT id, name, normalized_name, qualified_name, confidence
            FROM entities
            WHERE project_id = ? AND entity_type = ?
            ORDER BY normalized_name
            """,
            (project_id, EntityType.ORACLE_COLUMN.value),
        ).fetchall()

        # A column's owner survives into the row only through its qualified
        # name, so that is what scopes it back to a table.
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in column_rows:
            owner, _, _ = (row["qualified_name"] or "").partition(".")
            if owner and owner.upper() in by_name:
                grouped.setdefault(owner.upper(), []).append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "normalized_name": row["normalized_name"],
                        "confidence": row["confidence"],
                    }
                )

        link_rows = self.connection.execute(
            f"""
            SELECT r.source_entity_id, r.target_entity_id, r.metadata_json,
                   r.confidence, r.status, r.analyzer, r.start_line, r.end_line,
                   r.evidence_snippet,
                   sf.relative_path AS evidence_path,
                   sf.absolute_path AS evidence_abs
            FROM relationships r
            LEFT JOIN files sf ON sf.id = r.source_file_id
            WHERE r.project_id = ? AND r.relation_type = ?
              AND r.source_entity_id IN ({wanted})
              AND r.target_entity_id IN ({wanted})
            """,
            (
                project_id,
                RelationType.TABLE_JOINS_TABLE.value,
                *identifiers,
                *identifiers,
            ),
        ).fetchall()

        links: list[dict[str, Any]] = []
        for row in link_rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            links.append(
                {
                    "source_id": row["source_entity_id"],
                    "target_id": row["target_entity_id"],
                    "left_column": metadata.get("left_column"),
                    "right_column": metadata.get("right_column"),
                    "confidence": row["confidence"],
                    "status": row["status"],
                    "evidence": Evidence(
                        file_path=row["evidence_path"],
                        absolute_path=row["evidence_abs"],
                        start_line=row["start_line"],
                        end_line=row["end_line"],
                        snippet=row["evidence_snippet"],
                        analyzer=row["analyzer"],
                        confidence=row["confidence"],
                        status=row["status"],
                    ).to_dict(),
                }
            )

        return {
            "tables": [
                {**table.to_dict(), "columns": grouped.get(table.normalized_name.upper(), [])}
                for table in tables
            ],
            "links": links,
            # Stated in the payload so no caller can mistake this for the schema.
            "derived_from": "join_conditions",
        }

    # -- report structure ---------------------------------------------------

    def report_structure(self, entity_id: str) -> dict[str, Any] | None:
        """The bands of a Jasper report and what each one draws.

        Read from what the analyzer recorded, not by parsing the file again: a
        preview built from a second reading could disagree with the graph, and
        then neither could be trusted.
        """
        row = self.connection.execute(
            "SELECT id, name, entity_type, metadata_json, source_file_id"
            " FROM entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if row is None or row["entity_type"] != EntityType.JASPER_REPORT.value:
            return None

        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}

        file_row = (
            self.connection.execute(
                "SELECT relative_path, absolute_path, analyzed_by FROM files"
                " WHERE id = ?",
                (row["source_file_id"],),
            ).fetchone()
            if row["source_file_id"]
            else None
        )
        analyzed_by = file_row["analyzed_by"] if file_row else None

        return {
            "id": row["id"],
            "name": row["name"],
            "file_path": file_row["relative_path"] if file_row else None,
            "absolute_path": file_row["absolute_path"] if file_row else None,
            "bands": metadata.get("bands", []),
            "analyzed_by": analyzed_by,
            # Without this an empty preview is indistinguishable from a report
            # that genuinely has no bands, and the interface would blame the
            # file for what is really an out-of-date reading of it.
            "stale": self.suite is not None and analyzed_by != self.suite,
        }

    # -- freshness ----------------------------------------------------------

    def freshness(self, project_id: str) -> dict[str, Any]:
        """How much of this project's knowledge predates the running analyzers.

        The pipeline already re-reads these files on the next run; this exists so
        the interface can say so *before* the user goes looking for something
        that was never extracted.
        """
        rows = self.connection.execute(
            "SELECT analyzed_by, COUNT(*) AS n FROM files"
            " WHERE project_id = ? AND analysis_status = 'analyzed'"
            "   AND is_deleted = 0"
            " GROUP BY analyzed_by",
            (project_id,),
        ).fetchall()

        analyzed = sum(row["n"] for row in rows)
        stale = sum(row["n"] for row in rows if row["analyzed_by"] != self.suite)
        return {
            "suite": self.suite,
            "analyzed": analyzed,
            # NULL counts as stale: knowledge from before the column existed was
            # produced by an analyzer whose version nobody recorded.
            "stale": stale if self.suite is not None else 0,
            "by_suite": {
                (row["analyzed_by"] or "desconocida"): row["n"] for row in rows
            },
        }

    # -- graph navigation ---------------------------------------------------

    def neighborhood(
        self, entity_id: str, *, depth: int = 1, max_nodes: int = 150
    ) -> Neighborhood:
        """Expand outward from one entity, breadth first.

        Bounded on purpose. A table used by four hundred scripts would otherwise
        return a hairball no one can read, and the UI is meant to expand on
        demand rather than load a whole project at once.
        """
        result = Neighborhood()
        seen: dict[str, int] = {}
        frontier = [entity_id]

        root = self.get(entity_id)
        if root is None:
            return result
        seen[entity_id] = 0
        result.nodes.append(GraphNode(root, 0))

        for level in range(1, max(1, depth) + 1):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = self.connection.execute(
                f"""
                SELECT r.source_entity_id, r.target_entity_id, r.relation_type,
                       r.confidence, r.status, r.analyzer, r.start_line, r.end_line,
                       r.evidence_snippet,
                       sf.relative_path AS evidence_path,
                       sf.absolute_path AS evidence_abs
                FROM relationships r
                LEFT JOIN files sf ON sf.id = r.source_file_id
                WHERE r.source_entity_id IN ({placeholders})
                   OR r.target_entity_id IN ({placeholders})
                """,
                (*frontier, *frontier),
            ).fetchall()

            next_frontier: list[str] = []
            for row in rows:
                result.edges.append(
                    GraphEdge(
                        source_id=row["source_entity_id"],
                        target_id=row["target_entity_id"],
                        relation_type=row["relation_type"],
                        confidence=row["confidence"],
                        status=row["status"],
                        evidence=Evidence(
                            file_path=row["evidence_path"],
                            absolute_path=row["evidence_abs"],
                            start_line=row["start_line"],
                            end_line=row["end_line"],
                            snippet=row["evidence_snippet"],
                            analyzer=row["analyzer"],
                            confidence=row["confidence"],
                            status=row["status"],
                        ),
                    )
                )
                for side in (row["source_entity_id"], row["target_entity_id"]):
                    if side in seen:
                        continue
                    if len(seen) >= max_nodes:
                        result.truncated = True
                        continue
                    seen[side] = level
                    next_frontier.append(side)

            for node_id in next_frontier:
                hit = self.get(node_id)
                if hit is not None:
                    result.nodes.append(GraphNode(hit, seen[node_id]))
            frontier = next_frontier

        # An edge whose far end was cut by the node budget would dangle.
        known = {node.entity.id for node in result.nodes}
        result.edges = [
            edge
            for edge in result.edges
            if edge.source_id in known and edge.target_id in known
        ]
        return result

    # -- ¿Qué se rompe si toco esto? ----------------------------------------

    def impact(
        self,
        entity_id: str,
        *,
        depth: int = DEFAULT_DEPTH,
        direction: str = "incoming",
        include_containment: bool = False,
        max_nodes: int = DEFAULT_MAX_NODES,
    ) -> ImpactReport | None:
        """Everything a change to this entity could reach. See :mod:`.impact`."""
        return analyze_impact(
            self.connection,
            entity_id,
            depth=depth,
            direction=direction,
            include_containment=include_containment,
            max_nodes=max_nodes,
            entity_of=self.get,
        )

    # -- ¿En qué se diferencian dos entornos? -------------------------------

    def compare(
        self, left_project_id: str, right_project_id: str, *, limit: int = 500
    ) -> ComparisonReport | None:
        """Diff two analysed projects by their graphs. See :mod:`.compare`."""
        return compare_projects(
            self.connection, left_project_id, right_project_id, limit=limit
        )

    # -- internals ----------------------------------------------------------

    def _related(
        self,
        entity_id: str,
        *,
        direction: str,
        include_structural: bool = False,
        limit: int = 200,
    ) -> list[UsageHit]:
        clauses = {
            "incoming": "r.target_entity_id = ?",
            "outgoing": "r.source_entity_id = ?",
        }
        results: list[UsageHit] = []

        for way in ("incoming", "outgoing") if direction == "both" else (direction,):
            other = (
                "r.source_entity_id" if way == "incoming" else "r.target_entity_id"
            )
            sql = f"""
                SELECT {_ENTITY_COLUMNS}, r.relation_type, r.confidence AS rel_confidence,
                       r.status AS rel_status, r.analyzer, r.start_line AS ev_start,
                       r.end_line AS ev_end, r.evidence_snippet,
                       sf.relative_path AS evidence_path,
                       sf.absolute_path AS evidence_abs
                FROM relationships r
                JOIN entities e ON e.id = {other}
                LEFT JOIN files f ON f.id = e.source_file_id
                LEFT JOIN files sf ON sf.id = r.source_file_id
                WHERE {clauses[way]}
            """
            params: list[Any] = [entity_id]
            if not include_structural:
                placeholders = ",".join("?" for _ in _STRUCTURAL_RELATIONS)
                sql += f" AND r.relation_type NOT IN ({placeholders})"
                params.extend(_STRUCTURAL_RELATIONS)
            sql += " ORDER BY r.confidence DESC, e.normalized_name LIMIT ?"
            params.append(limit)

            results.extend(
                self._usage(row, way)
                for row in self.connection.execute(sql, params).fetchall()
            )

        return results

    def _by_relations(
        self,
        entity_id: str,
        relations: Sequence[str],
        direction: str,
        limit: int,
    ) -> list[UsageHit]:
        column = (
            "r.source_entity_id" if direction == "outgoing" else "r.target_entity_id"
        )
        other = (
            "r.target_entity_id" if direction == "outgoing" else "r.source_entity_id"
        )
        placeholders = ",".join("?" for _ in relations)
        rows = self.connection.execute(
            f"""
            SELECT {_ENTITY_COLUMNS}, r.relation_type, r.confidence AS rel_confidence,
                   r.status AS rel_status, r.analyzer, r.start_line AS ev_start,
                   r.end_line AS ev_end, r.evidence_snippet,
                   sf.relative_path AS evidence_path, sf.absolute_path AS evidence_abs
            FROM relationships r
            JOIN entities e ON e.id = {other}
            LEFT JOIN files f ON f.id = e.source_file_id
            LEFT JOIN files sf ON sf.id = r.source_file_id
            WHERE {column} = ? AND r.relation_type IN ({placeholders})
            ORDER BY e.normalized_name
            LIMIT ?
            """,
            (entity_id, *relations, limit),
        ).fetchall()
        return [self._usage(row, direction) for row in rows]

    @staticmethod
    def _usage(row: sqlite3.Row, direction: str) -> UsageHit:
        return UsageHit(
            entity=EntityHit.of(row),
            relation_type=row["relation_type"],
            direction=direction,
            evidence=Evidence(
                file_path=row["evidence_path"],
                absolute_path=row["evidence_abs"],
                start_line=row["ev_start"],
                end_line=row["ev_end"],
                snippet=row["evidence_snippet"],
                analyzer=row["analyzer"],
                confidence=row["rel_confidence"],
                status=row["rel_status"],
            ),
        )


def _fts_query(text: str) -> str:
    """Turn user text into an FTS5 query that means what they typed.

    Identifiers like ``UC_INSP_ENT.NUMCTL`` contain characters FTS5 reads as
    operators. Each word is quoted so it is matched literally, and a trailing
    ``*`` makes the last word a prefix so search works while typing.
    """
    words = [word for word in _FTS_SPECIAL.sub(" ", text).split() if word]
    if not words:
        return '""'
    quoted = [f'"{word}"' for word in words[:-1]]
    quoted.append(f'"{words[-1]}"*')
    return " ".join(quoted)


__all__ = [
    "QueryEngine",
    "EntityHit",
    "UsageHit",
    "Evidence",
    "Neighborhood",
    "GraphNode",
    "GraphEdge",
]
