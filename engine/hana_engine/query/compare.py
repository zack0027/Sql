"""Comparing two analysed projects — DEV against PROD.

Compares the **graphs**, not the files. A text diff of two environments is
useless in practice: the files come back reordered, reformatted, with different
headers, and every line shows as changed. What actually matters is whether the
same things exist and whether they still relate the same way — whether a query
stopped reading a table, whether a report uses a field that no longer exists.

Entities compare by ``identity_key``, which is derived from *what a thing is*
(type, schema, container, normalised name) and not from the project it was found
in. The ``UNIQUE(project_id, identity_key)`` constraint scopes them inside the
table; the key itself carries no project, so it lines up across two of them
without any translation. Measured before relying on it: two analyses of the same
sources produce 47 of 47 identical keys.

Relationships compare by the same semantic key annotations use — source
identity, relation type, target identity — deliberately ignoring which file
proved the claim. Moving a query from one script to another does not change
what it says about the tables.

**The trap this module has to guard against.** Two projects laid out
differently share almost no relative paths, and since files and SQL statements
are identified by path, the comparison would report that everything appeared and
everything disappeared at once. That is not a finding, it is a mismatch of
inputs — so the overlap is measured, reported, and the caller is expected to say
so before showing a single row.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..domain.types import RelationType

#: Below this share of common file paths, the two projects are probably not the
#: same codebase and the differences are noise rather than news.
COMPARABLE_THRESHOLD = 0.5

#: Containment edges. An entity present on one side only brings its containment
#: edge with it, which restates the entity list instead of adding to it.
_STRUCTURAL = (
    RelationType.FILE_CONTAINS_ENTITY.value,
    RelationType.ENTITY_DEFINED_IN_FILE.value,
)


@dataclass
class SideSummary:
    project_id: str
    name: str
    root_path: str
    entities: int
    relationships: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "root_path": self.root_path,
            "entities": self.entities,
            "relationships": self.relationships,
        }


@dataclass
class ComparisonReport:
    left: SideSummary
    right: SideSummary

    #: Entities present in one side only, grouped by entity type.
    entities_only_left: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    entities_only_right: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    #: Claims present in one side only, grouped by relation type.
    relations_only_left: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    relations_only_right: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    shared_entities: int = 0
    shared_relations: int = 0

    #: Fraction of file paths the two projects have in common, and what it means.
    path_overlap: float = 0.0
    comparable: bool = True
    warning: str | None = None
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "entities_only_left": self.entities_only_left,
            "entities_only_right": self.entities_only_right,
            "relations_only_left": self.relations_only_left,
            "relations_only_right": self.relations_only_right,
            "shared_entities": self.shared_entities,
            "shared_relations": self.shared_relations,
            "path_overlap": self.path_overlap,
            "comparable": self.comparable,
            "warning": self.warning,
            "truncated": self.truncated,
        }


def compare_projects(
    connection: sqlite3.Connection,
    left_id: str,
    right_id: str,
    *,
    limit: int = 500,
) -> ComparisonReport | None:
    """Diff two analysed projects by their graphs."""
    left = _side(connection, left_id)
    right = _side(connection, right_id)
    if left is None or right is None:
        return None

    report = ComparisonReport(left=left, right=right)
    _check_comparability(connection, left_id, right_id, report)

    left_entities = _entities(connection, left_id)
    right_entities = _entities(connection, right_id)
    report.shared_entities = len(set(left_entities) & set(right_entities))

    truncated = False
    report.entities_only_left, cut = _grouped(
        [left_entities[key] for key in left_entities.keys() - right_entities.keys()],
        "entity_type",
        limit,
    )
    truncated |= cut
    report.entities_only_right, cut = _grouped(
        [right_entities[key] for key in right_entities.keys() - left_entities.keys()],
        "entity_type",
        limit,
    )
    truncated |= cut

    left_relations = _relations(connection, left_id)
    right_relations = _relations(connection, right_id)
    report.shared_relations = len(set(left_relations) & set(right_relations))

    report.relations_only_left, cut = _grouped(
        [left_relations[key] for key in left_relations.keys() - right_relations.keys()],
        "relation_type",
        limit,
    )
    truncated |= cut
    report.relations_only_right, cut = _grouped(
        [right_relations[key] for key in right_relations.keys() - left_relations.keys()],
        "relation_type",
        limit,
    )
    truncated |= cut

    report.truncated = truncated
    return report


def _side(connection: sqlite3.Connection, project_id: str) -> SideSummary | None:
    row = connection.execute(
        "SELECT id, name, root_path FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        return None
    entities = connection.execute(
        "SELECT COUNT(*) AS n FROM entities WHERE project_id = ?", (project_id,)
    ).fetchone()["n"]
    relationships = connection.execute(
        "SELECT COUNT(*) AS n FROM relationships WHERE project_id = ?", (project_id,)
    ).fetchone()["n"]
    return SideSummary(
        project_id=row["id"],
        name=row["name"],
        root_path=row["root_path"],
        entities=int(entities),
        relationships=int(relationships),
    )


def _check_comparability(
    connection: sqlite3.Connection,
    left_id: str,
    right_id: str,
    report: ComparisonReport,
) -> None:
    """Measure how much of the two file trees is the same shape.

    Without this, comparing two unrelated folders produces a report saying
    thousands of things appeared and thousands disappeared, which reads like a
    catastrophic difference between environments rather than what it is: the
    wrong two projects.
    """
    left_paths = _paths(connection, left_id)
    right_paths = _paths(connection, right_id)
    union = left_paths | right_paths
    if not union:
        report.path_overlap = 0.0
        report.comparable = False
        report.warning = "Ninguno de los dos proyectos tiene archivos analizados."
        return

    report.path_overlap = len(left_paths & right_paths) / len(union)
    if report.path_overlap >= COMPARABLE_THRESHOLD:
        return

    report.comparable = False
    report.warning = (
        f"Solo el {report.path_overlap:.0%} de las rutas coincide entre los dos "
        "proyectos. Puede que no sean dos versiones del mismo código, o que la "
        "carpeta raíz elegida esté a distinta altura en uno de ellos. Las "
        "diferencias de abajo dirán que casi todo cambió, y eso no sería un "
        "hallazgo sino una comparación mal planteada."
    )


def _paths(connection: sqlite3.Connection, project_id: str) -> set[str]:
    rows = connection.execute(
        "SELECT relative_path FROM files WHERE project_id = ? AND is_deleted = 0",
        (project_id,),
    ).fetchall()
    return {row["relative_path"] for row in rows}


def _entities(
    connection: sqlite3.Connection, project_id: str
) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT e.identity_key, e.entity_type, e.name, e.normalized_name,
               e.qualified_name, e.confidence, e.verification_status,
               e.start_line, f.relative_path
        FROM entities e
        LEFT JOIN files f ON f.id = e.source_file_id
        WHERE e.project_id = ?
        """,
        (project_id,),
    ).fetchall()
    return {
        row["identity_key"]: {
            "identity_key": row["identity_key"],
            "entity_type": row["entity_type"],
            "name": row["name"],
            "normalized_name": row["normalized_name"],
            "qualified_name": row["qualified_name"],
            "confidence": row["confidence"],
            "verification_status": row["verification_status"],
            "file_path": row["relative_path"],
            "start_line": row["start_line"],
        }
        for row in rows
    }


