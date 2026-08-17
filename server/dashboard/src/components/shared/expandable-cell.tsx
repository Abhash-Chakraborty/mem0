"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface ExpandableCellProps {
  text: string;
  /** Lines shown before clamping. */
  lines?: number;
  className?: string;
}

/**
 * Long text in a table cell, clamped with an inline expand.
 *
 * Expands in place rather than opening the detail panel, because the two
 * actions answer different questions: "what does this row say in full" and
 * "show me everything about this record". Conflating them means you cannot read
 * a long memory without losing your place in the list.
 */
export function ExpandableCell({
  text,
  lines = 1,
  className,
}: ExpandableCellProps) {
  const [expanded, setExpanded] = useState(false);
  const [clamped, setClamped] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  // Only offer the chevron when the text is actually cut off. Measured after
  // layout rather than guessed from length, since the column is fluid.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setClamped(el.scrollHeight > el.clientHeight + 1);
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text]);

  return (
    <div className={cn("flex min-w-0 items-start gap-1.5", className)}>
      <span
        ref={ref}
        className={cn(
          "min-w-0 flex-1 text-sm",
          !expanded && "overflow-hidden text-ellipsis",
        )}
        style={
          expanded
            ? undefined
            : {
                display: "-webkit-box",
                WebkitLineClamp: lines,
                WebkitBoxOrient: "vertical",
              }
        }
      >
        {text}
      </span>
      {(clamped || expanded) && (
        <button
          type="button"
          aria-label={expanded ? "Collapse" : "Expand"}
          aria-expanded={expanded}
          onClick={(e) => {
            // The row itself opens the panel; expanding must not also do that.
            e.stopPropagation();
            setExpanded((v) => !v);
          }}
          className="mt-0.5 shrink-0 rounded text-onSurface-default-tertiary transition-colors hover:text-onSurface-default-primary"
        >
          <ChevronDown
            className={cn(
              "size-4 transition-transform",
              expanded && "rotate-180",
            )}
          />
        </button>
      )}
    </div>
  );
}
