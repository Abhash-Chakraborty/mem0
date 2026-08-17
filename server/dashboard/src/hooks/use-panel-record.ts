"use client";

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

interface UsePanelRecordOptions<T> {
  /** The list currently on screen. Stepping moves within this, in this order. */
  records: T[];
  /** Stable identity for a record. */
  getId: (record: T) => string;
  /** Query parameter carrying the open record, e.g. "memoryId". */
  param: string;
}

interface UsePanelRecordResult<T> {
  selected: T | undefined;
  open: boolean;
  /** Open a record, or pass null to close. */
  select: (record: T | null) => void;
  close: () => void;
  next: () => void;
  prev: () => void;
  hasNext: boolean;
  hasPrev: boolean;
  /** Index within `records`, or -1 when nothing is selected. */
  index: number;
}

/**
 * Keeps the open detail panel in the URL.
 *
 * Three things fall out of storing it there rather than in component state: the
 * panel survives a refresh, a link to a specific record is shareable, and the
 * browser back button closes the panel instead of leaving the page — which is
 * what people actually expect from a slide-over.
 *
 * Navigation uses `replace` with `scroll: false` so stepping through records
 * does not stack fifty history entries or jump the list back to the top.
 */
export function usePanelRecord<T>({
  records,
  getId,
  param,
}: UsePanelRecordOptions<T>): UsePanelRecordResult<T> {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const currentId = searchParams.get(param);

  const index = useMemo(() => {
    if (!currentId) return -1;
    return records.findIndex((r) => getId(r) === currentId);
  }, [currentId, records, getId]);

  const selected = index >= 0 ? records[index] : undefined;

  const setParam = useCallback(
    (id: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (id) params.set(param, id);
      else params.delete(param);
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [param, pathname, router, searchParams],
  );

  const select = useCallback(
    (record: T | null) => setParam(record ? getId(record) : null),
    [getId, setParam],
  );

  const close = useCallback(() => setParam(null), [setParam]);

  const hasPrev = index > 0;
  const hasNext = index >= 0 && index < records.length - 1;

  const prev = useCallback(() => {
    if (hasPrev) setParam(getId(records[index - 1]));
  }, [hasPrev, getId, records, index, setParam]);

  const next = useCallback(() => {
    if (hasNext) setParam(getId(records[index + 1]));
  }, [hasNext, getId, records, index, setParam]);

  return {
    selected,
    // A record id in the URL that is not in the current list — filtered out,
    // on another page — must not leave a blank panel open.
    open: selected !== undefined,
    select,
    close,
    next,
    prev,
    hasNext,
    hasPrev,
    index,
  };
}
