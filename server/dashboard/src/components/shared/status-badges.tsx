"use client";

import { cn } from "@/lib/utils";
import { TONE_BADGE, type Tone } from "@/lib/tones";

/* -------------------------------------------------------------------------- */
/* Request type                                                                */
/* -------------------------------------------------------------------------- */

export type RequestType =
  | "add"
  | "search"
  | "get_all"
  | "get"
  | "update"
  | "delete"
  | "delete_all"
  | "other";

const REQUEST_TYPE_LABEL: Record<RequestType, string> = {
  add: "ADD",
  search: "SEARCH",
  get_all: "GET ALL",
  get: "GET",
  update: "UPDATE",
  delete: "DELETE",
  delete_all: "DELETE ALL",
  other: "OTHER",
};

// Tones are assigned by what the call does to the data, not by HTTP verb:
// writes are green, reads are blue/violet, removals are red. That way a table
// of mixed traffic reads as "what happened" at a glance.
const REQUEST_TYPE_TONE: Record<RequestType, Tone> = {
  add: "good",
  search: "info",
  get_all: "violet",
  get: "violet",
  update: "warn",
  delete: "bad",
  delete_all: "bad",
  other: "neutral",
};

export function TypeBadge({
  type,
  className,
}: {
  type: RequestType | string;
  className?: string;
}) {
  const key = (type in REQUEST_TYPE_LABEL ? type : "other") as RequestType;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[11px] font-semibold tracking-wide",
        TONE_BADGE[REQUEST_TYPE_TONE[key]],
        className,
      )}
    >
      {REQUEST_TYPE_LABEL[key]}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Memory lifecycle                                                            */
/* -------------------------------------------------------------------------- */

export type LifecycleState =
  | "active"
  | "superseded"
  | "merged"
  | "pattern"
  | "expired";

const LIFECYCLE_LABEL: Record<LifecycleState, string> = {
  active: "Active",
  superseded: "Superseded",
  merged: "Merged",
  pattern: "Pattern",
  expired: "Expired",
};

// Superseded and merged are history, not failure — muted rather than red. Only
// "expired" gets a warning tone, because it is the one state where a memory has
// silently stopped being returned.
const LIFECYCLE_TONE: Record<LifecycleState, Tone> = {
  active: "neutral",
  superseded: "muted",
  merged: "muted",
  pattern: "violet",
  expired: "warn",
};

export const LIFECYCLE_DESCRIPTION: Record<LifecycleState, string> = {
  active: "Current. Returned by every read.",
  superseded: "Replaced by a newer fact. Still returned, labelled as history.",
  merged: "Folded into a canonical memory. Hidden unless you ask for it.",
  pattern: "Distilled by Dream from several source memories.",
  expired: "Past its expiration date. Retained but no longer returned.",
};

export function LifecycleBadge({
  state,
  className,
}: {
  state: LifecycleState | string;
  className?: string;
}) {
  const key = (state in LIFECYCLE_LABEL ? state : "active") as LifecycleState;
  return (
    <span
      title={LIFECYCLE_DESCRIPTION[key]}
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium",
        TONE_BADGE[LIFECYCLE_TONE[key]],
        className,
      )}
    >
      {LIFECYCLE_LABEL[key]}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* HTTP method                                                                 */
/* -------------------------------------------------------------------------- */

const METHOD_TONE: Record<string, Tone> = {
  POST: "info",
  PUT: "warn",
  PATCH: "warn",
  DELETE: "bad",
  GET: "neutral",
};

export function MethodBadge({
  method,
  className,
}: {
  method: string;
  className?: string;
}) {
  const upper = method.toUpperCase();
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[11px] font-semibold",
        TONE_BADGE[METHOD_TONE[upper] ?? "neutral"],
        className,
      )}
    >
      {upper}
    </span>
  );
}
