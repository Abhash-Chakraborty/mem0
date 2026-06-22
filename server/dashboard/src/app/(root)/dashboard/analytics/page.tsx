"use client";

import { useMemo, useState } from "react";
import { format, subDays } from "date-fns";
import type { DateRange } from "react-day-picker";
import {
  Area,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  CalendarDays,
  Database,
  Gauge,
  PlusCircle,
  RefreshCw,
  Search,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { ANALYTICS_ENDPOINTS } from "@/utils/api-endpoints";
import { AnalyticsSummary } from "@/types/api";
import { cn } from "@/lib/utils";

const PRESETS = [
  { key: "all", label: "All Time" },
  { key: "1d", label: "1d" },
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
] as const;

const ENTITY_COLORS: Record<string, string> = {
  user: "#0ea5e9",
  agent: "#ef4444",
  run: "#f59e0b",
  app: "#8b5cf6",
};

export default function DashboardPage() {
  const [range, setRange] = useState<string>("all");
  const [customRange, setCustomRange] = useState<DateRange | undefined>();
  const [draftRange, setDraftRange] = useState<DateRange | undefined>();
  const [pickerOpen, setPickerOpen] = useState(false);

  const queryParams = useMemo(() => {
    if (range === "custom" && customRange?.from) {
      const from = format(customRange.from, "yyyy-MM-dd");
      const to = format(customRange.to ?? customRange.from, "yyyy-MM-dd");
      return { start: from, end: to } as Record<string, string>;
    }
    return { range } as Record<string, string>;
  }, [range, customRange]);

  const { data, isLoading, refetch } = useApiQuery<AnalyticsSummary>(
    async () =>
      (await api.get(ANALYTICS_ENDPOINTS.BASE, { params: queryParams })).data,
    {
      errorToast: "Failed to load dashboard",
      deps: [JSON.stringify(queryParams)],
    },
  );

  const entityPie = useMemo(() => {
    if (!data) return [];
    return (["user", "agent", "run", "app"] as const)
      .map((type) => ({
        name: type,
        value: data.entities_by_type?.[type] ?? 0,
      }))
      .filter((item) => item.value > 0);
  }, [data]);

  const chartData = useMemo(
    () =>
      (data?.series ?? []).map((point) => ({
        ...point,
        label: point.date.slice(5),
      })),
    [data],
  );

  const rangeLabel =
    range === "custom" && customRange?.from
      ? `${format(customRange.from, "MMM d")} – ${format(
          customRange.to ?? customRange.from,
          "MMM d",
        )}`
      : "Pick a date range";

  const stats = data
    ? [
        {
          label: "Total Memories",
          value: data.total_memories,
          icon: Database,
          color: "text-violet-500",
        },
        {
          label: "Requests",
          value: data.total_requests,
          icon: Gauge,
          color: "text-emerald-500",
        },
        {
          label: "Retrieval Events",
          value: data.retrieval_events,
          icon: Search,
          color: "text-sky-500",
        },
        {
          label: "Add Events",
          value: data.add_events,
          icon: PlusCircle,
          color: "text-amber-500",
        },
      ]
    : [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold font-fustat">Dashboard</h1>
          <p className="text-sm text-onSurface-default-secondary mt-1">
            Memories, requests, and entities at a glance.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refetch} disabled={isLoading}>
          <RefreshCw className="size-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Date range controls */}
      <div className="flex flex-wrap items-center gap-2">
        <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className={cn(
                "gap-2",
                range === "custom" && "border-memPurple-400 text-memPurple-500",
              )}
              onClick={() => setDraftRange(customRange)}
            >
              <CalendarDays className="size-4" />
              {rangeLabel}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              mode="range"
              numberOfMonths={2}
              selected={draftRange}
              onSelect={setDraftRange}
              defaultMonth={subDays(new Date(), 30)}
            />
            <div className="flex items-center justify-end gap-2 border-t border-memBorder-primary p-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setDraftRange(undefined);
                  setPickerOpen(false);
                }}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={!draftRange?.from}
                onClick={() => {
                  setCustomRange(draftRange);
                  setRange("custom");
                  setPickerOpen(false);
                }}
              >
                Apply
              </Button>
            </div>
          </PopoverContent>
        </Popover>

        <div className="flex items-center gap-1">
          {PRESETS.map((preset) => (
            <Button
              key={preset.key}
              variant="ghost"
              size="sm"
              className={cn(
                "h-8",
                range === preset.key &&
                  "bg-surface-default-secondary text-onSurface-default-primary",
              )}
              onClick={() => {
                setRange(preset.key);
                setCustomRange(undefined);
              }}
            >
              {preset.label}
            </Button>
          ))}
        </div>
      </div>

      {isLoading || !data ? (
        <TableSkeleton rows={6} columns={4} />
      ) : (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {stats.map((stat) => (
              <Card key={stat.label} className="border-memBorder-primary">
                <CardContent className="p-5">
                  <div className="flex items-center gap-2 text-xs text-onSurface-default-tertiary">
                    <stat.icon className={cn("size-4", stat.color)} />
                    {stat.label}
                  </div>
                  <p className="mt-2 text-3xl font-semibold">{stat.value}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Secondary metrics */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              { label: "Entities", value: data.entities_total },
              { label: "Entities / Request", value: data.entities_per_request },
              { label: "Success Rate", value: `${data.success_rate}%` },
              { label: "Avg Latency", value: `${data.average_latency_ms} ms` },
            ].map((stat) => (
              <Card key={stat.label} className="border-memBorder-primary">
                <CardContent className="p-4">
                  <p className="text-xs text-onSurface-default-tertiary">
                    {stat.label}
                  </p>
                  <p className="mt-1 text-xl font-semibold">{stat.value}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="border-memBorder-primary lg:col-span-2">
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="text-sm">Requests over time</CardTitle>
                <span className="text-xs text-onSurface-default-tertiary">
                  {data.total_requests} total
                </span>
              </CardHeader>
              <CardContent>
                {chartData.length === 0 ? (
                  <EmptyState
                    title="No activity in this range"
                    description="Pick a wider date range or send some API traffic."
                  />
                ) : (
                  <div className="h-64 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart
                        data={chartData}
                        margin={{ top: 8, right: 8, left: -20, bottom: 0 }}
                      >
                        <defs>
                          <linearGradient
                            id="reqFill"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                          >
                            <stop
                              offset="0%"
                              stopColor="#7c3aed"
                              stopOpacity={0.3}
                            />
                            <stop
                              offset="100%"
                              stopColor="#7c3aed"
                              stopOpacity={0}
                            />
                          </linearGradient>
                        </defs>
                        <CartesianGrid
                          strokeDasharray="3 3"
                          vertical={false}
                          stroke="currentColor"
                          className="text-memBorder-primary"
                        />
                        <XAxis
                          dataKey="label"
                          tick={{ fontSize: 11 }}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          allowDecimals={false}
                          tick={{ fontSize: 11 }}
                          tickLine={false}
                          axisLine={false}
                        />
                        <RechartsTooltip
                          contentStyle={{ fontSize: 12, borderRadius: 8 }}
                        />
                        <Area
                          type="monotone"
                          dataKey="requests"
                          name="Requests"
                          stroke="#7c3aed"
                          strokeWidth={2}
                          fill="url(#reqFill)"
                        />
                        <Line
                          type="monotone"
                          dataKey="retrievals"
                          name="Retrievals"
                          stroke="#0ea5e9"
                          strokeWidth={2}
                          dot={false}
                        />
                        <Line
                          type="monotone"
                          dataKey="adds"
                          name="Adds"
                          stroke="#f59e0b"
                          strokeWidth={2}
                          dot={false}
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-memBorder-primary">
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="text-sm">Entities</CardTitle>
                <Users className="size-4 text-onSurface-default-tertiary" />
              </CardHeader>
              <CardContent>
                {entityPie.length === 0 ? (
                  <EmptyState
                    title="No entities yet"
                    description="Entities appear once memories carry user/agent/run ids."
                  />
                ) : (
                  <div className="flex items-center gap-4">
                    <div className="h-44 w-1/2">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={entityPie}
                            dataKey="value"
                            nameKey="name"
                            innerRadius={40}
                            outerRadius={68}
                            paddingAngle={2}
                          >
                            {entityPie.map((entry) => (
                              <Cell
                                key={entry.name}
                                fill={ENTITY_COLORS[entry.name] ?? "#6b7280"}
                              />
                            ))}
                          </Pie>
                          <RechartsTooltip
                            contentStyle={{ fontSize: 12, borderRadius: 8 }}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="flex-1 space-y-1.5">
                      {entityPie.map((entry) => (
                        <div
                          key={entry.name}
                          className="flex items-center justify-between gap-2 text-sm"
                        >
                          <span className="flex items-center gap-2 capitalize">
                            <span
                              className="size-2.5 rounded-full"
                              style={{
                                backgroundColor:
                                  ENTITY_COLORS[entry.name] ?? "#6b7280",
                              }}
                            />
                            {entry.name}
                          </span>
                          <span className="text-onSurface-default-secondary">
                            {entry.value}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Category distribution */}
          {data.category_distribution.length > 0 && (
            <Card className="border-memBorder-primary">
              <CardHeader>
                <CardTitle className="text-sm">Category distribution</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-x-6 gap-y-2">
                  {data.category_distribution.map((category) => (
                    <div
                      key={category.name}
                      className="flex items-center gap-2 text-sm"
                    >
                      <span
                        className="size-2.5 rounded-full"
                        style={{ backgroundColor: category.color }}
                      />
                      <span>{category.name}</span>
                      <span className="text-onSurface-default-tertiary">
                        {category.count}
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
