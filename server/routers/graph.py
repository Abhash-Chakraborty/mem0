"""Entity graph endpoint.

Mirrors how mem0 builds graph memory today: its v3 pipeline extracts entities
into a parallel vector collection ({collection}_entities) and links memories
that share an entity. This router derives a node/edge graph from that entity
store - entities are nodes, and two entities are connected when they co-occur in
the same memory.

This is mem0's CURRENT graph implementation: upstream mem0 removed the external
graph-database backends (Neo4j/Memgraph/etc.) in the v3 pipeline rewrite
(mem0ai>=2.0, PR #4805) and replaced them with this vector-store-backed entity
graph. So there is no separate graph DB to configure - the graph is "real" mem0
graph memory in the v3 sense, just derived from the entity store rather than a
property-graph database.

Entity extraction is powered by spaCy (the en_core_web_sm model). If that model
is missing, extraction silently yields nothing and the entity store stays empty.
To avoid a misleading "empty graph", every response carries a `status` and
`entity_extraction_available` so the dashboard can tell a genuinely empty graph
apart from a misconfigured one, and the server logs the reason."""

import itertools
import logging
from collections import defaultdict
from typing import Any, Literal, Optional

import graph_services
from db import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from server_state import get_memory_instance
from sqlalchemy.orm import Session
from tenancy import Scope, require_role, require_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])

SCAN_LIMIT = 5_000
# Cap how many entities a single memory may fan out into edges. A memory that
# mentions N entities would otherwise produce N*(N-1)/2 edges; this bounds it.
MAX_ENTITIES_PER_MEMORY = 20

# Identifies the kind of graph backing this endpoint, so the dashboard can be
# explicit that this is a derived entity graph, not an external graph DB.
GRAPH_SOURCE = "mem0_entity_store"

GraphStatus = Literal["ok", "empty", "extractor_unavailable", "error"]


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    memories: int = 0
    # Precomputed server-side: the client would otherwise walk every edge to
    # size a node, which is the O(n*e) pass that made this page slow.
    degree: int = 0


class GraphEdge(BaseModel):
    source: str
    target: str
    relationship: str = "co-occurs"
    weight: int = 1


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    # Diagnostics so the graph never silently returns an unexplained empty set.
    status: GraphStatus = "ok"
    detail: Optional[str] = None
    source: str = GRAPH_SOURCE
    entity_extraction_available: bool = True
    # A count rather than a bare flag: "showing 2,000 of 8,412" tells the reader
    # what they are missing, which "truncated" does not.
    truncated: bool = False
    total_nodes: int = 0


def _scope_filters(user_id: Optional[str], agent_id: Optional[str], run_id: Optional[str]) -> dict[str, str]:
    return {k: v for k, v in {"user_id": user_id, "agent_id": agent_id, "run_id": run_id}.items() if v}


def _entity_extraction_available() -> bool:
    """Best-effort check that mem0's spaCy entity extractor can run.

    The /graph data is only ever populated when entity extraction works, which
    requires spaCy plus the en_core_web_sm model. We check for the model package
    rather than loading the full pipeline so the probe stays cheap. Any failure
    (spaCy missing, model missing, import error) is treated as unavailable.
    """
    try:
        import spacy

        return bool(spacy.util.is_package("en_core_web_sm"))
    except Exception:
        return False


def _list_entities(filters: dict[str, str], limit: int) -> tuple[list[Any], Optional[str]]:
    """Return (rows, error) from the entity store.

    The entity store is created lazily by the SDK. A missing/never-written
    entities collection is normal before any memory is added and is reported as
    an empty result with no error. A genuine failure (DB down, bad config) is
    returned as an error string so the caller can surface it instead of
    pretending the graph is empty.
    """
    try:
        store = get_memory_instance().entity_store
        results = store.list(filters=filters or None, top_k=limit)
    except Exception as exc:  # noqa: BLE001 - we want to report any failure
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("Graph entity store query failed: %s", message, exc_info=True)
        # The SDK raises when the entities collection has simply never been
        # created yet (no memories with extractable entities). Treat the
        # "relation/table/collection does not exist" family as empty, not error.
        lowered = str(exc).lower()
        if any(token in lowered for token in ("does not exist", "no such table", "not found", "undefinedtable")):
            return [], None
        return [], message
    # vector_store.list may return [[rows]] or [rows] depending on the backend.
    if results and isinstance(results, list) and results and isinstance(results[0], list):
        return results[0], None
    return results or [], None


