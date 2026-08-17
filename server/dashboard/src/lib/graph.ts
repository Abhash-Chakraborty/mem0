import type { GraphEdge, GraphNode, GraphResponse } from "@/types/api";

/**
 * Coerce whatever came back from /graph into a shape the renderer can trust.
 *
 * The page previously did `[...graph.nodes]` on the raw response. `??` does not
 * protect that: when the body is an object without a `nodes` key — a proxy
 * error page served with 200, a gateway body, an older server build — the
 * fallback never fires, `graph.nodes` is undefined, and the spread throws
 * "is not iterable" during render. With no error boundary above it that became
 * a full-page "Application error", which is the production crash on
 * /dashboard/graph.
 *
 * Filtering by predicate rather than casting also removes the two downstream
 * throw paths: `n.type.toLowerCase()` and `n.label.length` on a node whose
 * fields are null.
 */

function isGraphNode(value: unknown): value is GraphNode {
  if (typeof value !== "object" || value === null) return false;
  const n = value as Record<string, unknown>;
  return (
    typeof n.id === "string" &&
    n.id.length > 0 &&
    typeof n.label === "string" &&
    typeof n.type === "string" &&
    typeof n.memories === "number" &&
    Number.isFinite(n.memories)
  );
}

function isGraphEdge(value: unknown): value is GraphEdge {
  if (typeof value !== "object" || value === null) return false;
  const e = value as Record<string, unknown>;
  return (
    typeof e.source === "string" &&
    typeof e.target === "string" &&
    typeof e.weight === "number" &&
    Number.isFinite(e.weight)
  );
}

export function normalizeGraph(raw: unknown): GraphResponse {
  const body = (typeof raw === "object" && raw !== null ? raw : {}) as Record<
    string,
    unknown
  >;

  const nodesOk = Array.isArray(body.nodes);
  const edgesOk = Array.isArray(body.edges);

  // A body carrying neither array is not an empty graph, it is a wrong
  // response. Saying so beats rendering "No graph yet" over a broken backend.
  const malformed = !nodesOk && !edgesOk;

  const nodes = nodesOk ? (body.nodes as unknown[]).filter(isGraphNode) : [];
  const edges = edgesOk ? (body.edges as unknown[]).filter(isGraphEdge) : [];

  const status = malformed
    ? "error"
    : ((body.status as GraphResponse["status"]) ?? "ok");

  const detail = malformed
    ? typeof body.detail === "string"
      ? body.detail
      : "The graph service returned an unexpected response. Check the API logs."
    : ((body.detail as string | null | undefined) ?? null);

  return {
    nodes,
    edges,
    status,
    detail,
    source: typeof body.source === "string" ? body.source : undefined,
    entity_extraction_available:
      typeof body.entity_extraction_available === "boolean"
        ? body.entity_extraction_available
        : undefined,
    truncated: body.truncated === true,
    total_nodes:
      typeof body.total_nodes === "number" && Number.isFinite(body.total_nodes)
        ? body.total_nodes
        : nodes.length,
  };
}

/** Drop edges whose endpoints are not both present in the visible node set. */
export function pruneEdges(
  edges: GraphEdge[],
  visibleIds: Set<string>,
): GraphEdge[] {
  return edges.filter(
    (e) => visibleIds.has(e.source) && visibleIds.has(e.target),
  );
}
