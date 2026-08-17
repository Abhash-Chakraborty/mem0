"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { format, formatDistanceToNow } from "date-fns";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { REQUEST_ENDPOINTS } from "@/utils/api-endpoints";
import { getErrorMessage } from "@/lib/error-message";
import { parseQuery } from "@/lib/query-syntax";
import {
  entityHref,
  ENTITY_LABEL,
  type EntityType,
} from "@/constants/entities";
import { usePanelRecord } from "@/hooks/use-panel-record";
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
import { FilterBar } from "@/components/shared/filter-bar";
import {
  ActivityHistogram,
  type HistogramBucket,
} from "@/components/shared/activity-histogram";
import { TypeBadge, type RequestType } from "@/components/shared/status-badges";
import { EntityChip } from "@/components/shared/entity-chip";
import { CopyInline } from "@/components/shared/copy-inline";
import {
  formatRange,
  rangeToParams,
  type TimeRange,
} from "@/components/shared/time-range-picker";
import { DetailPanel } from "@/components/panel/detail-panel";
import { PanelSection } from "@/components/panel/panel-section";
import { JsonBlock } from "@/components/panel/json-block";

interface TraceEntity {
  type: string;
  id: string;
}

interface RequestRow {
  id: string;
  request_id: string | null;
  method: string;
  path: string;
  request_type: string | null;
  status_code: number;
  latency_ms: number;
  auth_type: string;
  entities: TraceEntity[];
  event_count: number;
  is_playground: boolean;
  error: string | null;
  created_at: string;
}

interface RequestDetail extends RequestRow {
  payload: unknown;
  result_summary: Record<string, unknown> | null;
  memory_ids: string[];
  memories: Record<string, unknown>[];
}

interface HistogramResponse {
  buckets: { bucket: string; counts: Record<string, number>; total: number }[];
  interval: string;
  total: number;
}

// One colour per request type, fixed here so the bars, the legend and the type
// badges cannot drift apart as types are added.
const SERIES = [
  { key: "add", label: "Add", color: "#6D4AFF" },
  { key: "search", label: "Search", color: "#3B9EFF" },
  { key: "get_all", label: "Get all", color: "#26B47F" },
  { key: "get", label: "Get", color: "#8FBF3F" },
  { key: "update", label: "Update", color: "#E0A94A" },
  { key: "delete", label: "Delete", color: "#E0674A" },
  { key: "delete_all", label: "Delete all", color: "#C24A6B" },
  { key: "other", label: "Other", color: "#8C8AA0" },
];

const QUICK_FILTERS = [
  { id: "type:add", label: "Add" },
  { id: "type:search", label: "Search" },
  { id: "type:get_all", label: "Get all" },
  { id: "has_results", label: "Has results" },
  { id: "hide_playground", label: "Hide playground" },
  { id: "status:failed", label: "Failed" },
];

const PAGE_SIZE = 50;

function statusTone(code: number): string {
  if (code >= 500) return "text-onSurface-danger-primary";
  if (code >= 400) return "text-onSurface-default-secondary";
  return "text-onSurface-default-secondary";
}

