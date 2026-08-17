"use client";

import { useMemo } from "react";
import { format, parseISO } from "date-fns";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { cn } from "@/lib/utils";

export interface HistogramBucket {
  /** ISO date for the bucket start. */
  date: string;
  /** Count per series key, e.g. { add: 49, search: 26 }. */
  counts: Record<string, number>;
}

export interface HistogramSeries {
  key: string;
  label: string;
  /** Any CSS colour. Kept explicit so the legend and bars cannot drift apart. */
  color: string;
}

interface ActivityHistogramProps {
  buckets: HistogramBucket[];
  series: HistogramSeries[];
  height?: number;
  /** Called when a bar is clicked, for drill-down into that bucket. */
  onSelectBucket?: (bucket: HistogramBucket) => void;
  className?: string;
}

interface TooltipPayloadEntry {
  payload: HistogramBucket & { total: number };
}

function HistogramTooltip({
  active,
  payload,
  series,
}: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  series: HistogramSeries[];
}) {
  if (!active || !payload?.length) return null;
  const bucket = payload[0].payload;

  // Zero-count series are dropped rather than listed as 0: the tooltip is for
  // reading what happened, and a wall of zeroes buries the one line that did.
  const rows = series
    .map((s) => ({ ...s, value: bucket.counts[s.key] ?? 0 }))
    .filter((row) => row.value > 0);

  return (
    <div className="rounded-md border border-memBorder-primary bg-surface-default-primary p-2.5 shadow-lg">
      <p className="mb-1.5 font-mono text-[11px] text-onSurface-default-tertiary">
        {format(parseISO(bucket.date), "dd/MM/yyyy")}
      </p>
      <div className="flex items-center justify-between gap-6 border-b border-memBorder-primary pb-1.5">
        <span className="font-mono text-[11px] uppercase tracking-wide text-onSurface-default-secondary">
          Total
        </span>
        <span className="font-mono text-[11px] tabular-nums text-onSurface-default-primary">
          {bucket.total}
        </span>
      </div>
      <div className="mt-1.5 space-y-1">
        {rows.map((row) => (
          <div
            key={row.key}
            className="flex items-center justify-between gap-6"
          >
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="size-2 rounded-[2px]"
                style={{ backgroundColor: row.color }}
              />
              <span className="font-mono text-[11px] uppercase tracking-wide text-onSurface-default-secondary">
                {row.label}
              </span>
            </span>
            <span className="font-mono text-[11px] tabular-nums text-onSurface-default-primary">
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Stacked activity bars over time, sitting above a filtered list.
 *
 * Its job is to show where the traffic was, so the axis carries dates and
 * nothing else — no y-axis, no gridlines. The exact numbers live in the tooltip
 * and in the table below; competing with them here would just add ink.
 */
export function ActivityHistogram({
  buckets,
  series,
  height = 96,
  onSelectBucket,
  className,
}: ActivityHistogramProps) {
  const data = useMemo(
    () =>
      buckets.map((b) => ({
        ...b,
        total: Object.values(b.counts).reduce((sum, n) => sum + n, 0),
        // Recharts reads stack values off the top level, not out of `counts`.
        ...b.counts,
      })),
    [buckets],
  );

  if (buckets.length === 0) return null;

  return (
    <div className={cn("w-full", className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 4, right: 0, bottom: 0, left: 0 }}
          onClick={(state) => {
            const index = state?.activeTooltipIndex;
            if (onSelectBucket && typeof index === "number" && buckets[index]) {
              onSelectBucket(buckets[index]);
            }
          }}
        >
          <XAxis
            dataKey="date"
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
            minTickGap={48}
            tick={{ fontSize: 11, fill: "currentColor" }}
            className="text-onSurface-default-tertiary"
            tickFormatter={(value: string) => format(parseISO(value), "MMM d")}
          />
          <Tooltip
            cursor={{ fill: "currentColor", fillOpacity: 0.06 }}
            content={<HistogramTooltip series={series} />}
          />
          {series.map((s, i) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              stackId="activity"
              fill={s.color}
              // Only the top segment gets rounded corners, or every stacked
              // slice reads as its own separate bar.
              radius={i === series.length - 1 ? [2, 2, 0, 0] : undefined}
              maxBarSize={14}
              cursor={onSelectBucket ? "pointer" : undefined}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
