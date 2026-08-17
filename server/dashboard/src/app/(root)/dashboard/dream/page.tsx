"use client";

import { useCallback, useEffect, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { ArrowRight, Layers, Lightbulb, Play, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { DREAM_ENDPOINTS } from "@/utils/api-endpoints";
import { getErrorMessage } from "@/lib/error-message";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { CopyInline } from "@/components/shared/copy-inline";

interface DreamStatus {
  synthesis_enabled: boolean;
  thresholds: Record<string, number>;
  totals: Record<string, number>;
  last_run_at: string | null;
  candidates: {
    entity_type: string;
    entity_id: string;
    memory_count: number;
    eligible: boolean;
    due: boolean;
  }[];
}

interface RunItem {
  id: string;
  kind: string;
  status: string;
  scope: Record<string, unknown> | null;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  considered: number;
  acted: number;
  tokens_used: number;
  duration_ms: number | null;
}

interface ActionItem {
  id: string;
  kind: string;
  subject_memory_id: string;
  object_memory_id: string | null;
  confidence: number | null;
  rationale: string | null;
  reverted_at: string | null;
  created_at: string;
  subject_text: string | null;
  object_text: string | null;
}

/**
 * The three capabilities, described in terms of what they do to your memories
 * rather than what they are called. Supersede and merge are always on because
 * they are corrections; synthesis writes new memories, so it is opt-in.
 */
const CAPABILITIES = [
  {
    kind: "supersede",
    title: "Supersede",
    icon: ArrowRight,
    description:
      "When a newer fact contradicts an older one, the older is marked as history and linked to its replacement. It is still returned by default — what the system used to believe is worth being able to read.",
    always: true,
  },
  {
    kind: "merge",
    title: "Merge",
    icon: Layers,
    description:
      "When two memories say the same thing, the thinner one folds into the richer. Hidden by default, never deleted.",
    always: true,
  },
  {
    kind: "synthesis",
    title: "Synthesis",
    icon: Lightbulb,
    description:
      "Recurring signals across someone's memories are distilled into a pattern that links back to its evidence. The sources are untouched.",
    always: false,
  },
];

const STATUS_TONE: Record<string, string> = {
  succeeded: "text-onSurface-default-secondary",
  skipped: "text-onSurface-default-tertiary",
  running: "text-onSurface-default-secondary",
  failed: "text-onSurface-danger-primary",
};

export default function DreamPage() {
  const { can } = useScope();
  const [status, setStatus] = useState<DreamStatus | null>(null);
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<"actions" | "runs">("actions");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, r, a] = await Promise.all([
        api.get<DreamStatus>(DREAM_ENDPOINTS.STATUS),
        api.get<RunItem[]>(DREAM_ENDPOINTS.RUNS),
        api.get<ActionItem[]>(DREAM_ENDPOINTS.ACTIONS),
      ]);
      setStatus(s.data);
      setRuns(r.data);
      setActions(a.data);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not load Dream."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const revert = async (actionId: string) => {
    setBusy(actionId);
    try {
      const res = await api.post(DREAM_ENDPOINTS.REVERT(actionId));
      toast.success(res.data?.message ?? "Reverted");
      await load();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not revert that action."));
    } finally {
      setBusy(null);
    }
  };

  const runNow = async (entityId: string) => {
    setBusy(entityId);
    try {
      const res = await api.post(DREAM_ENDPOINTS.SYNTHESIZE, {
        entity_id: entityId,
      });
      const run = res.data as RunItem;
      toast.success(
        run.status === "skipped"
          ? "Nothing new to synthesise for that entity."
          : `Synthesis finished — ${run.acted} pattern${run.acted === 1 ? "" : "s"} from ${run.considered} memories.`,
      );
      await load();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not run synthesis."));
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const eligible = (status?.candidates ?? []).filter((c) => c.eligible);

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="typo-heading-md text-onSurface-default-primary">
              Dream
            </h1>
            <span className="rounded-full bg-surface-default-tertiary px-2 py-0.5 typo-caption-sm uppercase tracking-wide text-onSurface-default-secondary">
              New
            </span>
          </div>
          <p className="typo-body-sm text-onSurface-default-tertiary">
            Background curation that keeps memories current. Nothing it does is
            destructive, and every decision can be undone.
          </p>
        </div>
        {status?.last_run_at && (
          <div className="text-right">
            <div className="typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
              Last run
            </div>
            <div className="typo-body-sm text-onSurface-default-secondary">
              {formatDistanceToNow(new Date(status.last_run_at), {
                addSuffix: true,
              })}
            </div>
          </div>
        )}
      </header>

      <div className="grid gap-3 lg:grid-cols-3">
        {CAPABILITIES.map((capability) => {
          const count = status?.totals?.[capability.kind] ?? 0;
          const on = capability.always || status?.synthesis_enabled;
          return (
            <Card key={capability.kind}>
              <CardContent className="flex h-full flex-col gap-2 py-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <capability.icon className="size-4 text-onSurface-default-secondary" />
                    <span className="typo-body-md text-onSurface-default-primary">
                      {capability.title}
                    </span>
                  </div>
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 typo-caption-sm uppercase tracking-wide",
                      on
                        ? "bg-surface-default-tertiary text-onSurface-default-secondary"
                        : "border border-memBorder-primary text-onSurface-default-tertiary",
                    )}
                  >
                    {capability.always ? "Always on" : on ? "On" : "Off"}
                  </span>
                </div>
                <p className="flex-1 typo-caption-sm text-onSurface-default-tertiary">
                  {capability.description}
                </p>
                <div className="typo-body-sm tabular-nums text-onSurface-default-secondary">
                  {count} action{count === 1 ? "" : "s"}
                </div>
                {!capability.always && !on && (
                  <Link
                    href="/dashboard/settings/retention"
                    className="typo-caption-sm text-onSurface-default-secondary underline"
                  >
                    Enable in Settings → Retention
                  </Link>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {status?.synthesis_enabled && eligible.length > 0 && can("admin") && (
        <Card>
          <CardContent className="py-4">
            <div className="typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
              Ready for synthesis
            </div>
            <div className="mt-2 flex flex-col gap-2">
              {eligible.map((candidate) => (
                <div
                  key={candidate.entity_id}
                  className="flex items-center justify-between gap-4"
                >
                  <div className="min-w-0">
                    <span className="font-mono text-xs text-onSurface-default-primary">
                      {candidate.entity_id}
                    </span>
                    <span className="ml-2 typo-caption-sm text-onSurface-default-tertiary">
                      {candidate.memory_count} memories
                      {candidate.due ? " · due" : " · not due yet"}
                    </span>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy === candidate.entity_id}
                    onClick={() => runNow(candidate.entity_id)}
                  >
                    <Play className="mr-1.5 size-3.5" />
                    {busy === candidate.entity_id ? "Running…" : "Run now"}
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex gap-1 border-b border-memBorder-primary">
        {(
          [
            ["actions", `Actions (${actions.length})`],
            ["runs", `Runs (${runs.length})`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 typo-body-sm transition-colors",
              tab === key
                ? "border-onSurface-default-primary text-onSurface-default-primary"
                : "border-transparent text-onSurface-default-tertiary hover:text-onSurface-default-secondary",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="p-0">
          {tab === "actions" ? (
            actions.length === 0 ? (
              <EmptyState
                title="Dream has not acted yet"
                description="Supersede and merge run as memories arrive. Synthesis runs on a schedule once enabled."
              />
            ) : (
              <div className="divide-y divide-memBorder-primary">
                {actions.map((action) => (
                  <div
                    key={action.id}
                    className={cn(
                      "flex flex-col gap-2 p-4",
                      action.reverted_at && "opacity-60",
                    )}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded bg-surface-default-tertiary px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-onSurface-default-secondary">
                        {action.kind}
                      </span>
                      {action.confidence !== null && (
                        <span className="typo-caption-sm tabular-nums text-onSurface-default-tertiary">
                          {(action.confidence * 100).toFixed(0)}% confident
                        </span>
                      )}
                      <span className="typo-caption-sm text-onSurface-default-tertiary">
                        {formatDistanceToNow(new Date(action.created_at), {
                          addSuffix: true,
                        })}
                      </span>
                      {action.reverted_at && (
                        <span className="typo-caption-sm text-onSurface-default-tertiary">
                          · reverted
                        </span>
                      )}
                      <span className="flex-1" />
                      {can("admin") && !action.reverted_at && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy === action.id}
                          onClick={() => revert(action.id)}
                        >
                          <RotateCcw className="mr-1.5 size-3.5" />
                          Revert
                        </Button>
                      )}
                    </div>

                    <div className="grid gap-2 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
                      <div className="rounded-md border border-memBorder-primary bg-surface-default-secondary p-2">
                        <div className="typo-caption-sm text-onSurface-default-tertiary">
                          {action.kind === "synthesis" ? "Pattern" : "Affected"}
                        </div>
                        <p className="typo-body-sm text-onSurface-default-primary">
                          {action.subject_text ??
                            "(memory no longer available)"}
                        </p>
                        <CopyInline value={action.subject_memory_id} />
                      </div>

                      {action.object_memory_id && (
                        <>
                          <ArrowRight className="hidden size-4 text-onSurface-default-tertiary sm:block" />
                          <div className="rounded-md border border-memBorder-primary bg-surface-default-secondary p-2">
                            <div className="typo-caption-sm text-onSurface-default-tertiary">
                              {action.kind === "supersede"
                                ? "Replaced by"
                                : "Merged into"}
                            </div>
                            <p className="typo-body-sm text-onSurface-default-primary">
                              {action.object_text ??
                                "(memory no longer available)"}
                            </p>
                            <CopyInline value={action.object_memory_id} />
                          </div>
                        </>
                      )}
                    </div>

                    {action.rationale && (
                      <p className="typo-caption-sm italic text-onSurface-default-tertiary">
                        “{action.rationale}”
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )
          ) : runs.length === 0 ? (
            <EmptyState
              title="No runs yet"
              description="A run is recorded every time Dream considers a memory, even when it decides to do nothing."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-40">Started</TableHead>
                    <TableHead className="w-28">Kind</TableHead>
                    <TableHead className="w-24">Status</TableHead>
                    <TableHead className="w-24 text-right">
                      Considered
                    </TableHead>
                    <TableHead className="w-20 text-right">Acted</TableHead>
                    <TableHead className="w-24 text-right">Duration</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.map((run) => (
                    <TableRow key={run.id}>
                      <TableCell className="whitespace-nowrap text-onSurface-default-secondary">
                        {formatDistanceToNow(new Date(run.started_at), {
                          addSuffix: true,
                        })}
                      </TableCell>
                      <TableCell className="text-onSurface-default-secondary">
                        {run.kind}
                      </TableCell>
                      <TableCell className={STATUS_TONE[run.status] ?? ""}>
                        {run.status}
                        {run.error && (
                          <span
                            className="ml-1 cursor-help"
                            title={run.error}
                            aria-label={run.error}
                          >
                            ⚠
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-onSurface-default-secondary">
                        {run.considered}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-onSurface-default-secondary">
                        {run.acted || "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-onSurface-default-tertiary">
                        {run.duration_ms !== null
                          ? `${run.duration_ms}ms`
                          : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
