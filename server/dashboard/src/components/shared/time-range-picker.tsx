"use client";

import { CalendarDays, ChevronDown } from "lucide-react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type RangeKey = "all" | "1d" | "7d" | "30d" | "custom";

export interface TimeRange {
  key: RangeKey;
  /** Only set when `key` is "custom". */
  from?: Date;
  to?: Date;
}

const PRESETS: { key: RangeKey; label: string }[] = [
  { key: "all", label: "All time" },
  { key: "1d", label: "1d" },
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
];

export function formatRange(range: TimeRange): string {
  if (range.key === "custom" && range.from) {
    const from = format(range.from, "d MMM");
    const to = range.to ? format(range.to, "d MMM") : "now";
    return `${from} – ${to}`;
  }
  return PRESETS.find((p) => p.key === range.key)?.label ?? "All time";
}

/** Resolve a range into the query params the API expects. */
export function rangeToParams(range: TimeRange): Record<string, string> {
  if (range.key === "custom") {
    const params: Record<string, string> = {};
    if (range.from) params.from = range.from.toISOString();
    if (range.to) params.to = range.to.toISOString();
    return params;
  }
  return range.key === "all" ? {} : { range: range.key };
}

interface TimeRangePickerProps {
  value: TimeRange;
  onChange: (range: TimeRange) => void;
  className?: string;
}

/**
 * The time control shared by every activity view.
 *
 * Presets and the custom picker live in one popover rather than as a separate
 * button row, because on the pages that use this the horizontal space is
 * already spent on search and filters.
 */
export function TimeRangePicker({
  value,
  onChange,
  className,
}: TimeRangePickerProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn("gap-2 font-normal", className)}
        >
          <CalendarDays className="size-4 text-onSurface-default-tertiary" />
          {formatRange(value)}
          <ChevronDown className="size-3.5 text-onSurface-default-tertiary" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-auto p-0">
        <div className="flex flex-col gap-1 border-b border-memBorder-primary p-2">
          {PRESETS.map((preset) => (
            <button
              key={preset.key}
              type="button"
              onClick={() => onChange({ key: preset.key })}
              className={cn(
                "rounded px-2 py-1.5 text-left text-sm transition-colors",
                value.key === preset.key
                  ? "bg-surface-default-tertiary text-onSurface-default-primary"
                  : "text-onSurface-default-secondary hover:bg-surface-default-secondary",
              )}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <Calendar
          mode="range"
          selected={{ from: value.from, to: value.to }}
          onSelect={(selection) => {
            if (!selection?.from) return;
            onChange({
              key: "custom",
              from: selection.from,
              to: selection.to,
            });
          }}
          className="p-2"
        />
      </PopoverContent>
    </Popover>
  );
}
