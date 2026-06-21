"use client";

import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { EmptyState } from "@/components/self-hosted/empty-state";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { ANALYTICS_ENDPOINTS } from "@/utils/api-endpoints";
import { AnalyticsSummary } from "@/types/api";

export default function AnalyticsPage() {
  const { data, isLoading, refetch } = useApiQuery<AnalyticsSummary>(
    async () => (await api.get(ANALYTICS_ENDPOINTS.BASE)).data,
    { errorToast: "Failed to load analytics" },
  );

  const maxDaily = Math.max(
    ...(data?.by_day ?? []).map((item) => item.count),
    1,
  );
  const maxCategory = Math.max(
    ...(data?.category_distribution ?? []).map((item) => item.count),
    1,
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
                  <div className="flex h-56 items-end gap-2">
                    {data.by_day.map((item) => (
                      <div
                        key={item.date}
                        className="flex flex-1 flex-col items-center gap-2"
                      >
                        <div
                          className="w-full rounded-t bg-surface-default-brand"
                          style={{
                            height: `${Math.max(8, (item.count / maxDaily) * 100)}%`,
                          }}
                          title={`${item.date}: ${item.count}`}
                        />
                        <span className="text-[10px] text-onSurface-default-tertiary">
                          {item.date.slice(5)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-memBorder-primary">
              <CardHeader>
                <CardTitle className="text-sm">Category distribution</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {data.category_distribution.length === 0 ? (
                  <EmptyState
                    title="No categories"
                    description="Create categories to see distribution."
                  />
                ) : (
                  data.category_distribution.map((category) => (
                    <div key={category.name} className="space-y-1">
                      <div className="flex justify-between text-sm">
                        <span>{category.name}</span>
                        <span>{category.count}</span>
                      </div>
                      <div className="h-2 rounded bg-surface-default-secondary">
                        <div
                          className="h-2 rounded"
                          style={{
                            width: `${(category.count / maxCategory) * 100}%`,
                            backgroundColor: category.color,
                          }}
                        />
                      </div>
                    </div>
                  ))
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
                {data.by_path.map((item) => (
                  <div
                    key={item.path}
                    className="flex justify-between gap-4 text-sm"
                  >
                    <span className="truncate font-mono text-xs">
                      {item.path}
                    </span>
                    <span>{item.count}</span>
                  </div>
                ))}
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
                      className="flex justify-between text-sm"
                    >
                      <span>{item.status}</span>
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
