"""Materializing the entity graph, so the graph page stops re-deriving it.

The derivation itself is unchanged and still lives in routers/graph.py: entities
are nodes, and two entities are connected when a memory mentions both. What
changes is when it runs. Previously that was on every request, scanning the
whole entity store and recomputing every edge. Now it runs on write, and the
request reads rows.

These tables are a cache. The entity store remains the source of truth, so a
stale graph is a performance problem, not a wrong answer, and a full rebuild is
always one call away. That framing is what makes incremental refresh safe to
attempt at all.
"""

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from models import GraphEdge, GraphNode

logger = logging.getLogger(__name__)

SCAN_LIMIT = 10_000
# A memory mentioning N entities implies N*(N-1)/2 edges. Capped so one
# pathological memory cannot dominate the graph or the rebuild.
MAX_ENTITIES_PER_MEMORY = 20


def entity_key(entity_type: str, entity_id: str) -> str:
    return f"{entity_type}:{entity_id}"


def derive(rows: Iterable[Any]) -> tuple[dict[str, dict], dict[tuple[str, str], int]]:
    """Turn entity-store rows into nodes and weighted edges.

    Pure: takes rows, returns data. That is what lets the same function serve
    the full rebuild, the incremental refresh, and the tests without any of
    them needing a database.
    """
    nodes: dict[str, dict] = {}
    memory_to_entities: dict[str, list[str]] = defaultdict(list)

    for row in rows:
        entity_id = getattr(row, "id", None)
        payload = getattr(row, "payload", None) or {}
        label = payload.get("data")
        if not entity_id or not label:
            continue

        linked = [str(m) for m in (payload.get("linked_memory_ids") or [])]
        key = str(entity_id)
        nodes[key] = {
            "entity_key": key,
            "label": str(label),
            "entity_type": str(payload.get("entity_type") or "ENTITY"),
            "memory_count": len(linked),
        }
        for memory_id in linked:
            memory_to_entities[memory_id].append(key)

    weights: dict[tuple[str, str], int] = defaultdict(int)
    for entity_ids in memory_to_entities.values():
        # Sorted and truncated so the pair order is stable and the fan-out is
        # bounded. Stable order matters: (a,b) and (b,a) must be one edge.
        unique = sorted(set(entity_ids))[:MAX_ENTITIES_PER_MEMORY]
        for source, target in itertools.combinations(unique, 2):
            weights[(source, target)] += 1

    return nodes, dict(weights)


def rebuild_project(db: Session, project_id, rows: Iterable[Any]) -> dict[str, int]:
    """Replace this project's materialized graph wholesale.

    Delete-then-insert rather than a diff. The graph is a cache, the whole
    computation is already in memory, and a diff would be more code for a
    result that has to be identical anyway.
    """
    nodes, weights = derive(rows)

    degree: dict[str, int] = defaultdict(int)
    for source, target in weights:
        degree[source] += 1
        degree[target] += 1

    now = datetime.now(timezone.utc)

    db.execute(delete(GraphEdge).where(GraphEdge.project_id == project_id))
    db.execute(delete(GraphNode).where(GraphNode.project_id == project_id))

    db.bulk_save_objects(
        [
            GraphNode(
                project_id=project_id,
                entity_key=data["entity_key"],
                label=data["label"],
                entity_type=data["entity_type"],
                memory_count=data["memory_count"],
                degree=degree.get(data["entity_key"], 0),
                updated_at=now,
            )
            for data in nodes.values()
        ]
    )
    db.bulk_save_objects(
        [
            GraphEdge(
                project_id=project_id,
                source_key=source,
                target_key=target,
                weight=weight,
                updated_at=now,
            )
            for (source, target), weight in weights.items()
        ]
    )
    db.commit()

    return {"nodes": len(nodes), "edges": len(weights)}


