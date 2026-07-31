"""Transitive impact: what breaks if I change this?

``where_used`` and ``dependents`` answer one hop. Real impact is transitive —
changing ``UC_INSP_ENT.NETWGT`` reaches the queries that read it, the APEX item
bound to it, the page that item sits on, the report that prints it and the MOCA
pipeline that publishes it. Each of those is a hop, and stopping at the first
one answers a question nobody asked.

Three things make the answer trustworthy rather than merely long:

**Confidence degrades along the path.** A chain that crosses an inference at
0.9 cannot be presented as certainty. Every node carries the confidence of the
weakest link that reached it, and a flag saying whether any link was inferred.
A caller can then show the solid part without the speculative part
contaminating it.

**Containment is off by default.** ``FILE_CONTAINS_ENTITY`` joins everything to
everything: follow it and the impact of any one thing is the whole project. It
has to be asked for explicitly.

**Truncation is reported.** An incomplete impact presented as complete is worse
than no impact at all, so the report says when it hit its limit.

This is an over-approximation, and deliberately so. A report that reads a table
appears in the impact of every column of that table, even one it never prints.
Missing something that does break is far worse than listing something that does
not — but the path is always shown, so the reader can judge each one.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ..domain.types import RelationType

#: Structural edges. A file contains every entity found in it, so following
#: these makes every impact answer "the entire project".
CONTAINMENT_RELATIONS = (
    RelationType.FILE_CONTAINS_ENTITY.value,
    RelationType.ENTITY_DEFINED_IN_FILE.value,
)

DEFAULT_DEPTH = 4
DEFAULT_MAX_NODES = 500


@dataclass
class ImpactNode:
    """One thing affected by a change to the root, and how the change gets there."""

    entity: dict[str, Any]
    depth: int
    #: Entity ids from the root to here, inclusive. The reason a reader can
    #: judge a result instead of taking it on faith.
    path: list[str]
    #: Confidence of the weakest link in that path, not of the last edge.
    min_confidence: float
    inferred_in_path: bool
    #: The edge that brought this node in, and the file and line that prove it.
    relation_type: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "depth": self.depth,
            "path": self.path,
            "min_confidence": self.min_confidence,
            "inferred_in_path": self.inferred_in_path,
            "relation_type": self.relation_type,
            "evidence": self.evidence,
        }


@dataclass
class ImpactReport:
    root: dict[str, Any]
    nodes: list[ImpactNode]
    truncated: bool
    max_depth_reached: int
    by_type: dict[str, int]
    direction: str
    include_containment: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "nodes": [node.to_dict() for node in self.nodes],
            "truncated": self.truncated,
            "max_depth_reached": self.max_depth_reached,
            "by_type": self.by_type,
            "direction": self.direction,
            "include_containment": self.include_containment,
        }


def analyze_impact(
    connection: sqlite3.Connection,
    entity_id: str,
    *,
    depth: int = DEFAULT_DEPTH,
    direction: str = "incoming",
    include_containment: bool = False,
    max_nodes: int = DEFAULT_MAX_NODES,
    entity_of: Any,
) -> ImpactReport | None:
    """Walk the graph outward from one entity, breadth first.

    ``direction`` is ``"incoming"`` by default — "who depends on me", the
    question people mean by impact. ``"outgoing"`` reverses it into "what do I
    depend on".

    ``entity_of`` is the caller's entity lookup, passed in rather than imported
    so this module stays free of the query engine and can be tested alone.
    """
    root = entity_of(entity_id)
    if root is None:
        return None

    depth = max(1, depth)
    following_sources = direction == "incoming"

    # `visited` also terminates cycles: PL/SQL has mutual recursion, and
    # without this the walk never returns.
    visited: dict[str, ImpactNode] = {}
    truncated = False
    max_depth_reached = 0

    frontier: list[tuple[str, list[str], float, bool]] = [
        (entity_id, [entity_id], 1.0, False)
    ]

    for level in range(1, depth + 1):
        if not frontier or truncated:
            break

        by_id = {item[0]: item for item in frontier}
        rows = _edges(
            connection,
            list(by_id),
            following_sources=following_sources,
            include_containment=include_containment,
        )

        # A node can be reachable by several paths at the same depth. The one
        # that survives is the one a reader would trust most, which depends on
        # the weakest link of the whole path — not on this last edge alone.
        candidates: list[tuple[float, int, int, sqlite3.Row, list[str], bool]] = []
        for order, row in enumerate(rows):
            neighbour = row["other_id"]
            if neighbour == entity_id or neighbour in visited:
                continue
            _, path, weakest, inferred = by_id[row["anchor_id"]]
            node_inferred = inferred or row["status"] != "confirmed"
            candidates.append(
                (
                    min(weakest, row["confidence"]),
                    0 if not node_inferred else 1,
                    order,
                    row,
                    path,
                    node_inferred,
                )
            )
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))

        next_frontier: dict[str, tuple[str, list[str], float, bool]] = {}
        for node_confidence, _, _, row, path, node_inferred in candidates:
            neighbour = row["other_id"]
            if neighbour in visited:
                continue

            entity = _entity_dict(entity_of, neighbour)
            if entity is None:
                # An edge pointing at a row that is no longer there. Skipping it
                # is right; counting it against the budget would not be.
                continue

            if len(visited) >= max_nodes:
                truncated = True
                break

            node = ImpactNode(
                entity=entity,
                depth=level,
                path=[*path, neighbour],
                min_confidence=node_confidence,
                inferred_in_path=node_inferred,
                relation_type=row["relation_type"],
                evidence={
                    "file_path": row["evidence_path"],
                    "absolute_path": row["evidence_abs"],
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "snippet": row["evidence_snippet"],
                    "analyzer": row["analyzer"],
                    "confidence": row["confidence"],
                    "status": row["status"],
                },
            )
            visited[neighbour] = node
            max_depth_reached = max(max_depth_reached, level)
            next_frontier[neighbour] = (
                neighbour,
                node.path,
                node_confidence,
                node_inferred,
            )

        frontier = list(next_frontier.values())

    nodes = sorted(
        visited.values(),
        key=lambda node: (
            node.depth,
            node.entity["entity_type"],
            node.entity["normalized_name"],
        ),
    )

    return ImpactReport(
        root=_entity_dict(entity_of, entity_id),
        nodes=nodes,
        truncated=truncated,
        max_depth_reached=max_depth_reached,
        by_type=dict(Counter(node.entity["entity_type"] for node in nodes)),
        direction=direction,
        include_containment=include_containment,
    )


def _edges(
    connection: sqlite3.Connection,
    anchors: list[str],
    *,
    following_sources: bool,
    include_containment: bool,
) -> list[sqlite3.Row]:
    """Edges touching ``anchors``, labelled with which end was the anchor."""
    if not anchors:
        return []

    anchor_column = "target_entity_id" if following_sources else "source_entity_id"
    other_column = "source_entity_id" if following_sources else "target_entity_id"
    placeholders = ",".join("?" for _ in anchors)

    sql = f"""
        SELECT r.{anchor_column} AS anchor_id, r.{other_column} AS other_id,
               r.relation_type, r.confidence, r.status, r.analyzer,
               r.start_line, r.end_line, r.evidence_snippet,
               sf.relative_path AS evidence_path,
               sf.absolute_path AS evidence_abs
        FROM relationships r
        LEFT JOIN files sf ON sf.id = r.source_file_id
        WHERE r.{anchor_column} IN ({placeholders})
    """
    params: list[Any] = list(anchors)
    if not include_containment:
        excluded = ",".join("?" for _ in CONTAINMENT_RELATIONS)
        sql += f" AND r.relation_type NOT IN ({excluded})"
        params.extend(CONTAINMENT_RELATIONS)
    # Strongest evidence first, so a node reached by two paths keeps the one a
    # reader would trust.
    sql += " ORDER BY r.confidence DESC, r.relation_type"
    return connection.execute(sql, params).fetchall()


def _entity_dict(entity_of: Any, entity_id: str) -> dict[str, Any] | None:
    hit = entity_of(entity_id)
    return hit.to_dict() if hit is not None else None