function RequestsPageInner() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [range, setRange] = useState<TimeRange>({ key: "7d" });
  const [active, setActive] = useState<string[]>([]);

  const [rows, setRows] = useState<RequestRow[]>([]);
  const [total, setTotal] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [histogram, setHistogram] = useState<HistogramResponse | null>(null);

  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [tab, setTab] = useState("request");

  /** The filter set, assembled once and shared by the list and the histogram. */
  const params = useMemo(() => {
    const out: Record<string, string | string[] | boolean> = {};
    const types = active
      .filter((f) => f.startsWith("type:"))
      .map((f) => f.slice(5));
    if (types.length) out.type = types;
    if (active.includes("status:failed")) out.status = "failed";
    if (active.includes("has_results")) out.has_results = true;
    if (active.includes("hide_playground")) out.hide_playground = true;
    if (submitted.trim()) out.q = submitted.trim();
    Object.assign(out, rangeToParams(range));
    return out;
  }, [active, submitted, range]);

  const load = useCallback(
    async (nextCursor?: string) => {
      const paging = nextCursor ? setLoadingMore : setLoading;
      paging(true);
      try {
        const res = await api.get(REQUEST_ENDPOINTS.BASE, {
          params: { ...params, limit: PAGE_SIZE, cursor: nextCursor },
        });
        setRows((current) =>
          nextCursor ? [...current, ...res.data.items] : res.data.items,
        );
        setTotal(res.data.total);
        setCursor(res.data.next_cursor);
      } catch (err) {
        toast.error(getErrorMessage(err, "Could not load requests."));
      } finally {
        paging(false);
      }
    },
    [params],
  );

  const loadHistogram = useCallback(async () => {
    try {
      const res = await api.get<HistogramResponse>(
        REQUEST_ENDPOINTS.HISTOGRAM,
        {
          params,
        },
      );
      setHistogram(res.data);
    } catch {
      // The chart is context, not content. Losing it must not blank the table.
      setHistogram(null);
    }
  }, [params]);

  useEffect(() => {
    void load();
    void loadHistogram();
  }, [load, loadHistogram]);

  const panel = usePanelRecord<RequestRow>({
    records: rows,
    getId: (row) => row.id,
    param: "requestId",
  });

  useEffect(() => {
    if (!panel.selected) {
      setDetail(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setTab("request");
    api
      .get<RequestDetail>(REQUEST_ENDPOINTS.BY_ID(panel.selected.id))
      .then((res) => {
        if (active) setDetail(res.data);
      })
      .catch((err) => {
        if (active)
          toast.error(getErrorMessage(err, "Could not load the request."));
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [panel.selected]);

  const buckets: HistogramBucket[] = useMemo(
    () =>
      (histogram?.buckets ?? []).map((b) => ({
        date: b.bucket,
        counts: b.counts,
      })),
    [histogram],
  );

  // Only the types actually present get a series, so a quiet instance does not
  // render a legend of eight colours for two kinds of traffic.
  const presentSeries = useMemo(() => {
    const seen = new Set<string>();
    for (const bucket of buckets)
      for (const key of Object.keys(bucket.counts)) seen.add(key);
    return SERIES.filter((s) => seen.has(s.key));
  }, [buckets]);

  const toggle = (id: string) =>
    setActive((current) =>
      current.includes(id) ? current.filter((f) => f !== id) : [...current, id],
    );

  const parsed = parseQuery(query);

  const tabs = useMemo(() => {
    const list = [{ id: "request", label: "Request" }];
    if (detail?.request_type === "add" || detail?.payload) {
      list.push({ id: "input", label: "Input" });
    }
    if ((detail?.memory_ids?.length ?? 0) > 0) {
      list.push({
        id: "memories",
        label: `Memories (${detail?.memory_ids.length})`,
      });
    }
    return list;
  }, [detail]);

  return (
    <div className="space-y-4 p-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="typo-heading-md text-onSurface-default-primary">
            Requests
          </h1>
          <p className="typo-body-sm text-onSurface-default-tertiary">
            Every API call in this project, with what went in and what came out.
          </p>
        </div>
        <div className="text-right">
          <div className="typo-heading-sm tabular-nums text-onSurface-default-primary">
            {total.toLocaleString()}
          </div>
          <div className="typo-caption-sm text-onSurface-default-tertiary">
            {formatRange(range)}
          </div>
        </div>
      </header>

      <FilterBar
        placeholder="Search — try user:alice, type:add, status:failed"
        query={query}
        onQueryChange={setQuery}
        onSubmit={() => setSubmitted(query)}
        range={range}
        onRangeChange={setRange}
        quickFilters={QUICK_FILTERS}
        activeFilters={active}
        onToggleFilter={toggle}
        onRefresh={() => {
          void load();
          void loadHistogram();
        }}
        isRefreshing={loading}
        onClearAll={() => {
          setActive([]);
          setQuery("");
          setSubmitted("");
        }}
      />

      {query.trim() &&
        parsed.types.length === 0 &&
        !parsed.entityId &&
        !parsed.status && (
          <p className="typo-caption-sm text-onSurface-default-tertiary">
            Searching payloads and paths for “{query.trim()}”. Press Enter to
            run it.
          </p>
        )}

      {buckets.length > 0 && (
        <Card>
          <CardContent className="pt-4">
            <ActivityHistogram
              buckets={buckets}
              series={presentSeries}
              height={120}
            />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {loading && rows.length === 0 ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              title="No requests match"
              description="Nothing in this project matched these filters. Widen the time range or clear the filters."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-40">Time</TableHead>
                    <TableHead className="w-28">Type</TableHead>
                    <TableHead>Entities</TableHead>
                    <TableHead className="w-20 text-right">Event</TableHead>
                    <TableHead className="w-24 text-right">Latency</TableHead>
                    <TableHead className="w-24">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow
                      key={row.id}
                      onClick={() => panel.select(row)}
                      className="cursor-pointer"
                    >
                      <TableCell
                        className="whitespace-nowrap text-onSurface-default-secondary"
                        title={format(new Date(row.created_at), "PPpp")}
                      >
                        {formatDistanceToNow(new Date(row.created_at), {
                          addSuffix: true,
                        })}
                      </TableCell>
                      <TableCell>
                        <TypeBadge
                          type={(row.request_type ?? "other") as RequestType}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1.5">
                          {row.entities.length === 0 ? (
                            <span className="typo-caption-sm text-onSurface-default-tertiary">
                              —
                            </span>
                          ) : (
                            row.entities.map((e) => (
                              <EntityChip
                                key={`${e.type}:${e.id}`}
                                type={e.type as EntityType}
                                id={e.id}
                                href={entityHref(e.type as EntityType, e.id)}
                                isPlayground={row.is_playground}
                              />
                            ))
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-onSurface-default-secondary">
                        {row.event_count || "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-onSurface-default-secondary">
                        {row.latency_ms.toFixed(0)}ms
                      </TableCell>
                      <TableCell
                        className={`tabular-nums ${statusTone(row.status_code)}`}
                      >
                        {row.status_code}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {cursor && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => void load(cursor)}
            disabled={loadingMore}
          >
            {loadingMore ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}

      <DetailPanel
        open={panel.open}
        onOpenChange={(open) => !open && panel.close()}
        badge={{
          label: (panel.selected?.request_type ?? "other")
            .replace("_", " ")
            .toUpperCase(),
          tone: "violet",
        }}
        status={{
          label:
            (panel.selected?.status_code ?? 0) >= 400 ? "Failed" : "Succeeded",
          tone: (panel.selected?.status_code ?? 0) >= 400 ? "bad" : "good",
        }}
        title={
          panel.selected?.entities?.[0]
            ? `${ENTITY_LABEL[panel.selected.entities[0].type as EntityType] ?? panel.selected.entities[0].type}: ${panel.selected.entities[0].id}`
            : (panel.selected?.path ?? "Request")
        }
        meta={[
          panel.selected ? `${panel.selected.latency_ms.toFixed(2)}ms` : "",
          panel.selected
            ? format(
                new Date(panel.selected.created_at),
                "d MMM yyyy, HH:mm:ss",
              )
            : "",
        ].filter(Boolean)}
        copyId={panel.selected?.id}
        tabs={tabs}
        activeTab={tab}
        onTabChange={setTab}
        onPrev={panel.prev}
        onNext={panel.next}
        hasPrev={panel.hasPrev}
        hasNext={panel.hasNext}
      >
        {detailLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : !detail ? null : tab === "request" ? (
          <>
            <PanelSection label="Endpoint">
              <div className="flex items-center gap-2 font-mono text-xs text-onSurface-default-primary">
                <span className="rounded bg-surface-default-tertiary px-1.5 py-0.5">
                  {detail.method}
                </span>
                <span className="min-w-0 truncate">{detail.path}</span>
              </div>
            </PanelSection>

            <PanelSection label="Outcome">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 typo-body-sm">
                <dt className="text-onSurface-default-tertiary">Status</dt>
                <dd className={statusTone(detail.status_code)}>
                  {detail.status_code}
                </dd>
                <dt className="text-onSurface-default-tertiary">Latency</dt>
                <dd className="tabular-nums">
                  {detail.latency_ms.toFixed(2)}ms
                </dd>
                <dt className="text-onSurface-default-tertiary">Events</dt>
                <dd className="tabular-nums">{detail.event_count}</dd>
                <dt className="text-onSurface-default-tertiary">Auth</dt>
                <dd>{detail.auth_type}</dd>
                {detail.request_id && (
                  <>
                    <dt className="text-onSurface-default-tertiary">
                      Request ID
                    </dt>
                    <dd>
                      <CopyInline value={detail.request_id} />
                    </dd>
                  </>
                )}
              </dl>
            </PanelSection>

            {detail.error && (
              <PanelSection label="Error">
                <p className="rounded-md border border-memBorder-primary bg-surface-default-secondary p-2 typo-body-sm text-onSurface-danger-primary">
                  {detail.error}
                </p>
              </PanelSection>
            )}

            {detail.result_summary && (
              <PanelSection label="Result">
                <JsonBlock value={detail.result_summary} />
              </PanelSection>
            )}
          </>
        ) : tab === "input" ? (
          <PanelSection
            label="Request body"
            note="Credentials are removed before this is stored."
          >
            {detail.payload ? (
              <JsonBlock value={detail.payload} />
            ) : (
              <p className="typo-body-sm text-onSurface-default-tertiary">
                No body was captured for this request.
              </p>
            )}
          </PanelSection>
        ) : (
          <PanelSection
            label="Memories"
            note="Fetched live, so this reflects what each memory says now."
          >
            <div className="flex flex-col gap-2">
              {detail.memories.map((memory, index) => (
                <div
                  key={String(memory.id ?? index)}
                  className="rounded-md border border-memBorder-primary bg-surface-default-secondary p-2"
                >
                  {memory.deleted ? (
                    <p className="typo-body-sm text-onSurface-default-tertiary">
                      <span className="font-mono text-xs">
                        {String(memory.id)}
                      </span>{" "}
                      — deleted since this request
                    </p>
                  ) : (
                    <>
                      <p className="typo-body-sm text-onSurface-default-primary">
                        {String(memory.memory ?? memory.data ?? "—")}
                      </p>
                      <div className="mt-1">
                        <CopyInline value={String(memory.id)} />
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>
          </PanelSection>
        )}
      </DetailPanel>
    </div>
  );
}

export default function RequestsPage() {
  // usePanelRecord reads searchParams, which Next requires be inside Suspense.
  return (
    <Suspense fallback={<Skeleton className="m-6 h-64" />}>
      <RequestsPageInner />
    </Suspense>
  );
}
