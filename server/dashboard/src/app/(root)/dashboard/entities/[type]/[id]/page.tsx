"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { format, formatDistanceToNow } from "date-fns";
import { ChevronRight, Unlink } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { ENTITY_ENDPOINTS } from "@/utils/api-endpoints";
import { getErrorMessage } from "@/lib/error-message";
import { ENTITY_LABEL, type EntityType } from "@/constants/entities";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
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
import { ScopePill } from "@/components/shared/filter-bar";
import {
  LifecycleBadge,
  TypeBadge,
  type LifecycleState,
  type RequestType,
} from "@/components/shared/status-badges";

interface EntityDetail {
  id: string;
  type: EntityType;
  total_memories: number;
  total_requests: number;
  aliases: string[];
  display_name: string | null;
  note: string | null;
  first_seen: string | null;
  last_seen: string | null;
}

interface AliasRow {
  id: string;
  entity_type: string;
  canonical_id: string;
  alias_id: string;
}

interface MemoryRow {
  id: string;
  memory: string;
  created_at?: string;
  lifecycle?: { state: string };
  metadata?: Record<string, unknown>;
}

interface RequestRow {
  id: string;
  request_type: string | null;
  method: string;
  path: string;
  status_code: number;
  latency_ms: number;
  event_count: number;
  created_at: string;
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
          {label}
        </div>
        <div className="mt-1 typo-heading-sm tabular-nums text-onSurface-default-primary">
          {value}
        </div>
      </CardContent>
    </Card>
  );
}

