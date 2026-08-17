"use client";

import { RefreshCw, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  TimeRangePicker,
  type TimeRange,
} from "@/components/shared/time-range-picker";

export interface QuickFilter {
  id: string;
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
}

interface FilterBarProps {
  /** Placeholder for the search input. Mention the typed syntax where it helps. */
  placeholder?: string;
  query: string;
  onQueryChange: (value: string) => void;
  /** Fired on Enter, so typing does not trigger a request per keystroke. */
  onSubmit?: () => void;

  range?: TimeRange;
  onRangeChange?: (range: TimeRange) => void;

  quickFilters?: QuickFilter[];
  activeFilters?: string[];
  onToggleFilter?: (id: string) => void;

  /** Locked scope, e.g. "User is alice" on an entity detail page. */
  scopePill?: React.ReactNode;

  onRefresh?: () => void;
  isRefreshing?: boolean;

  /** Shown when anything is active. Clears filters and query. */
  onClearAll?: () => void;

  className?: string;
}

/**
 * Search, quick filters and time range for a list view.
 *
 * Quick filters are toggle chips rather than a dropdown because they are the
 * handful of cuts people make constantly — narrowing to adds, or hiding
 * playground traffic — and a dropdown turns a one-click action into three.
 */
export function FilterBar({
  placeholder = "Search…",
  query,
  onQueryChange,
  onSubmit,
  range,
  onRangeChange,
  quickFilters,
  activeFilters = [],
  onToggleFilter,
  scopePill,
  onRefresh,
  isRefreshing,
  onClearAll,
  className,
}: FilterBarProps) {
  const hasActive = activeFilters.length > 0 || query.trim().length > 0;

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[240px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-onSurface-default-tertiary" />
          <Input
            value={query}
            placeholder={placeholder}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSubmit?.();
              if (e.key === "Escape" && query) onQueryChange("");
            }}
            className="pl-9 pr-9"
          />
          {query && (
            <button
              type="button"
              onClick={() => onQueryChange("")}
              aria-label="Clear search"
              className="absolute right-3 top-1/2 -translate-y-1/2 text-onSurface-default-tertiary transition-colors hover:text-onSurface-default-primary"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>

        {range && onRangeChange && (
          <TimeRangePicker value={range} onChange={onRangeChange} />
        )}

        {onRefresh && (
          <Button
            variant="outline"
            size="icon"
            onClick={onRefresh}
            disabled={isRefreshing}
            aria-label="Refresh"
          >
            <RefreshCw
              className={cn("size-4", isRefreshing && "animate-spin")}
            />
          </Button>
        )}
      </div>

      {(quickFilters?.length || scopePill || hasActive) && (
        <div className="flex flex-wrap items-center gap-2">
          {quickFilters?.map((filter) => {
            const active = activeFilters.includes(filter.id);
            const Icon = filter.icon;
            return (
              <button
                key={filter.id}
                type="button"
                aria-pressed={active}
                onClick={() => onToggleFilter?.(filter.id)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
                  active
                    ? "border-transparent bg-violet-100 text-violet-700 dark:bg-violet-950/60 dark:text-violet-300"
                    : "border-memBorder-primary text-onSurface-default-secondary hover:bg-surface-default-secondary",
                )}
              >
                {Icon && <Icon className="size-3.5" />}
                {filter.label}
              </button>
            );
          })}

          {scopePill}

          {hasActive && onClearAll && (
            <button
              type="button"
              onClick={onClearAll}
              className="ml-auto text-xs text-onSurface-default-tertiary underline underline-offset-4 transition-colors hover:text-onSurface-default-primary"
            >
              Clear all
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * A filter the user cannot remove, e.g. the entity a detail page is about.
 * Visually distinct from a quick filter so it does not read as clickable.
 */
export function ScopePill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-100 px-3 py-1 text-xs text-violet-700 dark:bg-violet-950/60 dark:text-violet-300">
      <span className="opacity-70">{label} is</span>
      <span className="font-mono">{value}</span>
    </span>
  );
}
