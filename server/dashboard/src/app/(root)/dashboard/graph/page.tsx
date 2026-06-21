"use client";

import { useMemo, useState } from "react";
import { RefreshCw, Share2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS, GRAPH_ENDPOINTS } from "@/utils/api-endpoints";
import { useApiQuery } from "@/hooks/use-api-query";
import { Entity, EntityType, GraphResponse } from "@/types/api";

// Colors per entity_type produced by mem0's built-in entity extraction.
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

const MAX_NODES = 150;
const WIDTH = 900;
const HEIGHT = 600;

interface Positioned {
  id: string;
  x: number;
  y: number;
}

/**
 * Tiny dependency-free force-directed layout. Runs a fixed number of ticks of
 * repulsion (all pairs) + spring attraction (edges) + centering, then returns
 * final node positions. Deterministic given the same data + seed.
 */
function computeLayout(
  nodes: { id: string }[],
  edges: { source: string; target: string }[],
  seed: number,
): Map<string, Positioned> {
  const cx = WIDTH / 2;
  const cy = HEIGHT / 2;
  const pos = new Map<
    string,
    { x: number; y: number; vx: number; vy: number }
  >();

  // Deterministic pseudo-random based on seed + index, so "Re-layout" varies.
  const rand = (i: number) => {
    const v = Math.sin((i + 1) * (seed + 1) * 12.9898) * 43758.5453;
    return v - Math.floor(v);
  };

  nodes.forEach((n, i) => {
    const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2;
    const radius = 120 + rand(i) * 160;
    pos.set(n.id, {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
    });
  });

  const nodeArr = nodes.map((n) => n.id);
  const REPULSION = 9000;
  const SPRING = 0.02;
  const REST = 90;
  const CENTER = 0.012;
  const DAMP = 0.85;
  const TICKS = nodes.length > 80 ? 200 : 320;

  for (let t = 0; t < TICKS; t++) {
    // Repulsion between every pair.
    for (let i = 0; i < nodeArr.length; i++) {
      const a = pos.get(nodeArr[i])!;
      for (let j = i + 1; j < nodeArr.length; j++) {
        const b = pos.get(nodeArr[j])!;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let distSq = dx * dx + dy * dy;
        if (distSq < 0.01) {
          dx = rand(i + t) - 0.5;
          dy = rand(j + t) - 0.5;
          distSq = 0.01;
        }
        const dist = Math.sqrt(distSq);
        const force = REPULSION / distSq;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
    }

    // Spring attraction along edges.
    for (const e of edges) {
      const a = pos.get(e.source);
      const b = pos.get(e.target);
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const force = (dist - REST) * SPRING;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }

    // Centering + integration.
    for (const id of nodeArr) {
      const p = pos.get(id)!;
      p.vx += (cx - p.x) * CENTER;
      p.vy += (cy - p.y) * CENTER;
      p.vx *= DAMP;
      p.vy *= DAMP;
      p.x += p.vx;
      p.y += p.vy;
    }
  }

  const out = new Map<string, Positioned>();
  for (const id of nodeArr) {
    const p = pos.get(id)!;
    out.set(id, { id, x: p.x, y: p.y });
  }
  return out;
}

export default function GraphPage() {
  const [scope, setScope] = useState<string>("all");
  const [seed, setSeed] = useState(1);
  const [hovered, setHovered] = useState<string | null>(null);

  const { data: entities = [] } = useApiQuery<Entity[]>(
    async () => {
      const res = await api.get<Entity[]>(ENTITY_ENDPOINTS.BASE);
      return res.data ?? [];
    },
    { errorToast: "Failed to load entities", initialData: [] },
  );

  const {
    data: graph = { nodes: [], edges: [] },
    isLoading,
    refetch,
  } = useApiQuery<GraphResponse>(
    async () => {
      const params = new URLSearchParams();
      if (scope !== "all") {
        const [type, ...rest] = scope.split(":");
        const id = rest.join(":");
        const field = SCOPE_FIELD[type as Exclude<EntityType, "app">];
        if (field && id) params.set(field, id);
      }
      const qs = params.toString();
      const res = await api.get<GraphResponse>(
        `${GRAPH_ENDPOINTS.BASE}${qs ? `?${qs}` : ""}`,
      );
      return res.data ?? { nodes: [], edges: [] };
    },
    {
      errorToast: "Failed to load graph",
      initialData: { nodes: [], edges: [] },
      deps: [scope],
    },
  );

  // Keep the densest nodes when the graph is large.
  const nodes = useMemo(() => {
    const sorted = [...graph.nodes].sort((a, b) => b.memories - a.memories);
    return sorted.slice(0, MAX_NODES);
  }, [graph.nodes]);

  const visibleIds = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes]);
  const edges = useMemo(
    () =>
      graph.edges.filter(
        (e) => visibleIds.has(e.source) && visibleIds.has(e.target),
      ),
    [graph.edges, visibleIds],
  );

  const layout = useMemo(
    () => computeLayout(nodes, edges, seed),
    [nodes, edges, seed],
  );

  const maxMemories = useMemo(
    () => Math.max(1, ...nodes.map((n) => n.memories)),
    [nodes],
  );

  const neighbors = useMemo(() => {
    if (!hovered) return null;
    const set = new Set<string>([hovered]);
    for (const e of edges) {
      if (e.source === hovered) set.add(e.target);
      if (e.target === hovered) set.add(e.source);
    }
    return set;
  }, [hovered, edges]);

  const usedTypes = useMemo(
    () => Array.from(new Set(nodes.map((n) => n.type))),
    [nodes],
  );

  const entityOptions = useMemo(() => {
    const groups: Record<string, Entity[]> = {};
    for (const e of entities) {
      (groups[e.type] ??= []).push(e);
    }
    return groups;
  }, [entities]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold font-fustat">Graph</h1>
          <p className="text-xs text-onSurface-default-tertiary mt-0.5">
            Entities extracted from your memories, linked when they appear in the
            same memory.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={scope} onValueChange={setScope}>
            <SelectTrigger className="w-[220px]">
              <SelectValue placeholder="All entities" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All entities</SelectItem>
              {(["user", "agent", "run"] as const).map((type) =>
                entityOptions[type]?.length ? (
                  <SelectGroup key={type}>
                    <SelectLabel className="capitalize">{type}</SelectLabel>
                    {entityOptions[type].map((e) => (
                      <SelectItem key={`${type}:${e.id}`} value={`${type}:${e.id}`}>
                        {e.id}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                ) : null,
              )}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setSeed((s) => s + 1);
              void refetch();
            }}
          >
            <RefreshCw className="size-4 mr-2" />
            Re-layout
          </Button>
        </div>
      </div>

      {isLoading ? (
        <TableSkeleton rows={6} columns={1} />
      ) : nodes.length === 0 ? (
        <EmptyState
          title="No graph yet"
          description="The entity graph appears once memories are stored. mem0 extracts entities (people, places, things) and links memories that share them."
        >
          <div className="mt-4">
            <Share2 className="size-8 text-onSurface-default-tertiary mx-auto opacity-60" />
          </div>
        </EmptyState>
      ) : (
        <Card className="border-memBorder-primary overflow-hidden">
          <CardContent className="p-0">
            <div className="flex items-center justify-between px-4 py-2 border-b border-memBorder-primary text-xs text-onSurface-default-tertiary">
              <span>
                {nodes.length} entit{nodes.length === 1 ? "y" : "ies"} &middot;{" "}
                {edges.length} connection{edges.length === 1 ? "" : "s"}
                {graph.nodes.length > MAX_NODES &&
                  ` (showing top ${MAX_NODES} by memory count)`}
              </span>
              <div className="flex items-center gap-3">
                {usedTypes.map((t) => (
                  <span key={t} className="flex items-center gap-1.5">
                    <span
                      className="inline-block size-2.5 rounded-full"
                      style={{ backgroundColor: TYPE_COLORS[t] ?? TYPE_COLORS.ENTITY }}
                    />
                    <span className="capitalize">{t.toLowerCase()}</span>
                  </span>
                ))}
              </div>
            </div>
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              className="w-full h-[600px] bg-surface-default-secondary/30"
              role="img"
              aria-label="Entity relationship graph"
            >
              {edges.map((e, i) => {
                const a = layout.get(e.source);
                const b = layout.get(e.target);
                if (!a || !b) return null;
                const dim = neighbors && !(neighbors.has(e.source) && neighbors.has(e.target));
                return (
                  <line
                    key={`e${i}`}
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke="currentColor"
                    className="text-memBorder-primary"
                    strokeWidth={Math.min(3, 0.6 + e.weight * 0.4)}
                    strokeOpacity={dim ? 0.08 : 0.4}
                  />
                );
              })}
              {nodes.map((n) => {
                const p = layout.get(n.id);
                if (!p) return null;
                const r = 5 + (n.memories / maxMemories) * 16;
                const color = TYPE_COLORS[n.type] ?? TYPE_COLORS.ENTITY;
                const dim = neighbors && !neighbors.has(n.id);
                return (
                  <g
                    key={n.id}
                    transform={`translate(${p.x},${p.y})`}
                    onMouseEnter={() => setHovered(n.id)}
                    onMouseLeave={() => setHovered(null)}
                    style={{ cursor: "pointer", opacity: dim ? 0.25 : 1 }}
                  >
                    <circle r={r} fill={color} fillOpacity={0.85} />
                    <title>
                      {n.label} ({n.type.toLowerCase()}) — {n.memories} memor
                      {n.memories === 1 ? "y" : "ies"}
                    </title>
                    {(r > 10 || hovered === n.id) && (
                      <text
                        y={r + 11}
                        textAnchor="middle"
                        className="fill-onSurface-default-primary"
                        fontSize={11}
                      >
                        {n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
