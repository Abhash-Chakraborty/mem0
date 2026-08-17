"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GraphEdge, GraphNode } from "@/types/api";

/**
 * The graph, drawn to canvas and laid out in a worker.
 *
 * Canvas rather than SVG because SVG needs one DOM element per node and edge;
 * at two thousand nodes that is the render cost, not the drawing. Canvas draws
 * the same picture in one element and redraws it per frame for free.
 *
 * The layout runs in a worker (see public/graph-layout.worker.js) and streams
 * positions back as it settles, so the tab never freezes and the graph visibly
 * arranges itself rather than appearing after a stall.
 */

export interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Node ids to keep at full opacity; everything else dims. */
  highlighted?: Set<string> | null;
  selectedId?: string | null;
  onSelect?: (node: GraphNode | null) => void;
  colorFor: (type: string) => string;
  height?: number;
}

interface Point {
  x: number;
  y: number;
}

const MIN_RADIUS = 4;
const MAX_RADIUS = 22;
const LABEL_ZOOM_THRESHOLD = 0.75;

export function GraphCanvas({
  nodes,
  edges,
  highlighted,
  selectedId,
  onSelect,
  colorFor,
  height = 560,
}: GraphCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const workerRef = useRef<Worker | null>(null);
  const positionsRef = useRef<Float32Array>(new Float32Array(0));
  const frameRef = useRef<number>(0);

  const viewRef = useRef({ scale: 1, offsetX: 0, offsetY: 0 });
  const dragRef = useRef<{
    mode: "pan" | "node" | null;
    id?: string;
    last: Point;
  }>({
    mode: null,
    last: { x: 0, y: 0 },
  });
  const hoverRef = useRef<string | null>(null);

  const [progress, setProgress] = useState(0);
  const [ready, setReady] = useState(false);

  const indexById = useMemo(() => {
    const map = new Map<string, number>();
    nodes.forEach((node, i) => map.set(node.id, i));
    return map;
  }, [nodes]);

  // Radius encodes memory count, on a square-root scale so a node with 100
  // memories is not 100x the area of one with a single memory.
  const radii = useMemo(() => {
    const max = nodes.reduce((m, n) => (n.memories > m ? n.memories : m), 1);
    return nodes.map((n) => {
      const ratio = Math.sqrt(Math.max(0, n.memories) / max);
      return MIN_RADIUS + ratio * (MAX_RADIUS - MIN_RADIUS);
    });
  }, [nodes]);

  /** Start (or restart) the layout whenever the graph itself changes. */
  useEffect(() => {
    if (typeof window === "undefined" || nodes.length === 0) return;

    setReady(false);
    setProgress(0);
    positionsRef.current = new Float32Array(nodes.length * 2);

    let worker: Worker;
    try {
      worker = new Worker("/graph-layout.worker.js");
    } catch {
      // No worker available (very old browser, or a CSP that blocks it). The
      // graph still renders — it just does not move.
      setReady(true);
      return;
    }
    workerRef.current = worker;

    worker.onmessage = (event) => {
      const data = event.data;
      if (data?.type !== "positions") return;
      positionsRef.current = data.positions;
      setProgress(data.progress ?? 0);
      if (data.done) setReady(true);
    };

    worker.postMessage({
      type: "layout",
      nodes: nodes.map((n) => ({ id: n.id })),
      edges: edges.map((e) => ({
        source: e.source,
        target: e.target,
        weight: e.weight,
      })),
      iterations: Math.min(400, 120 + nodes.length),
    });

    return () => {
      worker.postMessage({ type: "stop" });
      worker.terminate();
      workerRef.current = null;
    };
  }, [nodes, edges]);

  const toWorld = useCallback((clientX: number, clientY: number): Point => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const view = viewRef.current;
    return {
      x: (clientX - rect.left - rect.width / 2 - view.offsetX) / view.scale,
      y: (clientY - rect.top - rect.height / 2 - view.offsetY) / view.scale,
    };
  }, []);

  const nodeAt = useCallback(
    (world: Point): number => {
      const positions = positionsRef.current;
      // Backwards, so the topmost node under the cursor wins — the same one
      // that is drawn last and therefore looks clickable.
      for (let i = nodes.length - 1; i >= 0; i -= 1) {
        const dx = positions[i * 2] - world.x;
        const dy = positions[i * 2 + 1] - world.y;
        const r = radii[i] + 4;
        if (dx * dx + dy * dy <= r * r) return i;
      }
      return -1;
    },
    [nodes.length, radii],
  );

  /** The draw loop. Runs every frame; cheap enough to not need dirty tracking. */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const displayHeight = canvas.clientHeight;
      if (
        canvas.width !== width * dpr ||
        canvas.height !== displayHeight * dpr
      ) {
        canvas.width = width * dpr;
        canvas.height = displayHeight * dpr;
      }

      const view = viewRef.current;
      const positions = positionsRef.current;

      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, width, displayHeight);
      context.save();
      context.translate(
        width / 2 + view.offsetX,
        displayHeight / 2 + view.offsetY,
      );
      context.scale(view.scale, view.scale);

      const dimmed = highlighted && highlighted.size > 0;

      context.lineCap = "round";
      for (const edge of edges) {
        const s = indexById.get(edge.source);
        const t = indexById.get(edge.target);
        if (s === undefined || t === undefined) continue;

        const lit =
          !dimmed ||
          (highlighted!.has(edge.source) && highlighted!.has(edge.target));
        context.globalAlpha = lit ? 0.35 : 0.06;
        context.strokeStyle = "#8C8AA0";
        context.lineWidth = Math.min(4, 0.5 + Math.log1p(edge.weight));
        context.beginPath();
        context.moveTo(positions[s * 2], positions[s * 2 + 1]);
        context.lineTo(positions[t * 2], positions[t * 2 + 1]);
        context.stroke();
      }

      context.globalAlpha = 1;
      for (let i = 0; i < nodes.length; i += 1) {
        const node = nodes[i];
        const lit = !dimmed || highlighted!.has(node.id);
        const x = positions[i * 2];
        const y = positions[i * 2 + 1];
        const r = radii[i];

        context.globalAlpha = lit ? 1 : 0.15;
        context.fillStyle = colorFor(node.type);
        context.beginPath();
        context.arc(x, y, r, 0, Math.PI * 2);
        context.fill();

        if (node.id === selectedId || node.id === hoverRef.current) {
          context.globalAlpha = 1;
          context.strokeStyle = "#0D0C12";
          context.lineWidth = 2 / view.scale;
          context.stroke();
        }

        // Labels only once zoomed in enough to read them, and only for nodes
        // big enough to be worth naming — otherwise a dense graph is a wall of
        // overlapping text.
        if (
          lit &&
          view.scale > LABEL_ZOOM_THRESHOLD &&
          (r > 7 || node.id === hoverRef.current)
        ) {
          context.globalAlpha = lit ? 0.9 : 0.2;
          context.fillStyle = "#55506A";
          context.font = `${Math.max(9, 11 / view.scale)}px ui-sans-serif, system-ui, sans-serif`;
          context.textAlign = "center";
          context.fillText(node.label, x, y + r + 11 / view.scale);
        }
      }

      context.restore();
      frameRef.current = requestAnimationFrame(draw);
    };

    frameRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frameRef.current);
  }, [nodes, edges, indexById, radii, highlighted, selectedId, colorFor]);

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const world = toWorld(event.clientX, event.clientY);
    const hit = nodeAt(world);
    dragRef.current = {
      mode: hit >= 0 ? "node" : "pan",
      id: hit >= 0 ? nodes[hit].id : undefined,
      last: { x: event.clientX, y: event.clientY },
    };
    if (hit >= 0) {
      workerRef.current?.postMessage({
        type: "pin",
        id: nodes[hit].id,
        pinned: true,
      });
    }
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;

    if (drag.mode === null) {
      const hit = nodeAt(toWorld(event.clientX, event.clientY));
      const nextHover = hit >= 0 ? nodes[hit].id : null;
      if (nextHover !== hoverRef.current) {
        hoverRef.current = nextHover;
        event.currentTarget.style.cursor = nextHover ? "pointer" : "grab";
      }
      return;
    }

    const dx = event.clientX - drag.last.x;
    const dy = event.clientY - drag.last.y;
    drag.last = { x: event.clientX, y: event.clientY };

    if (drag.mode === "pan") {
      viewRef.current.offsetX += dx;
      viewRef.current.offsetY += dy;
      return;
    }

    if (drag.mode === "node" && drag.id) {
      const index = indexById.get(drag.id);
      if (index === undefined) return;
      const positions = positionsRef.current;
      positions[index * 2] += dx / viewRef.current.scale;
      positions[index * 2 + 1] += dy / viewRef.current.scale;
      workerRef.current?.postMessage({
        type: "pin",
        id: drag.id,
        pinned: true,
        x: positions[index * 2],
        y: positions[index * 2 + 1],
      });
    }
  };

  const onPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    // A press with no movement is a click. Distinguished here rather than with
    // a separate onClick, which would also fire at the end of a drag.
    const moved =
      Math.abs(event.clientX - drag.last.x) > 2 ||
      Math.abs(event.clientY - drag.last.y) > 2;

    if (drag.mode === "node" && drag.id && !moved) {
      const node = nodes.find((n) => n.id === drag.id) ?? null;
      onSelect?.(node);
    } else if (drag.mode === "pan" && !moved) {
      onSelect?.(null);
    }

    if (drag.id) {
      workerRef.current?.postMessage({
        type: "pin",
        id: drag.id,
        pinned: false,
      });
    }
    dragRef.current = { mode: null, last: { x: 0, y: 0 } };
  };

  const onWheel = (event: React.WheelEvent<HTMLCanvasElement>) => {
    const view = viewRef.current;
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
    const next = Math.max(0.15, Math.min(6, view.scale * factor));

    // Zoom toward the cursor, not the centre — otherwise zooming in on a
    // cluster pushes it off screen.
    const canvas = canvasRef.current;
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      const px = event.clientX - rect.left - rect.width / 2;
      const py = event.clientY - rect.top - rect.height / 2;
      view.offsetX = px - ((px - view.offsetX) * next) / view.scale;
      view.offsetY = py - ((py - view.offsetY) * next) / view.scale;
    }
    view.scale = next;
  };

  const resetView = () => {
    viewRef.current = { scale: 1, offsetX: 0, offsetY: 0 };
  };

  return (
    <div className="relative w-full" style={{ height }}>
      <canvas
        ref={canvasRef}
        className="size-full touch-none rounded-lg bg-surface-default-secondary"
        style={{ cursor: "grab" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        onWheel={onWheel}
      />

      {!ready && nodes.length > 0 && (
        <div className="pointer-events-none absolute left-3 top-3 rounded-md bg-surface-default-primary/90 px-2 py-1 text-xs text-onSurface-default-tertiary">
          Arranging… {Math.round(progress * 100)}%
        </div>
      )}

      <button
        onClick={resetView}
        className="absolute bottom-3 right-3 rounded-md border border-memBorder-primary bg-surface-default-primary px-2 py-1 text-xs text-onSurface-default-secondary hover:text-onSurface-default-primary"
      >
        Reset view
      </button>
    </div>
  );
}
