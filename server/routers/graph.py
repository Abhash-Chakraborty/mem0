"""Entity graph endpoint.

Mirrors how mem0 builds graph memory today: it extracts entities into a parallel
vector collection ({collection}_entities) and links memories that share an entity.
This router derives a node/edge graph from that entity store — entities are nodes,
and two entities are connected when they co-occur in the same memory. No external
graph database is involved (mem0 removed Neo4j/Memgraph/etc. upstream)."""

import itertools
from collections import defaultdict
from typing import Any, Optional

from auth import verify_auth
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from server_state import get_memory_instance

router = APIRouter(prefix="/graph", tags=["graph"])

SCAN_LIMIT = 5_000
# Cap how many entities a single memory may fan out into edges. A memory that
# mentions N entities would otherwise produce N*(N-1)/2 edges; this bounds it.
MAX_ENTITIES_PER_MEMORY = 20


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    memories: int = 0


class GraphEdge(BaseModel):
    source: str
    target: str
    relationship: str = "co-occurs"
    weight: int = 1


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def _scope_filters(user_id: Optional[str], agent_id: Optional[str], run_id: Optional[str]) -> dict[str, str]:
    return {k: v for k, v in {"user_id": user_id, "agent_id": agent_id, "run_id": run_id}.items() if v}


def _list_entities(filters: dict[str, str], limit: int) -> list[Any]:
    """Return raw entity rows from the entity store.

    The entity store is created lazily by the SDK and raises if the entities
    collection was never written (no memories added yet). Treat that as empty.
    """
    try:
        store = get_memory_instance().entity_store
        results = store.list(filters=filters or None, top_k=limit)
    except Exception:
        return []
    # vector_store.list may return [[rows]] or [rows] depending on the backend.
    if results and isinstance(results, list) and results and isinstance(results[0], list):
        return results[0]
    return results or []


@router.get("", response_model=GraphResponse)
def get_graph(
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = Query(SCAN_LIMIT, ge=1, le=SCAN_LIMIT),
    _auth=Depends(verify_auth),
):
    rows = _list_entities(_scope_filters(user_id, agent_id, run_id), limit)

    nodes: dict[str, GraphNode] = {}
    memory_to_entities: dict[str, list[str]] = defaultdict(list)

    for row in rows:
        entity_id = getattr(row, "id", None)
        payload = getattr(row, "payload", None) or {}
        label = payload.get("data")
        if not entity_id or not label:
            continue
        linked = payload.get("linked_memory_ids") or []
        nodes[entity_id] = GraphNode(
            id=entity_id,
            label=str(label),
            type=str(payload.get("entity_type") or "ENTITY"),
            memories=len(linked),
        )
        for memory_id in linked:
            memory_to_entities[memory_id].append(entity_id)

    edge_weights: dict[tuple[str, str], int] = defaultdict(int)
    for entity_ids in memory_to_entities.values():
        unique_ids = sorted(set(entity_ids))[:MAX_ENTITIES_PER_MEMORY]
        for source, target in itertools.combinations(unique_ids, 2):
            edge_weights[(source, target)] += 1

    edges = [
        GraphEdge(source=source, target=target, weight=weight)
        for (source, target), weight in edge_weights.items()
    ]

    return GraphResponse(nodes=list(nodes.values()), edges=edges)
