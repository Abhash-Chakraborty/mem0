"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { ErrorState } from "@/components/shared/error-state";

/**
 * Boundary for every page under /dashboard.
 *
 * Placed at the segment rather than per page so a new route is protected the
 * moment it exists: the failure mode this fixes is a page throwing with no
 * boundary above it, which Next renders as a full-viewport
 * "Application error: a client-side exception has occurred" with no way back.
 * Keeping it here means the chrome — sidebar, nav — survives the failure.
 */
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const pathname = usePathname();

  useEffect(() => {
    console.error(`[dashboard] render failed at ${pathname}`, error);
  }, [error, pathname]);

  // "/dashboard/graph" -> "Graph"; the last segment is the page the user is on.
  const segment = pathname.split("/").filter(Boolean).pop() ?? "dashboard";
  const scope = segment
    .replace(/-/g, " ")
    .replace(/^\w/, (c) => c.toUpperCase());

  return (
    <div className="space-y-4">
      <h1 className="font-fustat text-xl font-semibold">{scope}</h1>
      <ErrorState error={error} reset={reset} scope={scope} />
    </div>
  );
}
