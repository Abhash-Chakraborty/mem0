"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, RefreshCw, Share2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { GraphCanvas } from "@/components/graph/graph-canvas";
import { CopyInline } from "@/components/shared/copy-inline";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS, GRAPH_ENDPOINTS } from "@/utils/api-endpoints";
import { useApiQuery } from "@/hooks/use-api-query";
import { normalizeGraph, pruneEdges } from "@/lib/graph";
import { getErrorMessage } from "@/lib/error-message";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { Entity, EntityType, GraphNode, GraphResponse } from "@/types/api";

// Colours per entity_type produced by mem0's built-in entity extraction.
const TYPE_COLORS: Record<string, string> = {
  PROPER: "#7c3aed",
  QUOTED: "#0ea5e9",
  COMPOUND: "#f59e0b",
  NOUN: "#10b981",
  ENTITY: "#6b7280",
};

const SCOPE_FIELD: Record<Exclude<EntityType, "app">, string> = {
  user: "user_id",
  agent: "agent_id",
  run: "run_id",
};

// Two thousand nodes is where canvas plus a quadtree layout still holds an
// interactive frame rate. The server sends the densest slice, so a cut graph is
// still the connected core rather than an arbitrary alphabetical one.
const MAX_NODES = 2000;

function colorFor(type: string): string {
  return TYPE_COLORS[type] ?? TYPE_COLORS.ENTITY;
}

