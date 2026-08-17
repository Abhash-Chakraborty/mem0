"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { ChevronDown, ChevronUp, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { CopyInline } from "@/components/shared/copy-inline";
import { TONE_BADGE, TONE_DOT, type Tone } from "@/lib/tones";

export interface PanelTab {
  id: string;
  label: string;
  /** Rendered as a small pill after the label. `0` still shows, `undefined` does not. */
  count?: number;
}

export interface PanelRow {
  label: string;
  node: React.ReactNode;
}

export interface DetailPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;

  /** Leading badge, e.g. the request type. */
  badge?: { label: string; tone?: Tone };
  /** Dot + label to the right of the badge, e.g. "Succeeded". */
  status?: { label: string; tone?: Tone };

  title: React.ReactNode;
  /** Monospace facts under the title, joined with a divider. */
  meta?: React.ReactNode[];
  /** Identifier appended to the meta line with a copy affordance. */
  copyId?: string;

  /** Keyed rows between the meta line and the tabs. */
  rows?: PanelRow[];

  tabs?: PanelTab[];
  activeTab?: string;
  onTabChange?: (id: string) => void;

  /** Step to the previous/next record. Omit to hide the chevrons. */
  onPrev?: () => void;
  onNext?: () => void;
  hasPrev?: boolean;
  hasNext?: boolean;

  children: React.ReactNode;
  className?: string;
}

/**
 * The right-hand detail view, used by every list in the dashboard.
 *
 * Built on Radix Dialog rather than the existing Sheet because this needs a
 * fixed header with its own controls over a scrolling body, and Sheet's uniform
 * `p-6` fights that. Radix still gives the focus trap, scroll lock, Esc
 * handling and aria wiring for free.
 *
 * Record stepping is a first-class part of the contract: scanning a list one
 * record at a time is the main way these panels get used, so ↑/↓ move between
 * records while the panel is open and the header chevrons do the same thing for
 * the mouse.
 */
