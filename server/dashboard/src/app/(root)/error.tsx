"use client";

import { useEffect } from "react";
import { ErrorState } from "@/components/shared/error-state";

/**
 * Boundary for the authenticated shell.
 *
 * Catches failures in the layout itself — nav, providers, auth bootstrap —
 * which sit above the /dashboard boundary and would otherwise escape to Next's
 * bare full-page error. No chrome is rendered here because the chrome is what
 * failed.
 */
export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[shell] render failed", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-2xl px-6 py-16">
      <ErrorState error={error} reset={reset} scope="The dashboard" />
    </div>
  );
}
