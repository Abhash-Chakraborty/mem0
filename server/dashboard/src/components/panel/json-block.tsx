"use client";

import { useMemo, useState } from "react";
import { Check, ChevronDown, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

interface JsonBlockProps {
  value: unknown;
  /** Lines shown before collapsing behind "Show all". */
  maxLines?: number;
  className?: string;
  /** Shown instead of the block when `value` is null/undefined/empty. */
  emptyLabel?: string;
}

type Token = { text: string; kind: "key" | "string" | "number" | "punct" };

/**
 * Tokenize one line of already-formatted JSON for colouring.
 *
 * A real parser is overkill here: the input is always the output of
 * JSON.stringify, so the grammar per line is `"key": value` or a bare value,
 * and a regex over quoted runs plus numbers covers it. Anything unmatched falls
 * through as punctuation, which is the safe default.
 */
function tokenize(line: string): Token[] {
  const tokens: Token[] = [];
  const pattern =
    /("(?:[^"\\]|\\.)*"\s*:)|("(?:[^"\\]|\\.)*")|(-?\d+\.?\d*(?:[eE][+-]?\d+)?)|(true|false|null)/g;
  let last = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(line)) !== null) {
    if (match.index > last) {
      tokens.push({ text: line.slice(last, match.index), kind: "punct" });
    }
    if (match[1]) tokens.push({ text: match[1], kind: "key" });
    else if (match[2]) tokens.push({ text: match[2], kind: "string" });
    else tokens.push({ text: match[3] ?? match[4], kind: "number" });
    last = match.index + match[0].length;
  }
  if (last < line.length) {
    tokens.push({ text: line.slice(last), kind: "punct" });
  }
  return tokens;
}

const TOKEN_CLASS: Record<Token["kind"], string> = {
  key: "text-sky-600 dark:text-sky-400",
  string: "text-emerald-600 dark:text-emerald-400",
  number: "text-amber-600 dark:text-amber-400",
  punct: "text-onSurface-default-tertiary",
};

/** Count top-level keys, for the "N keys" note beside a section label. */
export function keyCount(value: unknown): number {
  if (!value || typeof value !== "object" || Array.isArray(value)) return 0;
  return Object.keys(value as Record<string, unknown>).length;
}

/**
 * Read-only JSON viewer with copy, used for request payloads, filters and
 * memory metadata.
 *
 * Long values collapse rather than pushing the rest of the panel off screen —
 * a captured request body can be thousands of lines, and the panel's job is to
 * show what a record is, not to be a file viewer.
 */
export function JsonBlock({
  value,
  maxLines = 40,
  className,
  emptyLabel = "None",
}: JsonBlockProps) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const text = useMemo(() => {
    if (value === null || value === undefined) return "";
    try {
      return typeof value === "string" ? value : JSON.stringify(value, null, 2);
    } catch {
      // Circular structures are possible in captured payloads.
      return String(value);
    }
  }, [value]);

  const lines = useMemo(() => (text ? text.split("\n") : []), [text]);
  const isEmpty =
    !text || text === "{}" || text === "[]" || text.trim().length === 0;
  const overflows = lines.length > maxLines;
  const shown = expanded ? lines : lines.slice(0, maxLines);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard needs a secure context; the content is on screen regardless.
    }
  };

  if (isEmpty) {
    return (
      <p className="text-sm text-onSurface-default-tertiary">{emptyLabel}</p>
    );
  }

  return (
    <div
      className={cn(
        "group relative rounded-md border border-memBorder-primary bg-surface-default-secondary",
        className,
      )}
    >
      <button
        type="button"
        onClick={copy}
        aria-label="Copy JSON"
        className="absolute right-2 top-2 z-10 rounded border border-memBorder-primary bg-surface-default-primary p-1.5 text-onSurface-default-tertiary opacity-0 transition-opacity hover:text-onSurface-default-primary focus-visible:opacity-100 group-hover:opacity-100"
      >
        {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
      </button>

      <pre className="overflow-x-auto p-3 font-mono text-[12px] leading-[1.7]">
        <code>
          {shown.map((line, i) => (
            <div key={i}>
              {tokenize(line).map((token, j) => (
                <span key={j} className={TOKEN_CLASS[token.kind]}>
                  {token.text}
                </span>
              ))}
            </div>
          ))}
        </code>
      </pre>

      {overflows && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex w-full items-center justify-center gap-1 border-t border-memBorder-primary py-1.5 text-[11px] text-onSurface-default-tertiary transition-colors hover:text-onSurface-default-primary"
        >
          <ChevronDown
            className={cn(
              "size-3 transition-transform",
              expanded && "rotate-180",
            )}
          />
          {expanded
            ? "Show less"
            : `Show all ${lines.length.toLocaleString()} lines`}
        </button>
      )}
    </div>
  );
}
