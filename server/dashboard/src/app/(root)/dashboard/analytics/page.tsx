"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { format } from "date-fns";
import { ArrowRight, RefreshCw } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";
import { api } from "@/utils/api";
import { ANALYTICS_ENDPOINTS } from "@/utils/api-endpoints";
import { getErrorMessage } from "@/lib/error-message";
import { useScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip as UiTooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { EmptyState } from "@/components/self-hosted/empty-state";

interface SeriesPoint {
  date: string;
  counts: Record<string, number>;
  total: number;
}

interface Overview {
  total_memories: number;
  active_entities: number;
  retrieval_events: number;
  add_events: number;
  categorized_memories: number;
  lifecycle_counts: Record<string, number>;
  requests_series: SeriesPoint[];
  entities_series: SeriesPoint[];
  category_distribution: { name: string; color: string; count: number }[];
  range: string;
}

const RANGES = [
  { id: "all", label: "All time" },
  { id: "1d", label: "1d" },
  { id: "7d", label: "7d" },
  { id: "30d", label: "30d" },
  { id: "90d", label: "90d" },
] as const;

/**
 * A stat card's definition, shown on hover. "Retrieval event" is not
 * self-evident, and a number nobody can define is a number nobody trusts.
 */
const DEFINITIONS: Record<string, string> = {
  "Total memories":
    "Every memory in this project, regardless of the selected range.",
  "Active entities":
    "Users, agents and sessions that had a memory recorded in this range.",
  "Retrieval events":
    "Searches and reads — one per search, get, or list request.",
  "Add events": "Requests that wrote memories.",
};

const SERIES_COLORS: Record<string, string> = {
  add: "#6D4AFF",
  search: "#3B9EFF",
  get_all: "#26B47F",
  get: "#8FBF3F",
  update: "#E0A94A",
  delete: "#E0674A",
  delete_all: "#C24A6B",
  other: "#8C8AA0",
  user: "#6D4AFF",
  agent: "#3B9EFF",
  session: "#26B47F",
  total: "#6D4AFF",
};

function StatCard({
  label,
  value,
  loading,
}: {
  label: string;
  value: number;
  loading: boolean;
}) {
  return (
    <Card>
      <CardContent className="py-4">
        <UiTooltip>
          <TooltipTrigger asChild>
            <div className="cursor-help typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
              {label}
            </div>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            {DEFINITIONS[label]}
          </TooltipContent>
        </UiTooltip>
        {loading ? (
          <Skeleton className="mt-2 h-7 w-20" />
        ) : (
          <div className="mt-1 typo-heading-md tabular-nums text-onSurface-default-primary">
            {value.toLocaleString()}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ChartTooltip({ active, payload, label, daily }: any) {
  if (!active || !payload?.length) return null;
  const rows = payload.filter((p: any) => p.value > 0);
  if (rows.length === 0) return null;

  return (
    <div className="rounded-md border border-memBorder-secondary bg-surface-default-primary px-3 py-2 shadow-lg">
      <div className="typo-caption-sm text-onSurface-default-tertiary">
        {format(new Date(label), daily ? "d MMM yyyy" : "d MMM, HH:mm")}
      </div>
      {rows.map((row: any) => (
        <div
          key={row.dataKey}
          className="mt-1 flex items-center gap-2 typo-body-sm"
        >
          <span
            aria-hidden
            className="size-2 rounded-full"
            style={{ backgroundColor: row.color }}
          />
          <span className="text-onSurface-default-secondary">{row.name}</span>
          <span className="ml-auto tabular-nums text-onSurface-default-primary">
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function SeriesPanel({
  title,
  href,
  total,
  series,
  daily,
  loading,
}: {
  title: string;
  href: string;
  total: number;
  series: SeriesPoint[];
  daily: boolean;
  loading: boolean;
}) {
  const [breakdown, setBreakdown] = useState(false);

  const keys = useMemo(() => {
    const seen = new Set<string>();
    for (const point of series)
      for (const key of Object.keys(point.counts)) seen.add(key);
    return [...seen].sort();
  }, [series]);

  const data = useMemo(
    () =>
      series.map((point) => ({
        date: point.date,
        total: point.total,
        ...point.counts,
      })),
    [series],
  );

  const shown = breakdown ? keys : ["total"];

  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
              {title}
            </div>
            {loading ? (
              <Skeleton className="mt-1 h-7 w-24" />
            ) : (
              <div className="mt-0.5 typo-heading-sm tabular-nums text-onSurface-default-primary">
                {total.toLocaleString()}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {keys.length > 1 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setBreakdown((v) => !v)}
                aria-pressed={breakdown}
              >
                {breakdown ? "Combine" : "View breakdown"}
              </Button>
            )}
            <Link
              href={href}
              className="flex items-center gap-1 typo-body-sm text-onSurface-default-secondary hover:text-onSurface-default-primary"
            >
              View
              <ArrowRight className="size-3.5" />
            </Link>
          </div>
        </div>

        <div className="mt-3 h-[180px]">
          {loading ? (
            <Skeleton className="size-full" />
          ) : data.length === 0 ? (
            <div className="grid size-full place-items-center typo-body-sm text-onSurface-default-tertiary">
              Nothing in this range.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={data}
                margin={{ top: 4, right: 4, bottom: 0, left: -20 }}
              >
                <defs>
                  {shown.map((key) => (
                    <linearGradient
                      key={key}
                      id={`fill-${title}-${key}`}
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="1"
                    >
                      <stop
                        offset="0%"
                        stopColor={SERIES_COLORS[key] ?? SERIES_COLORS.other}
                        stopOpacity={0.28}
                      />
                      <stop
                        offset="100%"
                        stopColor={SERIES_COLORS[key] ?? SERIES_COLORS.other}
                        stopOpacity={0.02}
                      />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="currentColor"
                  opacity={0.12}
                  vertical={false}
                />
                <XAxis
                  dataKey="date"
                  tickFormatter={(value) =>
                    format(new Date(value), daily ? "d MMM" : "HH:mm")
                  }
                  tick={{ fontSize: 11 }}
                  stroke="currentColor"
                  opacity={0.45}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  stroke="currentColor"
                  opacity={0.45}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                  width={40}
                />
                <Tooltip content={<ChartTooltip daily={daily} />} />
                {shown.map((key) => (
                  <Area
                    key={key}
                    type="monotone"
                    dataKey={key}
                    name={key === "total" ? title : key.replace("_", " ")}
                    stroke={SERIES_COLORS[key] ?? SERIES_COLORS.other}
                    strokeWidth={1.5}
                    fill={`url(#fill-${title}-${key})`}
                    stackId={breakdown ? "1" : undefined}
                    dot={false}
                    activeDot={{ r: 3 }}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function AnalyticsInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { scope } = useScope();

  // The range lives in the URL, so a link to "the last 30 days" is a real link.
  const range = searchParams.get("range") ?? "7d";
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);

  const setRange = (next: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("range", next);
    router.replace(`?${params.toString()}`, { scroll: false });
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Overview>(ANALYTICS_ENDPOINTS.BASE, {
        params: { range },
      });
      setData(res.data);
    } catch (err) {
      toast.error(getErrorMessage(err, "Could not load the dashboard."));
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    void load();
  }, [load]);

  const daily = range !== "1d";
  const totalCategorised = data?.categorized_memories ?? 0;
  const isFresh = !loading && data !== null && data.total_memories === 0;

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="typo-heading-md text-onSurface-default-primary">
            Dashboard
          </h1>
          <p className="typo-body-sm text-onSurface-default-tertiary">
            {scope ? `${scope.project_name} · ${scope.org_name}` : "Overview"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-0.5 rounded-md border border-memBorder-primary p-0.5">
            {RANGES.map((option) => (
              <button
                key={option.id}
                onClick={() => setRange(option.id)}
                aria-pressed={range === option.id}
                className={cn(
                  "rounded px-2 py-1 typo-caption-sm transition-colors",
                  range === option.id
                    ? "bg-surface-default-tertiary text-onSurface-default-primary"
                    : "text-onSurface-default-tertiary hover:text-onSurface-default-secondary",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw
              className={cn("mr-1.5 size-3.5", loading && "animate-spin")}
            />
            Refresh
          </Button>
        </div>
      </header>

      {isFresh ? (
        <EmptyState
          title="No memories yet"
          description="Add your first memory and this page fills in. Point a client at POST /memories with an API key, or try the Recall playground to see the shape of a request."
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Total memories"
              value={data?.total_memories ?? 0}
              loading={loading}
            />
            <StatCard
              label="Active entities"
              value={data?.active_entities ?? 0}
              loading={loading}
            />
            <StatCard
              label="Retrieval events"
              value={data?.retrieval_events ?? 0}
              loading={loading}
            />
            <StatCard
              label="Add events"
              value={data?.add_events ?? 0}
              loading={loading}
            />
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <SeriesPanel
              title="Requests"
              href="/dashboard/requests"
              total={(data?.retrieval_events ?? 0) + (data?.add_events ?? 0)}
              series={data?.requests_series ?? []}
              daily={daily}
              loading={loading}
            />
            <SeriesPanel
              title="Entities"
              href="/dashboard/entities"
              total={data?.active_entities ?? 0}
              series={data?.entities_series ?? []}
              daily={daily}
              loading={loading}
            />
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card>
              <CardContent className="py-4">
                <div className="flex items-center justify-between">
                  <div className="typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
                    Categories
                  </div>
                  <Link
                    href="/dashboard/settings/categories"
                    className="typo-caption-sm text-onSurface-default-secondary hover:text-onSurface-default-primary"
                  >
                    Manage
                  </Link>
                </div>
                {loading ? (
                  <Skeleton className="mt-3 h-24 w-full" />
                ) : (data?.category_distribution.length ?? 0) === 0 ? (
                  <p className="mt-2 typo-body-sm text-onSurface-default-tertiary">
                    No categories defined yet.
                  </p>
                ) : (
                  <div className="mt-3 flex flex-col gap-2">
                    {data!.category_distribution.slice(0, 8).map((category) => {
                      const max = Math.max(
                        1,
                        ...data!.category_distribution.map((c) => c.count),
                      );
                      return (
                        <div
                          key={category.name}
                          className="flex items-center gap-2"
                        >
                          <span className="w-28 shrink-0 truncate typo-body-sm text-onSurface-default-secondary">
                            {category.name}
                          </span>
                          <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-default-tertiary">
                            <div
                              className="h-full rounded-full"
                              style={{
                                width: `${(category.count / max) * 100}%`,
                                backgroundColor: category.color,
                              }}
                            />
                          </div>
                          <span className="w-10 shrink-0 text-right tabular-nums typo-caption-sm text-onSurface-default-tertiary">
                            {category.count}
                          </span>
                        </div>
                      );
                    })}
                    <p className="mt-1 typo-caption-sm text-onSurface-default-tertiary">
                      {totalCategorised} memories categorised in this range.
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="py-4">
                <div className="flex items-center justify-between">
                  <div className="typo-caption-sm uppercase tracking-wide text-onSurface-default-tertiary">
                    Dream activity
                  </div>
                  <Link
                    href="/dashboard/dream"
                    className="typo-caption-sm text-onSurface-default-secondary hover:text-onSurface-default-primary"
                  >
                    View
                  </Link>
                </div>
                {loading ? (
                  <Skeleton className="mt-3 h-24 w-full" />
                ) : Object.keys(data?.lifecycle_counts ?? {}).length === 0 ? (
                  <p className="mt-2 typo-body-sm text-onSurface-default-tertiary">
                    Dream has not changed any memory yet. Everything is active.
                  </p>
                ) : (
                  <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2">
                    {Object.entries(data!.lifecycle_counts).map(
                      ([state, count]) => (
                        <div
                          key={state}
                          className="flex items-center justify-between"
                        >
                          <dt className="typo-body-sm capitalize text-onSurface-default-secondary">
                            {state}
                          </dt>
                          <dd className="tabular-nums typo-body-sm text-onSurface-default-primary">
                            {count}
                          </dd>
                        </div>
                      ),
                    )}
                  </dl>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

export default function AnalyticsPage() {
  // useSearchParams needs a Suspense boundary above it.
  return (
    <Suspense fallback={<Skeleton className="m-6 h-96" />}>
      <AnalyticsInner />
    </Suspense>
  );
}