export default function EntityDetailPage() {
  const params = useParams<{ type: string; id: string }>();
  const type = params.type as EntityType;
  const id = decodeURIComponent(params.id);
  const { can } = useScope();

  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [links, setLinks] = useState<AliasRow[]>([]);
  const [memories, setMemories] = useState<MemoryRow[]>([]);
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [tab, setTab] = useState<"memories" | "requests">("memories");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [detail, mem, req, allLinks] = await Promise.all([
        api.get<EntityDetail>(ENTITY_ENDPOINTS.BY_ID(type, id)),
        api.get<{ results: MemoryRow[] }>(ENTITY_ENDPOINTS.MEMORIES(type, id)),
        api.get<{ items: RequestRow[] }>(ENTITY_ENDPOINTS.REQUESTS(type, id)),
        api.get<AliasRow[]>(ENTITY_ENDPOINTS.LINKS),
      ]);
      setEntity(detail.data);
      setMemories(mem.data.results ?? []);
      setRequests(req.data.items ?? []);
      setLinks(allLinks.data);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not load this entity."));
    } finally {
      setLoading(false);
    }
  }, [type, id]);

  useEffect(() => {
    void load();
  }, [load]);

  const aliasRows = useMemo(
    () =>
      links.filter(
        (l) => l.entity_type === type && l.canonical_id === (entity?.id ?? id),
      ),
    [links, type, entity, id],
  );

  const unlink = async (linkId: string) => {
    try {
      await api.delete(ENTITY_ENDPOINTS.LINK_BY_ID(linkId));
      toast.success("Unlinked");
      await load();
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not unlink that identifier."));
    }
  };

  if (loading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!entity) {
    return (
      <div className="p-6">
        <EmptyState
          title="Entity not found"
          description="It may have been deleted, or it belongs to a different project."
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-6">
      <nav className="flex items-center gap-1 typo-caption-sm text-onSurface-default-tertiary">
        <Link href="/dashboard/entities" className="hover:underline">
          Entities
        </Link>
        <ChevronRight className="size-3" />
        <span>{ENTITY_LABEL[type]}</span>
        <ChevronRight className="size-3" />
        <span className="font-mono text-onSurface-default-secondary">
          {entity.display_name ?? entity.id}
        </span>
      </nav>

      <Card>
        <CardContent className="flex flex-wrap items-start justify-between gap-4 py-4">
          <div className="min-w-0">
            <h1 className="typo-heading-md text-onSurface-default-primary">
              {entity.display_name ?? entity.id}
            </h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <CopyInline value={entity.id} />
              <span className="typo-caption-sm text-onSurface-default-tertiary">
                {ENTITY_LABEL[type]}
              </span>
              {entity.first_seen && (
                <span className="typo-caption-sm text-onSurface-default-tertiary">
                  · first seen{" "}
                  {format(new Date(entity.first_seen), "d MMM yyyy")}
                </span>
              )}
            </div>
          </div>
          {/* The scope pill is not removable: it is what makes this page this
              entity's page rather than a filtered list. */}
          <ScopePill label={ENTITY_LABEL[type]} value={entity.id} />
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Total memories" value={entity.total_memories} />
        <Stat label="Total requests" value={entity.total_requests} />
        <Stat
          label="Last seen"
          value={
            entity.last_seen
              ? formatDistanceToNow(new Date(entity.last_seen), {
                  addSuffix: true,
                })
              : "—"
          }
        />
      </div>

      {aliasRows.length > 0 && (
        <Card>
          <CardContent className="py-4">
            <div className="typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
              Also known as
            </div>
            <p className="mt-1 typo-caption-sm text-onSurface-default-tertiary">
              These identifiers resolve here. Memories and requests under any of
              them appear on this page.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {aliasRows.map((row) => (
                <span
                  key={row.id}
                  className="inline-flex items-center gap-1.5 rounded-full border border-memBorder-primary px-2.5 py-1 font-mono text-xs text-onSurface-default-secondary"
                >
                  {row.alias_id}
                  {can("admin") && (
                    <button
                      onClick={() => unlink(row.id)}
                      aria-label={`Unlink ${row.alias_id}`}
                      title="Unlink — the split comes back and no memory is lost"
                      className="text-onSurface-default-tertiary hover:text-onSurface-danger-primary"
                    >
                      <Unlink className="size-3" />
                    </button>
                  )}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex gap-1 border-b border-memBorder-primary">
        {(
          [
            ["memories", `Memories (${memories.length})`],
            ["requests", `Requests (${requests.length})`],
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
          {tab === "memories" ? (
            memories.length === 0 ? (
              <EmptyState
                title="No memories"
                description="Nothing has been recorded about this entity yet."
              />
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Memory</TableHead>
                      <TableHead className="w-28">Lifecycle</TableHead>
                      <TableHead className="w-40">Created</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {memories.map((memory) => (
                      <TableRow key={memory.id}>
                        <TableCell className="text-onSurface-default-primary">
                          {memory.memory}
                          {/* Present when the memory arrived under an alias —
                              the record of which channel it came from. */}
                          {typeof memory.metadata?.source_entity_id ===
                            "object" && (
                            <div className="mt-0.5 font-mono text-[10px] text-onSurface-default-tertiary">
                              via{" "}
                              {Object.values(
                                memory.metadata.source_entity_id as Record<
                                  string,
                                  string
                                >,
                              ).join(", ")}
                            </div>
                          )}
                        </TableCell>
                        <TableCell>
                          <LifecycleBadge
                            state={
                              (memory.lifecycle?.state ??
                                "active") as LifecycleState
                            }
                          />
                        </TableCell>
                        <TableCell className="text-onSurface-default-tertiary">
                          {memory.created_at
                            ? formatDistanceToNow(new Date(memory.created_at), {
                                addSuffix: true,
                              })
                            : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )
          ) : requests.length === 0 ? (
            <EmptyState
              title="No requests"
              description="No API calls about this entity have been traced yet."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-40">Time</TableHead>
                    <TableHead className="w-28">Type</TableHead>
                    <TableHead>Path</TableHead>
                    <TableHead className="w-20 text-right">Event</TableHead>
                    <TableHead className="w-24 text-right">Latency</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {requests.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="whitespace-nowrap text-onSurface-default-secondary">
                        {formatDistanceToNow(new Date(row.created_at), {
                          addSuffix: true,
                        })}
                      </TableCell>
                      <TableCell>
                        <TypeBadge
                          type={(row.request_type ?? "other") as RequestType}
                        />
                      </TableCell>
                      <TableCell className="font-mono text-xs text-onSurface-default-secondary">
                        {row.path}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-onSurface-default-secondary">
                        {row.event_count || "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-onSurface-default-secondary">
                        {row.latency_ms.toFixed(0)}ms
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