export default function GraphPage() {
  const { can } = useScope();

  const [scopeType, setScopeType] = useState<Exclude<EntityType, "app"> | "">(
    "",
  );
  const [scopeId, setScopeId] = useState("");
  const [search, setSearch] = useState("");
  const [minDegree, setMinDegree] = useState(0);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [isolate, setIsolate] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  const entitiesQuery = useApiQuery<Entity[]>(
    async () => (await api.get(ENTITY_ENDPOINTS.BASE)).data ?? [],
    { errorToast: "Failed to load entities", initialData: [] },
  );

  const graphQuery = useApiQuery<GraphResponse>(
    async () => {
      const params: Record<string, string | number> = { limit: MAX_NODES };
      if (scopeType && scopeId) params[SCOPE_FIELD[scopeType]] = scopeId;
      if (minDegree > 0) params.min_degree = minDegree;
      const res = await api.get<unknown>(GRAPH_ENDPOINTS.BASE, { params });
      return normalizeGraph(res.data);
    },
    {
      errorToast: "Failed to load graph",
      initialData: { nodes: [], edges: [] },
      deps: [scopeType, scopeId, minDegree],
    },
  );

  const graph = graphQuery.data ?? { nodes: [], edges: [] };

  const presentTypes = useMemo(() => {
    const seen = new Set<string>();
    for (const node of graph.nodes) seen.add(node.type);
    return [...seen].sort();
  }, [graph.nodes]);

  const visibleNodes = useMemo(
    () => graph.nodes.filter((n) => !hiddenTypes.has(n.type)),
    [graph.nodes, hiddenTypes],
  );

  const visibleIds = useMemo(
    () => new Set(visibleNodes.map((n) => n.id)),
    [visibleNodes],
  );

  const edges = useMemo(
    () => pruneEdges(graph.edges, visibleIds),
    [graph.edges, visibleIds],
  );

  /** Which nodes stay lit: a search match, or the selection's neighbourhood. */
  const highlighted = useMemo(() => {
    const needle = search.trim().toLowerCase();

    if (isolate && selected) {
      const near = new Set<string>([selected.id]);
      for (const edge of edges) {
        if (edge.source === selected.id) near.add(edge.target);
        if (edge.target === selected.id) near.add(edge.source);
      }
      return near;
    }

    if (!needle) return null;
    return new Set(
      visibleNodes
        .filter((n) => n.label.toLowerCase().includes(needle))
        .map((n) => n.id),
    );
  }, [search, isolate, selected, edges, visibleNodes]);

  // A selection that has been filtered out of view is stale; clearing it stops
  // the detail card describing something that is no longer on screen.
  useEffect(() => {
    if (selected && !visibleIds.has(selected.id)) setSelected(null);
  }, [selected, visibleIds]);

  const toggleType = (type: string) =>
    setHiddenTypes((current) => {
      const next = new Set(current);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });

  const rebuild = useCallback(async () => {
    setRebuilding(true);
    try {
      const res = await api.post(GRAPH_ENDPOINTS.REBUILD);
      toast.success(
        `Rebuilt — ${res.data.nodes} nodes, ${res.data.edges} connections.`,
      );
      await graphQuery.refetch();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not rebuild the graph."));
    } finally {
      setRebuilding(false);
    }
  }, [graphQuery]);

  const status = graph.status ?? "ok";
  const entities = entitiesQuery.data ?? [];

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="typo-heading-md text-onSurface-default-primary">
            Graph
          </h1>
          <p className="typo-body-sm text-onSurface-default-tertiary">
            Entities extracted from your memories, connected where they appear
            together.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {can("admin") && (
            <Button
              variant="outline"
              size="sm"
              onClick={rebuild}
              disabled={rebuilding}
            >
              <RefreshCw
                className={cn("mr-1.5 size-3.5", rebuilding && "animate-spin")}
              />
              {rebuilding ? "Rebuilding…" : "Rebuild"}
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => graphQuery.refetch()}
            disabled={graphQuery.isLoading}
          >
            <RefreshCw
              className={cn(
                "mr-1.5 size-3.5",
                graphQuery.isLoading && "animate-spin",
              )}
            />
            Refresh
          </Button>
        </div>
      </header>

      {status === "error" && (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>The graph could not be built</AlertTitle>
          <AlertDescription>
            {graph.detail ??
              "The graph service returned an unexpected response."}
          </AlertDescription>
        </Alert>
      )}

      {status === "extractor_unavailable" && (
        <Alert>
          <AlertTriangle className="size-4" />
          <AlertTitle>Entity extraction is unavailable</AlertTitle>
          <AlertDescription>
            The spaCy <code>en_core_web_sm</code> model is missing, so no
            entities can be extracted and the graph will stay empty. Install it
            in the API image with{" "}
            <code>python -m spacy download en_core_web_sm</code>.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 py-4">
          <div className="min-w-[200px] flex-1">
            <label className="mb-1 block typo-caption-sm text-onSurface-default-tertiary">
              Find a node
            </label>
            <Input
              value={search}
              placeholder="Search labels…"
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="w-[180px]">
            <label className="mb-1 block typo-caption-sm text-onSurface-default-tertiary">
              Scope
            </label>
            <Select
              value={scopeType && scopeId ? `${scopeType}:${scopeId}` : "all"}
              onValueChange={(value) => {
                if (value === "all") {
                  setScopeType("");
                  setScopeId("");
                  return;
                }
                const [type, ...rest] = value.split(":");
                setScopeType(type as Exclude<EntityType, "app">);
                setScopeId(rest.join(":"));
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Whole project</SelectItem>
                {(["user", "agent", "run"] as const).map((type) => {
                  const matching = entities.filter((e) => e.type === type);
                  if (matching.length === 0) return null;
                  return (
                    <SelectGroup key={type}>
                      <SelectLabel>{type}</SelectLabel>
                      {matching.map((entity) => (
                        <SelectItem
                          key={`${type}:${entity.id}`}
                          value={`${type}:${entity.id}`}
                        >
                          {entity.id}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  );
                })}
              </SelectContent>
            </Select>
          </div>

          <div className="w-[180px]">
            <label className="mb-1 block typo-caption-sm text-onSurface-default-tertiary">
              Minimum connections: {minDegree}
            </label>
            <Slider
              value={[minDegree]}
              min={0}
              max={10}
              step={1}
              onValueChange={([value]) => setMinDegree(value)}
            />
          </div>

          <div className="flex flex-wrap gap-1.5">
            {presentTypes.map((type) => (
              <button
                key={type}
                onClick={() => toggleType(type)}
                aria-pressed={!hiddenTypes.has(type)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border px-2 py-1 text-xs transition-opacity",
                  hiddenTypes.has(type)
                    ? "border-memBorder-primary opacity-40"
                    : "border-transparent bg-surface-default-tertiary",
                )}
              >
                <span
                  aria-hidden
                  className="size-2 rounded-full"
                  style={{ backgroundColor: colorFor(type) }}
                />
                {type}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {graph.truncated && (
        <p className="typo-caption-sm text-onSurface-default-tertiary">
          Showing the {visibleNodes.length.toLocaleString()} most connected of{" "}
          {(graph.total_nodes ?? 0).toLocaleString()} entities. Raise the
          minimum connections to narrow it further.
        </p>
      )}

      <Card>
        <CardContent className="p-3">
          {graphQuery.isLoading && graph.nodes.length === 0 ? (
            <Skeleton className="h-[560px] w-full" />
          ) : visibleNodes.length === 0 ? (
            <EmptyState
              title={status === "ok" ? "Nothing to show" : "No graph yet"}
              description={
                hiddenTypes.size > 0
                  ? "Every entity type is hidden. Re-enable one from the legend above."
                  : "Entities appear here once memories have been added and extraction has run."
              }
            />
          ) : (
            <GraphCanvas
              nodes={visibleNodes}
              edges={edges}
              highlighted={highlighted}
              selectedId={selected?.id ?? null}
              onSelect={setSelected}
              colorFor={colorFor}
            />
          )}
        </CardContent>
      </Card>

      {selected && (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="size-2.5 rounded-full"
                  style={{ backgroundColor: colorFor(selected.type) }}
                />
                <span className="typo-body-md text-onSurface-default-primary">
                  {selected.label}
                </span>
                <span className="typo-caption-sm text-onSurface-default-tertiary">
                  {selected.type}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-3 typo-caption-sm text-onSurface-default-tertiary">
                <span>
                  {selected.memories} memor
                  {selected.memories === 1 ? "y" : "ies"}
                </span>
                {selected.degree !== undefined && (
                  <span>{selected.degree} connections</span>
                )}
                <CopyInline value={selected.id} />
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                variant={isolate ? "default" : "outline"}
                size="sm"
                onClick={() => setIsolate((v) => !v)}
              >
                <Share2 className="mr-1.5 size-3.5" />
                {isolate ? "Show all" : "Isolate neighbours"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelected(null)}
              >
                Clear
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
