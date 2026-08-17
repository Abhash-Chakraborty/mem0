"use client";

import { cn } from "@/lib/utils";

interface PanelSectionProps {
  /** Uppercased in CSS, so pass it in natural case. */
  label: string;
  /** Small monospace note after the label, e.g. "1 key" or "16 memories". */
  note?: string;
  /** Right-aligned control, e.g. a Save button. */
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

/**
 * A labelled block inside a DetailPanel.
 *
 * The label is a monospace all-caps eyebrow rather than a heading because these
 * are field names in a record, not sections of a document — the visual weight
 * belongs to the value, not the label.
 */
export function PanelSection({
  label,
  note,
  action,
  children,
  className,
}: PanelSectionProps) {
  return (
    <section className={cn("mb-6 last:mb-0", className)}>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.08em] text-onSurface-default-tertiary">
          {label}
        </h3>
        {note && (
          <span className="font-mono text-[10.5px] text-onSurface-default-tertiary">
            {note}
          </span>
        )}
        {action && <div className="ml-auto">{action}</div>}
      </div>
      {children}
    </section>
  );
}
