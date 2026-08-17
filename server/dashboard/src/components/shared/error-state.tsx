"use client";

import { useState } from "react";
import { AlertTriangle, Check, Copy, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { APP_VERSION, GIT_SHA } from "@/lib/build-info";

export interface ErrorStateProps {
  /** The error React caught. `digest` is set by Next for server-thrown errors. */
  error: Error & { digest?: string };
  /** Re-renders the failed segment. Provided by Next to every error.tsx. */
  reset?: () => void;
  /** Which part of the app failed, e.g. "Graph". Shown to the user verbatim. */
  scope: string;
}

/**
 * The UI behind every error boundary in the dashboard.
 *
 * Without a boundary, Next renders its own bare "Application error: a
 * client-side exception has occurred" over the whole viewport, which tells the
 * user nothing and leaves them no way back. This keeps the failure contained to
 * the segment that threw, names it, and gives two exits: retry, or copy enough
 * detail that a bug report is actionable without a screenshot.
 */
export function ErrorState({ error, reset, scope }: ErrorStateProps) {
  const [copied, setCopied] = useState(false);

  const details = [
    `scope: ${scope}`,
    `message: ${error.message || "(no message)"}`,
    error.digest ? `digest: ${error.digest}` : null,
    `build: ${APP_VERSION} (${GIT_SHA})`,
    `path: ${typeof window !== "undefined" ? window.location.pathname : "?"}`,
    `time: ${new Date().toISOString()}`,
    error.stack ? `\n${error.stack}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(details);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard is unavailable over plain HTTP on some hosts. The details are
      // already on screen below, so failing to copy is not worth an error toast.
    }
  };

  return (
    <Card className="border-memBorder-primary">
      <CardContent className="flex flex-col items-start gap-4 p-6">
        <div className="flex items-start gap-3">
          <div className="grid size-9 shrink-0 place-items-center rounded-md bg-surface-default-secondary">
            <AlertTriangle className="size-4 text-onSurface-danger-primary" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium text-onSurface-default-primary">
              {scope} could not be displayed
            </p>
            <p className="max-w-prose text-xs text-onSurface-default-tertiary">
              Something in this view threw while rendering. The rest of the
              dashboard is unaffected.
            </p>
          </div>
        </div>

        <pre className="max-h-40 w-full overflow-auto rounded-md bg-surface-default-secondary p-3 text-left font-mono text-[11px] leading-relaxed text-onSurface-default-secondary">
          {error.message || "Unknown error"}
          {error.digest ? `\n\ndigest: ${error.digest}` : ""}
        </pre>

        <div className="flex flex-wrap gap-2">
          {reset && (
            <Button variant="outline" size="sm" onClick={reset}>
              <RotateCcw className="mr-1.5 size-3.5" />
              Try again
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={copy}>
            {copied ? (
              <Check className="mr-1.5 size-3.5" />
            ) : (
              <Copy className="mr-1.5 size-3.5" />
            )}
            {copied ? "Copied" : "Copy details"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
