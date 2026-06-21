import { Skeleton } from "@/components/ui/skeleton";

interface TableSkeletonProps {
  rows?: number;
  columns?: number;
}

export function TableSkeleton({ rows = 5, columns = 5 }: TableSkeletonProps) {
  // Clamp to non-negative lengths: Array(-1) throws "Invalid array length",
  // which would crash any caller passing columns < 2 (e.g. a 1-column skeleton).
  const rowCount = Math.max(0, rows);
  const headerCols = Math.max(0, columns - 1);
  const bodyCols = Math.max(0, columns - 2);
  return (
    <div className="w-full">
      {/* Table Header */}
      <div className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50">
        <div className="flex items-center gap-4 px-4 py-3">
          <Skeleton className="size-4 rounded" />
          {[...Array(headerCols)].map((_, i) => (
            <Skeleton key={i} className="h-4 flex-1" />
          ))}
        </div>
      </div>

      {/* Table Rows */}
      <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
        {[...Array(rowCount)].map((_, rowIndex) => (
          <div key={rowIndex} className="flex items-center gap-4 px-4 py-3">
            <Skeleton className="size-4 rounded" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-3 w-3/4" />
            </div>
            {[...Array(bodyCols)].map((_, colIndex) => (
              <Skeleton key={colIndex} className="h-4 w-24" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