@router.get("", response_model=GraphResponse)
def get_graph(
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = Query(SCAN_LIMIT, ge=1, le=SCAN_LIMIT),
    min_degree: int = Query(0, ge=0, le=100),
    q: Optional[str] = Query(None, description="Filter nodes by label."),
    refresh: bool = Query(False, description="Force a rebuild before reading."),
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """The project's entity graph.

    Served from the materialized tables when they are warm, which is the whole
    point of phase 09 - the previous implementation rescanned the entity store
    and recomputed every edge on each request.

    An unscoped read is the materialized path. An entity-scoped one still
    derives live: the materialized graph is per project, and slicing it to one
    user would need a second set of tables for a query that is far rarer than
    the whole-project view.
    """
    extraction_available = _entity_extraction_available()
    filters = _scope_filters(user_id, agent_id, run_id)

    if not filters:
        try:
            if refresh or graph_services.is_stale(db, scope.project_id):
                rows, error = _list_entities({}, graph_services.SCAN_LIMIT)
                if error is None:
                    graph_services.rebuild_project(db, scope.project_id, rows)

            materialized = graph_services.read(
                db, scope.project_id, limit=limit, min_degree=min_degree, query=q
            )
            if materialized["materialized"]:
                return GraphResponse(
                    nodes=[GraphNode(**n) for n in materialized["nodes"]],
                    edges=[GraphEdge(**e) for e in materialized["edges"]],
                    status="ok",
                    detail=None,
                    source=GRAPH_SOURCE,
                    entity_extraction_available=extraction_available,
                    truncated=materialized["truncated"],
                    total_nodes=materialized["total_nodes"],
                )
        except Exception:
            # A cache that fails must fall through to the source of truth, not
            # take the page down with it.
            logger.warning("Materialized graph read failed; deriving live", exc_info=True)

    rows, error = _list_entities(filters, limit)

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

    node_list = list(nodes.values())
    status, detail = _classify(node_list, error, extraction_available)
    if status == "extractor_unavailable":
        logger.warning(
            "Graph is empty and the spaCy en_core_web_sm model is unavailable - "
            "entity extraction cannot run, so no graph can be built. Install the "
            "model in the image (python -m spacy download en_core_web_sm)."
        )

    return GraphResponse(
        nodes=node_list,
        edges=edges,
        status=status,
        detail=detail,
        source=GRAPH_SOURCE,
        entity_extraction_available=extraction_available,
    )


def _classify(
    nodes: list[GraphNode], error: Optional[str], extraction_available: bool
) -> tuple[GraphStatus, Optional[str]]:
    if nodes:
        # Data exists; report ok even if the extractor probe was pessimistic.
        return "ok", None
    if error:
        return "error", f"Graph storage query failed: {error}"
    if not extraction_available:
        return (
            "extractor_unavailable",
            "Entity extraction is unavailable (the spaCy en_core_web_sm model is "
            "not installed), so no graph can be built from your memories.",
        )
    return "empty", "No entities have been extracted from your memories yet."


@router.get("/nodes/{node_key:path}", response_model=GraphResponse)
def get_neighbourhood(
    node_key: str,
    depth: int = Query(1, ge=1, le=2),
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """The subgraph around one node, for click-to-explore.

    Separate from the main read because expanding a node should cost a small
    query, not a re-fetch of the whole graph with a client-side filter.
    """
    try:
        result = graph_services.neighbourhood(db, scope.project_id, node_key, depth)
    except Exception:
        raise HTTPException(status_code=503, detail="The graph could not be read.")

    if not result["nodes"]:
        raise HTTPException(status_code=404, detail="Node not found in the graph.")

    return GraphResponse(
        nodes=[GraphNode(**n) for n in result["nodes"]],
        edges=[GraphEdge(**e) for e in result["edges"]],
        status="ok",
        source=GRAPH_SOURCE,
        entity_extraction_available=True,
        truncated=False,
        total_nodes=result["total_nodes"],
    )


@router.post("/rebuild")
def rebuild_graph(
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Rebuild this project's materialized graph from the entity store.

    The repair hatch. The graph is a cache, so this exists for the case where
    it has drifted - and it is a plain rebuild rather than a diff because the
    whole computation is cheap enough to just redo.
    """
    rows, error = _list_entities({}, graph_services.SCAN_LIMIT)
    if error:
        raise HTTPException(status_code=503, detail=f"The entity store could not be read: {error}")

    counts = graph_services.rebuild_project(db, scope.project_id, rows)
    return {"rebuilt": True, **counts}
