"use client";

import { RefreshCw } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { ANALYTICS_ENDPOINTS } from "@/utils/api-endpoints";
import { AnalyticsSummary } from "@/types/api";

const STATUS_COLORS: Record<string, string> = {
  delivered: "#10b981",
  pending: "#f59e0b",
  failed: "#f43f5e",
  disabled: "#a1a1aa",
};

export default function AnalyticsPage() {
  const { data, isLoading, refetch } = useApiQuery<AnalyticsSummary>(
    async () => (await api.get(ANALYTICS_ENDPOINTS.BASE)).data,
    { errorToast: "Failed to load analytics" },
  );

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold font-fustat">Analytics</h1>
          <p className="text-sm text-onSurface-default-secondary mt-1">
            Local request, memory, category, and webhook health.
          </p>
        </div>
        <Button variant="outline" onClick={refetch} disabled={isLoading}>
          <RefreshCw className="size-4 mr-2" />
          Refresh
        </Button>
      </div>

      {isLoading || !data ? (
        <TableSkeleton rows={6} columns={4} />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            {[
              { label: "Requests", value: data.total_requests },
              { label: "Success Rate", value: `${data.success_rate}%` },
              { label: "Avg Latency", value: `${data.average_latency_ms} ms` },
              { label: "Memories", value: data.total_memories },
            ].map((stat) => (
              <Card key={stat.label} className="border-memBorder-primary">
                <CardContent className="p-5">
                  <p className="text-xs text-onSurface-default-tertiary">
                    {stat.label}
                  </p>
                  <p className="mt-1 text-2xl font-semibold">{stat.value}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card className="border-memBorder-primary">
              <CardHeader>
                <CardTitle className="text-sm">Requests over time</CardTitle>
              </CardHeader>
              <CardContent>
                {data.by_day.length === 0 ? (
                  <EmptyState
                    title="No request data"
                    description="Requests appear after API traffic."
                  />
                ) : (
                  <div className="h-56 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={data.by_day.map((item) => ({
                          ...item,
                          label: item.date.slice(5),
                        }))}
                        margin={{ top: 8, right: 8, left: -20, bottom: 0 }}
                      >
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
                          cursor={{ fill: "rgba(124,58,237,0.08)" }}
                          contentStyle={{ fontSize: 12, borderRadius: 8 }}
                        />
                        <Bar
                          dataKey="count"
                          fill="#7c3aed"
                          radius={[4, 4, 0, 0]}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-memBorder-primary">
              <CardHeader>
                <CardTitle className="text-sm">Category distribution</CardTitle>
              </CardHeader>
              <CardContent>
                {data.category_distribution.length === 0 ? (
                  <EmptyState
                    title="No categories"
                    description="Create categories to see distribution."
                  />
                ) : (
                  <div className="flex items-center gap-4">
                    <div className="h-56 w-1/2">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={data.category_distribution}
                            dataKey="count"
                            nameKey="name"
                            innerRadius={45}
                            outerRadius={75}
                            paddingAngle={2}
                          >
                            {data.category_distribution.map((category) => (
                              <Cell
                                key={category.name}
                                fill={category.color || "#7c3aed"}
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
                      {data.category_distribution.map((category) => (
                        <div
                          key={category.name}
                          className="flex items-center justify-between gap-2 text-sm"
                        >
                          <span className="flex items-center gap-2 min-w-0">
                            <span
                              className="size-2.5 rounded-full shrink-0"
                              style={{ backgroundColor: category.color }}
                            />
                            <span className="truncate">{category.name}</span>
                          </span>
                          <span className="text-onSurface-default-secondary">
                            {category.count}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card className="border-memBorder-primary">
              <CardHeader>
                <CardTitle className="text-sm">Top endpoints</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.by_path.length === 0 ? (
                  <EmptyState
                    title="No endpoint data"
                    description="Endpoints appear after API traffic."
                  />
                ) : (
                  data.by_path.map((item) => (
                    <div
                      key={item.path}
                      className="flex justify-between gap-4 text-sm"
                    >
                      <span className="truncate font-mono text-xs">
                        {item.path}
                      </span>
                      <span>{item.count}</span>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>

            <Card className="border-memBorder-primary">
              <CardHeader>
                <CardTitle className="text-sm">Webhook deliveries</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.webhook_deliveries.length === 0 ? (
                  <EmptyState
                    title="No webhook data"
                    description="Deliveries appear after webhooks run."
                  />
                ) : (
                  data.webhook_deliveries.map((item) => (
                    <div
                      key={item.status}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="flex items-center gap-2 capitalize">
                        <span
                          className="size-2.5 rounded-full"
                          style={{
                            backgroundColor:
                              STATUS_COLORS[item.status] ?? "#a1a1aa",
                          }}
                        />
                        {item.status}
                      </span>
                      <span>{item.count}</span>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
