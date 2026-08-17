"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

interface CopyInlineProps {
  /** What lands on the clipboard. */
  value: string;
  /** What the user sees. Defaults to `value`, truncated in the middle. */
  label?: string;
  className?: string;
  /** Announced to screen readers, e.g. "Copy request ID". */
  ariaLabel?: string;
}

/** Shorten an identifier from the middle: `cac38591…e098f0`. */
export function truncateId(id: string, head = 8, tail = 6): string {
  if (id.length <= head + tail + 1) return id;
  return `${id.slice(0, head)}…${id.slice(-tail)}`;
}

/**
 * An identifier you can click to copy.
 *
 * Used in panel meta lines where the full value is too long to show but is
 * exactly what someone needs to paste into a support thread or a query.
 */
export function CopyInline({
  value,
  label,
  className,
  ariaLabel = "Copy",
}: CopyInlineProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard needs a secure context. The value is visible either way.
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={ariaLabel}
      title={value}
      className={cn(
        "group inline-flex items-center gap-1 rounded font-mono transition-colors hover:text-onSurface-default-primary",
        className,
      )}
    >
      <span>{label ?? truncateId(value)}</span>
      {copied ? (
        <Check className="size-3 shrink-0" />
      ) : (
        <Copy className="size-3 shrink-0 opacity-50 transition-opacity group-hover:opacity-100" />
      )}
    </button>
  );
}
