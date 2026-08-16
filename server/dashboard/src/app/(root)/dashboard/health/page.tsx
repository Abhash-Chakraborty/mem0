"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { SYSTEM_ENDPOINTS } from "@/utils/api-endpoints";
import { HealthSection, HealthStatus, SystemHealth } from "@/types/api";
import { cn } from "@/lib/utils";

const REFRESH_MS = 15000;

const STATUS_META: Record<
  HealthStatus,
  { label: string; icon: typeof CheckCircle2; className: string; dot: string }
> = {
  ok: {
    label: "Healthy",
    icon: CheckCircle2,
    className: "text-emerald-600 dark:text-emerald-400",
    dot: "bg-emerald-500",
  },
  degraded: {
    label: "Degraded",
    icon: AlertTriangle,
    className: "text-amber-600 dark:text-amber-400",
    dot: "bg-amber-500",
  },
  critical: {
    label: "Critical",
    icon: XCircle,
    className: "text-red-600 dark:text-red-400",
    dot: "bg-red-500",
  },
  unavailable: {
    label: "Unavailable",
    icon: CircleHelp,
    className: "text-onSurface-default-tertiary",
    dot: "bg-zinc-400",
  },
  unknown: {
    label: "Unknown",
    icon: CircleHelp,
    className: "text-onSurface-default-tertiary",
    dot: "bg-zinc-400",
  },
};

const SECTION_TITLES: Record<string, string> = {
  database: "Database",
  disk: "Disk",
  memory_store: "Memory store",
  webhooks: "Webhooks",
  requests: "API traffic",
  backups: "Backups",
  providers: "Model providers",
};

function meta(status: HealthStatus) {
  return STATUS_META[status] ?? STATUS_META.unknown;
}

function formatBytes(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

/** Turn a section's extra keys into readable label/value rows. */
function detailRows(name: string, section: HealthSection): [string, string][] {
  const rows: [string, string][] = [];
  const push = (label: string, value: unknown) => {
    if (value === null || value === undefined || value === "") return;
    rows.push([label, String(value)]);
  };

  switch (name) {
    case "database": {
      const pool = (section.pool ?? {}) as Record<string, number>;
      push("Latency", `${section.latency_ms} ms`);
      push("Host", section.host);
      if (pool.checkedout !== undefined)
        push("Connections in use", `${pool.checkedout} / ${pool.size ?? "?"}`);
      break;
    }
    case "disk":
      push("Used", `${formatBytes(section.used_bytes)} of ${formatBytes(section.total_bytes)}`);
      push("Free", formatBytes(section.free_bytes));
      push("Path", section.path);
      break;
    case "memory_store":
      push("Collection", section.collection);
      break;
    case "webhooks":
      push("Pending", section.pending);
      push("Failed", section.failed);
      break;
    case "requests":
      push("Requests (24h)", section.total);
      push("Errors", section.errors);
      push("Error rate", `${section.error_rate_percent}%`);
      push(
        "Latency p95",
        section.latency_p95_ms === null ? "—" : `${section.latency_p95_ms} ms`,
      );
      break;
    case "backups": {
      const latest = section.latest as { started_at?: string } | null;
      push(
        "Last backup",
        latest?.started_at ? new Date(latest.started_at).toLocaleString() : "Never",
      );
      push("Keeping", `${section.retention_count} snapshots`);
      if (Array.isArray(section.missing_tools) && section.missing_tools.length) {
        push("Missing tools", (section.missing_tools as string[]).join(", "));
      }
      break;
    }
    case "providers": {
      const configured = (section.configured ?? {}) as Record<string, boolean>;
      const enabled = Object.entries(configured)
        .filter(([, on]) => on)
        .map(([key]) => key);
      push("Extraction model", section.llm_model);
      push("Embedding model", section.embedder_model);
      push("Keys configured", enabled.length ? enabled.join(", ") : "none");
      break;
    }
  }

  if (section.error) push("Error", section.error);
  return rows;
}

export default function HealthPage() {
  const [lastChecked, setLastChecked] = useState<string>("");

  const healthQuery = useApiQuery<SystemHealth | undefined>(
    async () => (await api.get(SYSTEM_ENDPOINTS.HEALTH)).data,
    { errorToast: "Failed to load system health" },
  );

  const { refetch } = healthQuery;
  const health = healthQuery.data;

  useEffect(() => {
    if (health) setLastChecked(new Date().toLocaleTimeString());
  }, [health]);

  // Health is only useful if it is current, so the page polls itself.
  useEffect(() => {
    const id = setInterval(() => void refetch(), REFRESH_MS);
    return () => clearInterval(id);
  }, [refetch]);

  const overall = meta(health?.status ?? "unknown");
  const OverallIcon = overall.icon;

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-onSurface-default-primary">
            System health
          </h1>
          <p className="text-sm text-onSurface-default-tertiary mt-1">
            Live status of the services this instance depends on.
            {lastChecked && ` Checked at ${lastChecked}.`}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => void refetch()}
          disabled={healthQuery.isLoading}
        >
          <RefreshCw
            className={cn("size-4 mr-2", healthQuery.isLoading && "animate-spin")}
          />
          Refresh
        </Button>
      </div>

      <Card>
        <CardContent className="flex flex-wrap items-center gap-6 p-6">
          <OverallIcon className={cn("size-10 shrink-0", overall.className)} />
          <div className="min-w-0">
            <p className={cn("text-xl font-semibold", overall.className)}>
              {overall.label}
            </p>
            <p className="text-sm text-onSurface-default-tertiary">
              {health
                ? `Up for ${formatUptime(health.uptime_seconds)}`
                : "Contacting the server…"}
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Object.entries(health?.sections ?? {}).map(([name, section]) => {
          const sectionMeta = meta(section.status);
          const rows = detailRows(name, section);
          return (
            <Card key={name}>
              <CardContent className="p-5">
                <div className="flex items-center justify-between gap-3 mb-4">
                  <div className="flex items-center gap-2 min-w-0">
                    <span
                      className={cn("size-2 rounded-full shrink-0", sectionMeta.dot)}
                      aria-hidden
                    />
                    <h2 className="font-medium text-onSurface-default-primary truncate">
                      {SECTION_TITLES[name] ?? name}
                    </h2>
                  </div>
                  <Badge variant="secondary" className={sectionMeta.className}>
                    {sectionMeta.label}
                  </Badge>
                </div>

                {rows.length ? (
                  <dl className="flex flex-col gap-2">
                    {rows.map(([label, value]) => (
                      <div key={label} className="flex justify-between gap-4 text-sm">
                        <dt className="text-onSurface-default-tertiary shrink-0">
                          {label}
                        </dt>
                        <dd className="text-onSurface-default-primary text-right break-words">
                          {value}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="text-sm text-onSurface-default-tertiary">
                    No detail reported.
                  </p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {!healthQuery.isLoading && !health && (
        <p className="text-sm text-onSurface-danger-primary">
          Could not reach the health endpoint. The API may be down.
        </p>
      )}
    </div>
  );
}