def read(
    db: Session,
    project_id,
    *,
    limit: int = 2000,
    min_degree: int = 0,
    query: Optional[str] = None,
) -> dict[str, Any]:
    """Read the materialized graph, densest first.

    Ordering by degree is what makes a truncated graph still useful: if only
    part of it fits, the part worth seeing is the connected core, not an
    arbitrary alphabetical slice.
    """
    node_query = select(
        GraphNode.entity_key,
        GraphNode.label,
        GraphNode.entity_type,
        GraphNode.memory_count,
        GraphNode.degree,
    ).where(GraphNode.project_id == project_id)
    if min_degree:
        node_query = node_query.where(GraphNode.degree >= min_degree)
    if query:
        node_query = node_query.where(GraphNode.label.ilike(f"%{query}%"))

    total_nodes = db.scalar(
        select(func.count(GraphNode.entity_key)).where(GraphNode.project_id == project_id)
    ) or 0

    # Tuple queries, not ORM objects. Hydrating a few thousand mapped instances
    # to read four attributes off each was most of this endpoint's cost - 355ms
    # of a 380ms response, at 800 nodes and 5,000 edges.
    node_rows = db.execute(
        node_query.order_by(GraphNode.degree.desc(), GraphNode.memory_count.desc()).limit(limit)
    ).all()
    visible = {row[0] for row in node_rows}

    edge_rows = db.execute(
        select(GraphEdge.source_key, GraphEdge.target_key, GraphEdge.weight).where(
            GraphEdge.project_id == project_id
        )
    ).all()
    # Edges to nodes that did not survive the cut are dropped here rather than
    # sent and hidden: an edge pointing at a node the client never received is
    # the exact shape that crashed this page before.
    edges = [
        {"source": source, "target": target, "weight": weight, "relationship": "co-occurs"}
        for source, target, weight in edge_rows
        if source in visible and target in visible
    ]

    return {
        "nodes": [
            {
                "id": key,
                "label": label,
                "type": entity_type,
                "memories": memory_count,
                "degree": degree,
            }
            for key, label, entity_type, memory_count, degree in node_rows
        ],
        "edges": edges,
        # A count, not a flag: "showing 2,000 of 8,412" is actionable in a way
        # that a bare "truncated" badge is not.
        "truncated": total_nodes > len(node_rows),
        "total_nodes": total_nodes,
        "materialized": total_nodes > 0,
    }


def neighbourhood(db: Session, project_id, key: str, depth: int = 1) -> dict[str, Any]:
    """The subgraph around one node, for click-to-explore.

    Depth is capped at 2. Past that the "neighbourhood" of a well-connected
    node is most of the graph, which is not an expansion so much as a reload.
    """
    depth = max(1, min(2, depth))
    frontier = {key}
    seen = {key}
    collected: list[GraphEdge] = []

    for _ in range(depth):
        if not frontier:
            break
        rows = (
            db.execute(
                select(GraphEdge).where(
                    GraphEdge.project_id == project_id,
                    (GraphEdge.source_key.in_(frontier)) | (GraphEdge.target_key.in_(frontier)),
                )
            )
            .scalars()
            .all()
        )
        collected.extend(rows)
        next_frontier = set()
        for edge in rows:
            for candidate in (edge.source_key, edge.target_key):
                if candidate not in seen:
                    seen.add(candidate)
                    next_frontier.add(candidate)
        frontier = next_frontier

    node_rows = (
        db.execute(
            select(GraphNode).where(GraphNode.project_id == project_id, GraphNode.entity_key.in_(seen))
        )
        .scalars()
        .all()
    )
    present = {row.entity_key for row in node_rows}

    return {
        "nodes": [
            {
                "id": row.entity_key,
                "label": row.label,
                "type": row.entity_type,
                "memories": row.memory_count,
                "degree": row.degree,
            }
            for row in node_rows
        ],
        "edges": [
            {"source": e.source_key, "target": e.target_key, "weight": e.weight, "relationship": "co-occurs"}
            for e in {(e.source_key, e.target_key): e for e in collected}.values()
            if e.source_key in present and e.target_key in present
        ],
        "truncated": False,
        "total_nodes": len(node_rows),
        "materialized": True,
    }


def refresh_all(session_factory: Callable, memory_instance_fn: Callable, list_entities: Callable) -> dict:
    """Rebuild every project's graph. Backs the scheduled refresh and the admin call."""
    from models import Project

    summary: dict[str, Any] = {"projects": 0, "nodes": 0, "edges": 0}
    try:
        with session_factory() as db:
            projects = db.execute(select(Project)).scalars().all()
            for project in projects:
                try:
                    rows, error = list_entities({}, SCAN_LIMIT)
                    if error:
                        logger.warning("Graph rebuild skipped for %s: %s", project.id, error)
                        continue
                    counts = rebuild_project(db, project.id, rows)
                    summary["projects"] += 1
                    summary["nodes"] += counts["nodes"]
                    summary["edges"] += counts["edges"]
                except Exception:
                    db.rollback()
                    logger.exception("Graph rebuild failed for project %s", project.id)
    except Exception:
        logger.exception("Graph rebuild sweep failed")
    return summary


def is_stale(db: Session, project_id, max_age_seconds: int = 300) -> bool:
    """Whether the materialized graph is old enough to be worth refreshing."""
    newest = db.scalar(
        select(GraphNode.updated_at)
        .where(GraphNode.project_id == project_id)
        .order_by(GraphNode.updated_at.desc())
        .limit(1)
    )
    if newest is None:
        return True
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - newest).total_seconds() > max_age_seconds