export function DetailPanel({
  open,
  onOpenChange,
  badge,
  status,
  title,
  meta,
  copyId,
  rows,
  tabs,
  activeTab,
  onTabChange,
  onPrev,
  onNext,
  hasPrev = true,
  hasNext = true,
  children,
  className,
}: DetailPanelProps) {
  // Arrow keys step records. Bound on the content rather than the document so
  // it dies with the panel and never leaks into the page behind it.
  const handleKeyDown = (event: React.KeyboardEvent) => {
    const target = event.target as HTMLElement;
    // Never hijack arrows away from something the user is typing or scrolling in.
    if (
      target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.isContentEditable
    ) {
      return;
    }
    if (event.key === "ArrowDown" && onNext && hasNext) {
      event.preventDefault();
      onNext();
    } else if (event.key === "ArrowUp" && onPrev && hasPrev) {
      event.preventDefault();
      onPrev();
    }
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[1px] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          onKeyDown={handleKeyDown}
          className={cn(
            "fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-memBorder-primary bg-surface-default-primary font-fustat shadow-2xl outline-none",
            "sm:max-w-[560px] lg:max-w-[720px]",
            "duration-200 ease-[cubic-bezier(.32,.72,0,1)] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right",
            className,
          )}
        >
          {/* Header — fixed, never scrolls with the body. */}
          <div className="shrink-0 border-b border-memBorder-primary px-5 pb-4 pt-4">
            <div className="mb-2.5 flex items-center gap-2.5">
              {badge && (
                <span
                  className={cn(
                    "inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 font-mono text-[11px] font-semibold tracking-wide",
                    TONE_BADGE[badge.tone ?? "violet"],
                  )}
                >
                  {badge.label}
                </span>
              )}
              {status && (
                <span className="inline-flex items-center gap-1.5 text-xs text-onSurface-default-secondary">
                  <span
                    aria-hidden
                    className={cn(
                      "size-1.5 rounded-full",
                      TONE_DOT[status.tone ?? "good"],
                    )}
                  />
                  {status.label}
                </span>
              )}

              <div className="ml-auto flex items-center gap-0.5">
                {onPrev && (
                  <button
                    type="button"
                    onClick={onPrev}
                    disabled={!hasPrev}
                    aria-label="Previous record"
                    className="rounded p-1 text-onSurface-default-tertiary transition-colors hover:bg-surface-default-secondary hover:text-onSurface-default-primary disabled:pointer-events-none disabled:opacity-30"
                  >
                    <ChevronUp className="size-4" />
                  </button>
                )}
                {onNext && (
                  <button
                    type="button"
                    onClick={onNext}
                    disabled={!hasNext}
                    aria-label="Next record"
                    className="rounded p-1 text-onSurface-default-tertiary transition-colors hover:bg-surface-default-secondary hover:text-onSurface-default-primary disabled:pointer-events-none disabled:opacity-30"
                  >
                    <ChevronDown className="size-4" />
                  </button>
                )}
                <DialogPrimitive.Close
                  aria-label="Close panel"
                  className="ml-1 rounded p-1 text-onSurface-default-tertiary transition-colors hover:bg-surface-default-secondary hover:text-onSurface-default-primary"
                >
                  <X className="size-4" />
                </DialogPrimitive.Close>
              </div>
            </div>

            <DialogPrimitive.Title className="text-balance text-[17px] font-semibold leading-snug text-onSurface-default-primary">
              {title}
            </DialogPrimitive.Title>
            {/* Radix warns without a description; the meta line is not one. */}
            <DialogPrimitive.Description className="sr-only">
              Detail view
            </DialogPrimitive.Description>

            {(meta?.length || copyId) && (
              <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11.5px] text-onSurface-default-tertiary">
                {meta?.map((item, i) => (
                  <React.Fragment key={i}>
                    {i > 0 && <span aria-hidden>|</span>}
                    <span>{item}</span>
                  </React.Fragment>
                ))}
                {copyId && (
                  <>
                    {meta?.length ? <span aria-hidden>|</span> : null}
                    <CopyInline value={copyId} ariaLabel="Copy ID" />
                  </>
                )}
              </div>
            )}

            {rows && rows.length > 0 && (
              <dl className="mt-3 grid grid-cols-[minmax(72px,max-content)_1fr] items-center gap-x-6 gap-y-1.5">
                {rows.map((row) => (
                  <React.Fragment key={row.label}>
                    <dt className="text-xs text-onSurface-default-tertiary">
                      {row.label}
                    </dt>
                    <dd className="min-w-0 text-sm text-onSurface-default-primary">
                      {row.node}
                    </dd>
                  </React.Fragment>
                ))}
              </dl>
            )}

            {tabs && tabs.length > 0 && (
              <div
                role="tablist"
                className="-mb-4 mt-3 flex items-center gap-4 border-b border-transparent"
              >
                {tabs.map((tab) => {
                  const selected = tab.id === activeTab;
                  return (
                    <button
                      key={tab.id}
                      role="tab"
                      type="button"
                      aria-selected={selected}
                      onClick={() => onTabChange?.(tab.id)}
                      className={cn(
                        "-mb-px flex items-center gap-1.5 border-b-2 pb-2.5 text-sm transition-colors",
                        selected
                          ? "border-onSurface-default-primary text-onSurface-default-primary"
                          : "border-transparent text-onSurface-default-tertiary hover:text-onSurface-default-secondary",
                      )}
                    >
                      {tab.label}
                      {tab.count !== undefined && (
                        <span
                          className={cn(
                            "rounded px-1.5 py-0.5 font-mono text-[10px]",
                            selected
                              ? "bg-surface-default-tertiary text-onSurface-default-secondary"
                              : "bg-surface-default-secondary text-onSurface-default-tertiary",
                          )}
                        >
                          {tab.count}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Body — the only scrolling region. */}
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {children}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