def _relations(
    connection: sqlite3.Connection, project_id: str
) -> dict[str, dict[str, Any]]:
    """Claims, keyed semantically so the proving file is irrelevant.

    A claim proved by two different files is one claim. Keeping the first
    sighting is enough: the key already says the two are the same statement.

    Structural edges are left out. A file contains every entity found in it, so
    an entity that exists on one side only drags its containment edge along —
    ten rows restating what the entity list said one screen earlier. Removing
    them turned a report where the real finding was buried into one where it is
    the first thing you read.
    """
    excluded = ",".join("?" for _ in _STRUCTURAL)
    rows = connection.execute(
        f"""
        SELECT s.identity_key AS source_key, r.relation_type,
               t.identity_key AS target_key,
               s.name AS source_name, t.name AS target_name,
               s.entity_type AS source_type, t.entity_type AS target_type,
               r.confidence, r.status, r.start_line,
               sf.relative_path AS evidence_path
        FROM relationships r
        JOIN entities s ON s.id = r.source_entity_id
        JOIN entities t ON t.id = r.target_entity_id
        LEFT JOIN files sf ON sf.id = r.source_file_id
        WHERE r.project_id = ? AND r.relation_type NOT IN ({excluded})
        """,
        (project_id, *_STRUCTURAL),
    ).fetchall()

    claims: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['source_key']}|{row['relation_type']}|{row['target_key']}"
        claims.setdefault(
            key,
            {
                "key": key,
                "relation_type": row["relation_type"],
                "source_name": row["source_name"],
                "source_type": row["source_type"],
                "target_name": row["target_name"],
                "target_type": row["target_type"],
                "confidence": row["confidence"],
                "status": row["status"],
                "file_path": row["evidence_path"],
                "start_line": row["start_line"],
            },
        )
    return claims


def _grouped(
    items: list[dict[str, Any]], key: str, limit: int
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    ordered = sorted(items, key=lambda item: (item[key], item.get("name") or item["key"]))
    truncated = len(ordered) > limit
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in ordered[:limit]:
        grouped.setdefault(item[key], []).append(item)
    return grouped, truncated
