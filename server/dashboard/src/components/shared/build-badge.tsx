"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/utils/api";
import { SYSTEM_ENDPOINTS } from "@/utils/api-endpoints";
import {
  APP_VERSION,
  BUILD_LABEL,
  BUILT_AT,
  GIT_SHA,
  isBuildMismatch,
  type ServerVersion,
} from "@/lib/build-info";

/**
 * Which build is running, in the sidebar footer.
 *
 * Shows the dashboard's own baked version, and compares it against the API's.
 * A mismatch means the two halves were deployed from different commits, which
 * is otherwise invisible and produces symptoms that look like random bugs.
 */
export function BuildBadge() {
  const [copied, setCopied] = useState(false);

  const { data: server } = useApiQuery<ServerVersion | undefined>(
    async () => {
      const res = await api.get<ServerVersion>(SYSTEM_ENDPOINTS.VERSION);
      return res.data;
    },
    // Deliberately no errorToast: an unreachable version endpoint is not worth
    // interrupting the user over, and the badge simply falls back to the
    // locally-baked values.
    { initialData: undefined },
  );

  const mismatch = isBuildMismatch(server);

  const details = [
    `dashboard: ${APP_VERSION} (${GIT_SHA})`,
    `built:     ${BUILT_AT}`,
    server ? `api:       ${server.version} (${server.git_sha})` : null,
    server ? `api built: ${server.built_at}` : null,
    server ? `mem0 core: ${server.mem0_core}` : null,
    server ? `python:    ${server.python}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(details);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard needs a secure context; the tooltip already shows the values.
    }
  };

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={copy}
          aria-label="Copy build details"
          className="group flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left font-mono text-[10px] text-onSurface-default-tertiary transition-colors hover:bg-surface-default-secondary-hover hover:text-onSurface-default-secondary"
        >
          {mismatch && (
            <span
              aria-hidden
              className="size-1.5 shrink-0 rounded-full bg-onSurface-danger-primary"
            />
          )}
          <span className="truncate">{BUILD_LABEL}</span>
          {copied ? (
            <Check className="ml-auto size-3 shrink-0" />
          ) : (
            <Copy className="ml-auto size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" align="start">
        <pre className="font-mono text-[11px] leading-relaxed">{details}</pre>
        {mismatch && (
          <p className="mt-1.5 max-w-56 text-[11px] text-onSurface-danger-primary">
            The dashboard and API were built from different commits. Redeploy
            both from the same revision.
          </p>
        )}
      </TooltipContent>
    </Tooltip>
  );
}
